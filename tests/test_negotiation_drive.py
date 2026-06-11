"""Ledger + NegotiatedSpace drive tests — the worked example end-to-end, degraded, stall, cap."""

from __future__ import annotations

from clonway_cockpit.colleague import Colleague, ColleagueRegistry
from clonway_cockpit.gateway.types import GatewayError, Message
from clonway_cockpit.group_chat import ChatMessage
from clonway_cockpit.handoff import (
    AskDecision,
    ClaimedFact,
    HandoffEnvelope,
    render_envelope,
)
from clonway_cockpit.negotiation import (
    TaskLedger,
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
