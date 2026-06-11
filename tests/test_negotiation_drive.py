"""Ledger + NegotiatedSpace drive tests — the worked example end-to-end, degraded, stall, cap."""

from __future__ import annotations

from pathlib import Path

import pytest

from clonway_cockpit.colleague import Colleague, ColleagueRegistry
from clonway_cockpit.gateway.types import GatewayError, Message
from clonway_cockpit.group_chat import ChatMessage, FakeChatTransport
from clonway_cockpit.handoff import (
    AskDecision,
    ClaimedFact,
    HandoffEnvelope,
    HandoffError,
    PlanStep,
    parse_envelope,
    render_envelope,
)
from clonway_cockpit.negotiation import (
    NegotiatedSpace,
    TaskLedger,
    address_notice,
    negotiating_responder,
)
from clonway_cockpit.persona import Persona
from clonway_cockpit.private_memory import PersonaMemory
from clonway_cockpit.reflex import ReflexBank, ReflexKit, ReflexLog, ReflexPolicy, ReflexRule

HOLD_ASK = "@milo — hold June payroll for employee 402"
LETTER_ASK = "write to employee 402 requesting evidence"
SPACE = "spaces/AAAA-drive"


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
    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.calls: list[list[Message]] = []

    def complete_structured(self, messages: list[Message], schema: dict, *, role: str) -> dict:
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if isinstance(result, GatewayError):
            raise result
        return result


def agent_msg(text: str, author: str) -> ChatMessage:
    return ChatMessage.from_text(text, author=author, is_owner=False, space=SPACE)


def test_ledger_lifecycle() -> None:
    ledger = TaskLedger()
    notice_msg = agent_msg(render_envelope(make_notice()), "vera")
    ledger.feed(notice_msg)
    assert [t.task_id for t in ledger.unresolved()] == ["rtw-402"]
    # A response whose transport author mismatches its origin is ignored (D1).
    ledger.feed(agent_msg(render_envelope(make_response_env()), "vera"))
    assert len(ledger.unresolved()[0].missing) == 2
    # The real response: hold terminal (done), letter redirected to quill.
    ledger.feed(agent_msg(render_envelope(make_response_env()), "milo"))
    assert ledger.unresolved()[0].missing == (LETTER_ASK,)
    # Only the redirect TARGET can terminalize a redirected ask.
    interloper = HandoffEnvelope(
        kind="response",
        task_id="rtw-402",
        origin="vera",
        recipient="milo",
        summary="re: not yours to accept",
        decisions=(AskDecision(ask=LETTER_ASK, decision="accept"),),
    )
    ledger.feed(agent_msg(render_envelope(interloper), "vera"))
    assert ledger.unresolved() != []
    quill_response = HandoffEnvelope(
        kind="response",
        task_id="rtw-402",
        origin="quill",
        recipient="vera",
        summary="re: the letter",
        decisions=(AskDecision(ask=LETTER_ASK, decision="accept"),),
    )
    ledger.feed(agent_msg(render_envelope(quill_response), "quill"))
    assert ledger.unresolved() == []
    assert ledger.plan_worthy() == ["rtw-402"]
    plan = ledger.compose_plan("rtw-402")
    assert plan is not None and plan.kind == "plan" and plan.origin == "vera"
    assert [(s.owner, s.status) for s in plan.steps] == [
        ("milo", "done"),
        ("quill", "needs-approval"),
    ]
    ledger.mark_planned("rtw-402")
    assert ledger.plan_worthy() == []
    ledger.feed(notice_msg)  # a reused task id is deliberately inert (D14)
    assert ledger.duplicate_notices() == ("rtw-402",)


def build_space(tmp_path: Path, completer, *, kits=None, max_persona_turns: int = 6):
    colleagues = make_colleagues()
    responder = negotiating_responder(
        lambda persona, message: None,  # prose stays quiet in these scenarios
        colleagues,
        completer,
        role="negotiate",
        memory_base=tmp_path,
        reflex_kits=kits,
    )
    transport = FakeChatTransport()
    space = NegotiatedSpace(
        space_id=SPACE,
        registry=colleagues.registry,
        transport=transport,
        responder=responder,
        owner_line="Mr Page",
        max_persona_turns=max_persona_turns,
    )
    return colleagues, transport, space


