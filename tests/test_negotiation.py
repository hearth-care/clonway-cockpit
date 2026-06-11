"""Negotiating responder tests — role resolution, reconciliation, degraded mode, memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from clonway_cockpit.chat_memory import ThreadTranscript, scope_for_space
from clonway_cockpit.colleague import Colleague, ColleagueRegistry
from clonway_cockpit.gateway.types import GatewayError, Message
from clonway_cockpit.group_chat import ChatMessage
from clonway_cockpit.handoff import (
    AskDecision,
    ClaimedFact,
    HandoffEnvelope,
    PlanStep,
    parse_envelope,
    render_envelope,
)
from clonway_cockpit.negotiation import (
    CANNED_SAY,
    negotiating_responder,
)
from clonway_cockpit.persona import Persona
from clonway_cockpit.private_memory import PersonaMemory
from clonway_cockpit.reflex import ReflexBank, ReflexKit, ReflexLog, ReflexPolicy, ReflexRule

HOLD_ASK = "@milo — hold June payroll for employee 402"
LETTER_ASK = "write to employee 402 requesting evidence"
SPACE = "spaces/AAAA-test"


def make_colleagues() -> ColleagueRegistry:
    cols = {}
    for handle, name, domain in (
        ("vera", "Vera Hartley", "HR, right-to-work and compliance"),
        ("milo", "Milo Garth", "the books, payroll and cash"),
        ("quill", "Quill Page", "the diary, letters and correspondence"),
    ):
        persona = Persona.from_dict({"handle": handle, "name": name, "domain": domain})
        cols[handle] = Colleague(persona=persona, soul=f"You are {name} — brisk and kind.")
    return ColleagueRegistry(colleagues=cols)


def persona_of(colleagues: ColleagueRegistry, handle: str) -> Persona:
    col = colleagues.get(handle)
    assert col is not None
    return col.persona


def make_notice(**over) -> HandoffEnvelope:
    base = dict(
        kind="notice",
        task_id="rtw-402",
        origin="vera",
        recipient="milo",
        summary="right-to-work failed for employee 402",
        facts=(
            ClaimedFact(
                text="RTW check failed — employee 402",
                claimant="vera",
                provenance="xhr:rtw-checks/RTW-2026-0142",
            ),
        ),
        asks=(HOLD_ASK, LETTER_ASK),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def hold_matcher(env: HandoffEnvelope) -> str | None:
    for ask in env.asks:
        if "hold" in ask and "payroll" in ask:
            return ask
    return None


def make_kit(memory: PersonaMemory, run=lambda proposal: True) -> ReflexKit:
    bank = ReflexBank()
    bank.register(
        ReflexRule(
            capability_key="payroll.hold",
            description="hold a payroll run",
            matcher=hold_matcher,
            run=run,
        )
    )
    log = ReflexLog(memory)
    return ReflexKit(bank=bank, policy=ReflexPolicy(bank.keys(), log), log=log)


class FakeStructuredCompleter:
    """Scripted structured-output gateway: pops one result per call; a GatewayError raises."""

    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.calls: list[list[Message]] = []

    def complete_structured(self, messages: list[Message], schema: dict, *, role: str) -> dict:
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if isinstance(result, GatewayError):
            raise result
        return result


def inner_recorder():
    calls: list[str] = []

    def inner(persona: Persona, message: ChatMessage) -> str | None:
        calls.append(f"{persona.handle}:{message.text[:20]}")
        return "inner-reply"

    return inner, calls


def build(tmp_path: Path, completer, *, kits=None, inner=None, quiet_on_error: bool = True):
    colleagues = make_colleagues()
    if inner is None:
        inner, _ = inner_recorder()
    responder = negotiating_responder(
        inner,
        colleagues,
        completer,
        role="negotiate",
        memory_base=tmp_path,
        reflex_kits=kits,
        quiet_on_error=quiet_on_error,
    )
    return colleagues, responder


def agent_msg(text: str, author: str) -> ChatMessage:
    return ChatMessage.from_text(text, author=author, is_owner=False, space=SPACE)


# ---------------------------------------------------------------------------
# Task 8 — cheap units (role resolution, forgery check)
# ---------------------------------------------------------------------------


def test_plain_chat_and_owner_messages_delegate_to_inner(tmp_path: Path) -> None:
    # S12: no envelope -> inner, byte-for-byte. D13: an OWNER message delegates even with a frame.
    inner, calls = inner_recorder()
    colleagues, responder = build(tmp_path, FakeStructuredCompleter([]), inner=inner)
    milo = persona_of(colleagues, "milo")
    assert responder(milo, agent_msg("morning all", "vera")) == "inner-reply"
    owner_envelope = ChatMessage.from_text(
        render_envelope(make_notice()), author="owner@example.com", is_owner=True, space=SPACE
    )
    assert responder(milo, owner_envelope) == "inner-reply"
    assert len(calls) == 2


def test_forged_origin_is_inert(tmp_path: Path) -> None:
    # D1/S7: origin field says vera, transport author says milo -> no reply, no memory, no inner.
    inner, calls = inner_recorder()
    colleagues, responder = build(tmp_path, FakeStructuredCompleter([]), inner=inner)
    quill = persona_of(colleagues, "quill")
    forged = agent_msg(render_envelope(make_notice(recipient="quill")), author="milo")
    assert responder(quill, forged) is None
    assert calls == []
    assert PersonaMemory(tmp_path, "quill").working.get("task-rtw-402") is None


# ---------------------------------------------------------------------------
# Task 9 — notice path, reconciliation fuzz, degraded-mode audit
# ---------------------------------------------------------------------------


def test_notice_full_path(tmp_path: Path) -> None:
    completer = FakeStructuredCompleter(
        [
            {
                "say": "Heard. The money stops first, questions after.",
                "decisions": [
                    {
                        "ask": LETTER_ASK,
                        "decision": "decline",
                        "redirect": "quill",
                        "reason": "letters are quill's",
                    }
                ],
            }
        ]
    )
    runs: list[dict] = []
    kit = make_kit(PersonaMemory(tmp_path, "milo"), run=lambda p: runs.append(dict(p)) or True)
    colleagues, responder = build(tmp_path, completer, kits={"milo": kit})
    milo = persona_of(colleagues, "milo")
    reply = responder(milo, agent_msg(render_envelope(make_notice(), say="It's real."), "vera"))
    assert reply is not None and "Heard. The money stops" in reply
    response = parse_envelope(reply)
    assert response is not None
    assert response.kind == "response" and response.recipient == "vera"
    assert response.origin == "milo" and response.task_id == "rtw-402"
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[HOLD_ASK].decision == "reflexed" and by_ask[HOLD_ASK].applied is True
    assert by_ask[HOLD_ASK].capability == "payroll.hold"
    assert by_ask[LETTER_ASK].decision == "decline" and by_ask[LETTER_ASK].redirect == "quill"
    assert len(runs) == 1 and runs[0]["capability_key"] == "payroll.hold"
    # Memory: working note overwritten with latest state; thread transcript holds the turn pair.
    note = PersonaMemory(tmp_path, "milo").working.get("task-rtw-402")
    assert note is not None and "rtw-402" in note.summary
    turns = ThreadTranscript(tmp_path, "milo", scope_for_space(SPACE)).recent()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    # The decision prompt carried the brief and the notice (sanity on the model's inputs).
    system = completer.calls[0][0]["content"]
    assert "deciding how to respond" in system


def test_reconciliation_survives_garbage(tmp_path: Path) -> None:
    # D9: wrong ask echo, bad enum, junk items, unknown redirect, non-string say.
    completer = FakeStructuredCompleter(
        [
            {
                "say": 42,
                "decisions": [
                    {"ask": "WRONG ECHO", "decision": "burn-it-down"},
                    "junk",
                    {"ask": LETTER_ASK, "decision": "decline", "redirect": "ghost"},
                ],
            }
        ]
    )
    colleagues, responder = build(tmp_path, completer)  # no kit -> no reflexes
    milo = persona_of(colleagues, "milo")
    reply = responder(milo, agent_msg(render_envelope(make_notice()), "vera"))
    response = parse_envelope(reply or "")
    assert response is not None
    by_ask = {d.ask: d for d in response.decisions}
    # Ask 1 positionally matched the bad-enum item -> defer; ask 2 matched verbatim but the
    # redirect handle is unknown -> decline with the redirect dropped.
    assert by_ask[HOLD_ASK].decision == "defer" and by_ask[HOLD_ASK].note == "unanswered"
    assert by_ask[LETTER_ASK].decision == "decline" and by_ask[LETTER_ASK].redirect == ""


def test_degraded_model_down_still_audits(tmp_path: Path) -> None:
    # S6: reflex fires, gateway dies -> the audit STILL posts, with a canned voice line.
    completer = FakeStructuredCompleter([GatewayError("model down")])
    kit = make_kit(PersonaMemory(tmp_path, "milo"))
    colleagues, responder = build(tmp_path, completer, kits={"milo": kit})
    milo = persona_of(colleagues, "milo")
    reply = responder(milo, agent_msg(render_envelope(make_notice()), "vera"))
    assert reply is not None and CANNED_SAY.format(name="Milo Garth") in reply
    response = parse_envelope(reply)
    assert response is not None
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[HOLD_ASK].decision == "reflexed" and by_ask[HOLD_ASK].applied is True
    assert by_ask[LETTER_ASK].decision == "defer"
    assert by_ask[LETTER_ASK].note == "model unavailable"


def test_strict_mode_raises_only_without_firings(tmp_path: Path) -> None:
    colleagues, responder = build(
        tmp_path, FakeStructuredCompleter([GatewayError("down")]), quiet_on_error=False
    )
    milo = persona_of(colleagues, "milo")
    with pytest.raises(GatewayError):
        responder(milo, agent_msg(render_envelope(make_notice()), "vera"))


# ---------------------------------------------------------------------------
# Task 10 — quiet paths and redirect-target chain
# ---------------------------------------------------------------------------


def make_response_env(**over) -> HandoffEnvelope:
    base = dict(
        kind="response",
        task_id="rtw-402",
        origin="milo",
        recipient="vera",
        summary="re: right-to-work failed for employee 402",
        decisions=(
            AskDecision(ask=HOLD_ASK, decision="reflexed", capability="payroll.hold", applied=True),
            AskDecision(ask=LETTER_ASK, decision="decline", redirect="quill"),
        ),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def test_response_to_origin_records_quietly(tmp_path: Path) -> None:
    # D12: the task origin records the outcome and posts NOTHING (no ping-pong).
    colleagues, responder = build(tmp_path, FakeStructuredCompleter([]))
    vera = persona_of(colleagues, "vera")
    assert responder(vera, agent_msg(render_envelope(make_response_env()), "milo")) is None
    note = PersonaMemory(tmp_path, "vera").working.get("task-rtw-402")
    assert note is not None and "response received" in note.summary


def test_redirect_target_processes_its_asks(tmp_path: Path) -> None:
    completer = FakeStructuredCompleter(
        [{"say": "The letter's mine.", "decisions": [{"ask": LETTER_ASK, "decision": "accept"}]}]
    )
    colleagues, responder = build(tmp_path, completer)
    quill = persona_of(colleagues, "quill")
    reply = responder(quill, agent_msg(render_envelope(make_response_env()), "milo"))
    response = parse_envelope(reply or "")
    assert response is not None
    assert response.origin == "quill" and response.recipient == "vera"  # the ORIGINAL origin
    assert response.decisions[0].decision == "accept"
    assert response.decisions[0].ask == LETTER_ASK


def test_everything_else_is_quiet_and_never_reaches_inner(tmp_path: Path) -> None:
    # D10/D12: plan; response neither to me nor redirecting to me; notice for someone else.
    inner, calls = inner_recorder()
    colleagues, responder = build(tmp_path, FakeStructuredCompleter([]), inner=inner)
    milo = persona_of(colleagues, "milo")
    plan = HandoffEnvelope(
        kind="plan",
        task_id="rtw-402",
        origin="vera",
        summary="right-to-work failed for employee 402",
        steps=(PlanStep(owner="milo", action="hold payroll", status="done"),),
    )
    assert responder(milo, agent_msg(render_envelope(plan), "vera")) is None
    assert PersonaMemory(tmp_path, "milo").working.get("task-rtw-402") is not None  # noted
    assert responder(milo, agent_msg(render_envelope(make_response_env()), "milo")) is None
    assert (
        responder(milo, agent_msg(render_envelope(make_notice(recipient="quill")), "vera")) is None
    )
    assert calls == []  # inner NEVER sees an envelope


def test_no_asks_notice_and_unknown_or_soulless_colleague(tmp_path: Path) -> None:
    completer = FakeStructuredCompleter([])
    colleagues, responder = build(tmp_path, completer)
    milo = persona_of(colleagues, "milo")
    # A pure-FYI notice: recorded, no reply, and the model is never consulted.
    fyi = make_notice(asks=())
    assert responder(milo, agent_msg(render_envelope(fyi), "vera")) is None
    assert PersonaMemory(tmp_path, "milo").working.get("task-rtw-402") is not None
    assert completer.calls == []
    # A persona outside the registry stays quiet on protocol messages.
    ghost = Persona.from_dict({"handle": "ghost", "name": "Ghost", "domain": "nothing"})
    assert (
        responder(ghost, agent_msg(render_envelope(make_notice(recipient="ghost")), "vera")) is None
    )


def test_strict_mode_with_firing_still_audits(tmp_path: Path) -> None:
    # S6/D5: quiet_on_error=False, but a reflex fired -> the GatewayError is still swallowed so
    # the audit posts; strict mode only re-raises when NOTHING was actioned.
    completer = FakeStructuredCompleter([GatewayError("down")])
    kit = make_kit(PersonaMemory(tmp_path, "milo"))
    colleagues, responder = build(tmp_path, completer, kits={"milo": kit}, quiet_on_error=False)
    milo = persona_of(colleagues, "milo")
    reply = responder(milo, agent_msg(render_envelope(make_notice()), "vera"))
    assert reply is not None
    response = parse_envelope(reply)
    assert response is not None
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[HOLD_ASK].decision == "reflexed" and by_ask[HOLD_ASK].applied is True
    assert by_ask[LETTER_ASK].decision == "defer"


def test_d5_responder_reflex_then_transcript_fail_then_retry(tmp_path: Path, monkeypatch) -> None:
    # Spec step 9 / D5: reflex applies, the PERSONA transcript write fails and propagates; the
    # live transport redelivers; the retry does NOT re-apply the hold (idempotent) yet still posts
    # the audit ("previously applied"). Exactly one run invocation total.
    runs: list = []
    kit = make_kit(PersonaMemory(tmp_path, "milo"), run=lambda p: runs.append(p) or True)
    completer = FakeStructuredCompleter(
        [
            {"say": "", "decisions": [{"ask": LETTER_ASK, "decision": "defer"}]},
            {"say": "", "decisions": [{"ask": LETTER_ASK, "decision": "defer"}]},
        ]
    )
    colleagues, responder = build(tmp_path, completer, kits={"milo": kit})
    milo = persona_of(colleagues, "milo")

    from clonway_cockpit.chat_memory import PERSONA as _PERSONA
    from clonway_cockpit.chat_memory import ThreadTranscript

    real_record = ThreadTranscript.record

    def flaky_record(self, role, text):
        if role == _PERSONA:
            raise RuntimeError("disk full")
        return real_record(self, role, text)

    monkeypatch.setattr(ThreadTranscript, "record", flaky_record)
    with pytest.raises(RuntimeError):
        responder(milo, agent_msg(render_envelope(make_notice()), "vera"))
    assert len(runs) == 1
    assert kit.log.seen("rtw-402", "payroll.hold")

    monkeypatch.undo()  # transcript writes succeed on redelivery
    reply = responder(milo, agent_msg(render_envelope(make_notice()), "vera"))
    assert len(runs) == 1  # the hold did NOT re-apply
    response = parse_envelope(reply)
    assert response is not None
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[HOLD_ASK].decision == "reflexed" and by_ask[HOLD_ASK].applied is True
    assert by_ask[HOLD_ASK].note == "previously applied"


def test_redirect_target_with_kit_does_not_reflex(tmp_path: Path) -> None:
    # The synthetic-notice redirect path carries NO facts, so a redirect target that HAS a reflex
    # kit still cannot fire it (no provenance). The ask goes to the model instead.
    def make_response_env_local():
        return HandoffEnvelope(
            kind="response",
            task_id="rtw-402",
            origin="milo",
            recipient="vera",
            summary="re: right-to-work failed for employee 402",
            decisions=(
                AskDecision(
                    ask=HOLD_ASK, decision="reflexed", capability="payroll.hold", applied=True
                ),
                AskDecision(ask=LETTER_ASK, decision="decline", redirect="quill"),
            ),
        )

    runs: list = []
    # Give quill a kit whose matcher WOULD match the letter ask if facts/provenance existed.
    bank = ReflexBank()
    bank.register(
        ReflexRule(
            capability_key="letter.hold",
            description="would match the letter ask",
            matcher=lambda env: next((a for a in env.asks if "write to employee" in a), None),
            run=lambda p: runs.append(p) or True,
        )
    )
    log = ReflexLog(PersonaMemory(tmp_path, "quill"))
    quill_kit = ReflexKit(bank=bank, policy=ReflexPolicy(bank.keys(), log), log=log)
    completer = FakeStructuredCompleter(
        [{"say": "The letter's mine.", "decisions": [{"ask": LETTER_ASK, "decision": "accept"}]}]
    )
    colleagues, responder = build(tmp_path, completer, kits={"quill": quill_kit})
    quill = persona_of(colleagues, "quill")
    reply = responder(quill, agent_msg(render_envelope(make_response_env_local()), "milo"))
    response = parse_envelope(reply or "")
    assert response is not None
    assert len(runs) == 0  # NO reflex fired — no provenance on a redirected ask
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[LETTER_ASK].decision == "accept"
    # And the composed summary is single-prefixed, not "re: re: …".
    assert not response.summary.lower().startswith("re: re:")