def test_worked_example_end_to_end(tmp_path: Path) -> None:
    # The spec's message trace: notice -> reflex hold + redirect -> quill accepts -> plan. ONE
    # owner_says/agent_says round carries the whole negotiation; the sweep posts the plan.
    completer = FakeStructuredCompleter(
        [
            {
                "say": "Heard. The money stops first, questions after.",
                "decisions": [{"ask": LETTER_ASK, "decision": "decline", "redirect": "quill"}],
            },
            {"say": "The letter's mine.", "decisions": [{"ask": LETTER_ASK, "decision": "accept"}]},
        ]
    )
    runs: list[dict] = []
    kit = make_kit(PersonaMemory(tmp_path, "milo"), run=lambda p: runs.append(dict(p)) or True)
    colleagues, transport, space = build_space(tmp_path, completer, kits={"milo": kit})
    replies = space.post_notice("vera", make_notice(), say="Checked twice — it's real.")
    assert [r.handle for r in replies] == ["milo", "quill"]
    texts = [text for _space_id, text in transport.posted]
    assert len(texts) == 3  # milo's response, quill's response, the swept plan
    milo_response = parse_envelope(texts[0])
    assert milo_response is not None and milo_response.origin == "milo"
    quill_response = parse_envelope(texts[1])
    assert quill_response is not None
    assert quill_response.origin == "quill" and quill_response.recipient == "vera"
    plan = parse_envelope(texts[2])
    assert plan is not None and plan.kind == "plan"
    assert [(s.owner, s.status) for s in plan.steps] == [
        ("milo", "done"),
        ("quill", "needs-approval"),
    ]
    assert "authorizes nothing" in texts[2]  # S11, rendered
    assert len(runs) == 1  # the hold applied exactly once (S5)
    assert space.ledger.unresolved() == []
    # Both sides remember: origin recorded the outcome, executor recorded its task state.
    assert PersonaMemory(tmp_path, "vera").working.get("task-rtw-402") is not None
    assert PersonaMemory(tmp_path, "milo").working.get("task-rtw-402") is not None


def test_degraded_model_down_still_holds_and_plans(tmp_path: Path) -> None:
    # S6 at the room level: gateway dead -> the hold applies, the audit posts, the plan shows
    # the letter unassigned. The hold NEVER silently happens.
    completer = FakeStructuredCompleter([GatewayError("model down")])
    kit = make_kit(PersonaMemory(tmp_path, "milo"))
    colleagues, transport, space = build_space(tmp_path, completer, kits={"milo": kit})
    space.post_notice("vera", make_notice())
    texts = [text for _space_id, text in transport.posted]
    assert len(texts) == 2  # milo's degraded response + the plan (no quill — no redirect)
    response = parse_envelope(texts[0])
    assert response is not None
    by_ask = {d.ask: d for d in response.decisions}
    assert by_ask[HOLD_ASK].decision == "reflexed" and by_ask[HOLD_ASK].applied is True
    assert by_ask[LETTER_ASK].decision == "defer"
    plan = parse_envelope(texts[1])
    assert plan is not None
    assert [(s.owner, s.status) for s in plan.steps] == [("milo", "done"), ("", "unassigned")]


def test_stall_escalates_once_and_duplicates_are_inert(tmp_path: Path) -> None:
    colleagues, transport, space = build_space(tmp_path, FakeStructuredCompleter([]))
    # vera notices HERSELF (recipient == author): nobody processes it — @milo appears in an ask
    # but he is not the recipient, so his negotiation path stays quiet (D10's role table).
    space.post_notice("vera", make_notice(recipient="vera"))
    texts = [text for _space_id, text in transport.posted]
    assert len(texts) == 1
    assert "unresolved handoff #rtw-402" in texts[0] and "Mr Page" in texts[0]
    space.post_notice("vera", make_notice(recipient="vera"))  # same task id again
    texts = [text for _space_id, text in transport.posted]
    assert len(texts) == 1  # no re-stall (once per task), duplicate notice inert
    assert space.ledger.duplicate_notices() == ("rtw-402",)


def test_turn_cap_orphans_the_redirect_and_stalls(tmp_path: Path) -> None:
    # D19: this is DESIGNED behavior — the cap escalates instead of pushing on. Do not "fix" it
    # by raising the cap in framework code; it is owner-configurable per space.
    completer = FakeStructuredCompleter(
        [
            {
                "say": "",
                "decisions": [{"ask": LETTER_ASK, "decision": "decline", "redirect": "quill"}],
            }
        ]
    )
    kit = make_kit(PersonaMemory(tmp_path, "milo"))
    colleagues, transport, space = build_space(
        tmp_path, completer, kits={"milo": kit}, max_persona_turns=1
    )
    space.post_notice("vera", make_notice())
    texts = [text for _space_id, text in transport.posted]
    assert len(texts) == 2  # milo's response (turn 1), then the stall — quill was capped out
    response = parse_envelope(texts[0])
    assert response is not None and response.kind == "response"
    assert "unresolved handoff #rtw-402" in texts[1]


def test_post_notice_validates_and_address_notice_points(tmp_path: Path) -> None:
    colleagues, transport, space = build_space(tmp_path, FakeStructuredCompleter([]))
    with pytest.raises(HandoffError):
        space.post_notice("milo", make_notice())  # origin is vera, not the posting handle
    plan = HandoffEnvelope(
        kind="plan",
        task_id="t1",
        origin="vera",
        summary="a plan",
        steps=(PlanStep(owner="", action="an action", status="unassigned"),),
    )
    with pytest.raises(HandoffError):
        space.post_notice("vera", plan)  # only notices post through this seam
    registry = colleagues.registry
    assert address_notice("who holds the payroll and cash?", registry) == "milo"
    assert address_notice("entirely mysterious weather", registry) is None


def test_ledger_tracks_two_tasks_independently() -> None:
    # The one composition the worked example never drives (final-audit gap): two distinct task_ids
    # in one ledger. The ledger keys per task_id — resolving one must not touch the other, and a
    # plan for one must carry ONLY its own asks (no cross-task bleed).
    ledger = TaskLedger()
    n1 = make_notice(task_id="rtw-402", asks=("@milo hold payroll for 402",))
    n2 = make_notice(
        task_id="rtw-503",
        summary="right-to-work failed for employee 503",
        asks=("@milo hold payroll for 503",),
    )
    ledger.feed(agent_msg(render_envelope(n1), "vera"))
    ledger.feed(agent_msg(render_envelope(n2), "vera"))
    assert {t.task_id for t in ledger.unresolved()} == {"rtw-402", "rtw-503"}

    # Resolve ONLY the first task; the second must stay open and untouched.
    r1 = HandoffEnvelope(
        kind="response",
        task_id="rtw-402",
        origin="milo",
        recipient="vera",
        summary="re: 402",
        decisions=(AskDecision(ask="@milo hold payroll for 402", decision="accept"),),
    )
    ledger.feed(agent_msg(render_envelope(r1), "milo"))
    assert {t.task_id for t in ledger.unresolved()} == {"rtw-503"}
    assert ledger.plan_worthy() == ["rtw-402"]
    plan = ledger.compose_plan("rtw-402")
    assert plan is not None and plan.task_id == "rtw-402"
    assert [s.action for s in plan.steps] == ["@milo hold payroll for 402"]  # no 503 bleed
    ledger.mark_planned("rtw-402")

    # Resolving the second yields its own independent plan, carrying only its own ask.
    r2 = HandoffEnvelope(
        kind="response",
        task_id="rtw-503",
        origin="milo",
        recipient="vera",
        summary="re: 503",
        decisions=(AskDecision(ask="@milo hold payroll for 503", decision="defer"),),
    )
    ledger.feed(agent_msg(render_envelope(r2), "milo"))
    assert ledger.unresolved() == []
    assert ledger.plan_worthy() == ["rtw-503"]
    plan2 = ledger.compose_plan("rtw-503")
    assert plan2 is not None
    assert [s.action for s in plan2.steps] == ["@milo hold payroll for 503"]
