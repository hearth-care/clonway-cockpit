"""Safe-direction reflex tests — bank, log slugging, policy fuzz, provenance, firing order."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from clonway_cockpit.handoff import ClaimedFact, HandoffEnvelope
from clonway_cockpit.private_memory import PersonaMemory
from clonway_cockpit.reflex import (
    ReflexBank,
    ReflexFiring,
    ReflexKit,
    ReflexLog,
    ReflexPolicy,
    ReflexRule,
    _slug_key,
    build_proposal,
    fire_reflexes,
)

HOLD_ASK = "@milo — hold June payroll for employee 402"
LETTER_ASK = "write to employee 402 requesting evidence"


def hold_matcher(env: HandoffEnvelope) -> str | None:
    for ask in env.asks:
        if "hold" in ask and "payroll" in ask:
            return ask
    return None


def make_rule(run=lambda proposal: True, key: str = "payroll.hold") -> ReflexRule:
    return ReflexRule(
        capability_key=key,
        description="hold a payroll run pending review",
        matcher=hold_matcher,
        run=run,
    )


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


def test_slug_key() -> None:
    # Capability keys are NOT slugs (Dragon D6) — note names must slugify them.
    assert _slug_key("payroll.hold") == "payroll-hold"
    assert _slug_key("Send PAUSE!") == "send-pause"
    assert _slug_key("...") == "key"  # degenerate input still yields a valid segment
    assert len(_slug_key("k" * 200)) <= 48


def test_bank_registration() -> None:
    bank = ReflexBank()
    bank.register(make_rule())
    assert bank.keys() == frozenset({"payroll.hold"})
    assert [r.capability_key for r in bank.rules()] == ["payroll.hold"]
    with pytest.raises(ValueError):
        bank.register(make_rule())  # duplicate key
    with pytest.raises(ValueError):
        ReflexRule(capability_key="  ", description="x", matcher=hold_matcher, run=lambda p: True)


def test_log_in_memory_and_persisted(tmp_path: Path) -> None:
    memory = PersonaMemory(tmp_path, "milo")
    log = ReflexLog(memory)
    assert not log.seen("rtw-402", "payroll.hold")
    log.mark("rtw-402", "payroll.hold")
    assert log.seen("rtw-402", "payroll.hold")
    # A FRESH log over the same memory still sees it — idempotency survives restart (S5).
    assert ReflexLog(memory).seen("rtw-402", "payroll.hold")
    # A memory-less log is in-memory only.
    bare = ReflexLog()
    bare.mark("t1", "k")
    assert bare.seen("t1", "k") and not ReflexLog().seen("t1", "k")


def make_kit(run=lambda proposal: True, memory=None, max_applies=None):
    bank = ReflexBank()
    bank.register(make_rule(run=run))
    log = ReflexLog(memory)
    policy = ReflexPolicy(bank.keys(), log, max_applies=max_applies)
    return ReflexKit(bank=bank, policy=policy, log=log)


def good_proposal(**over) -> dict:
    base = {
        "capability_key": "payroll.hold",
        "money_movement": False,
        "blocking": True,
        "task_id": "rtw-402",
        "ask": HOLD_ASK,
        "summary": "right-to-work failed for employee 402",
        "provenance": "xhr:rtw-checks/RTW-2026-0142",
        "origin": "vera",
    }
    base.update(over)
    return base


def test_policy_structural_fuzz() -> None:
    # S3: exact-identity checks, AllowlistPolicy-style — truthy/falsy lookalikes are REFUSED.
    kit = make_kit()
    assert kit.policy(good_proposal()) is True
    for money in (True, 1, "no", [], {}, None):
        assert kit.policy(good_proposal(money_movement=money)) is False
    for blocking in (False, 1, "yes", [], None):
        assert kit.policy(good_proposal(blocking=blocking)) is False
    assert kit.policy(good_proposal(capability_key="other.key")) is False
    for prov in ("", "   ", None, 5):
        assert kit.policy(good_proposal(provenance=prov)) is False  # S4
    for task in ("", "Not Safe", None, 7):
        assert kit.policy(good_proposal(task_id=task)) is False
    no_money_key = dict(good_proposal())
    del no_money_key["money_movement"]
    assert kit.policy(no_money_key) is True  # absent defaults to False, like AllowlistPolicy


def test_policy_idempotency_and_cap() -> None:
    kit = make_kit(max_applies=1)
    assert kit.policy(good_proposal()) is True
    kit.log.mark("rtw-402", "payroll.hold")
    assert kit.policy(good_proposal()) is False  # seen -> refuse (S5)
    assert kit.policy(good_proposal(task_id="rtw-403")) is True  # cap not yet consumed
    kit.policy.note_applied()
    assert kit.policy(good_proposal(task_id="rtw-404")) is False  # cap reached


def test_build_proposal_provenance_laundering() -> None:
    # Dragon D7: only a fact CLAIMED BY THE ORIGIN supplies provenance.
    rule = make_rule()
    laundered = make_notice(
        facts=(ClaimedFact(text="milo claims X", claimant="milo", provenance="xbook:somewhere"),),
    )
    assert build_proposal(laundered, rule, HOLD_ASK)["provenance"] == ""
    assert build_proposal(make_notice(), rule, HOLD_ASK)["provenance"] == (
        "xhr:rtw-checks/RTW-2026-0142"
    )
    direct = build_proposal(make_notice(), rule, HOLD_ASK)
    assert direct["money_movement"] is False and direct["blocking"] is True


def test_fire_reflexes_applies_and_marks(tmp_path: Path) -> None:
    runs: list[Mapping] = []

    def run(proposal):
        runs.append(proposal)
        return True

    kit = make_kit(run=run, memory=PersonaMemory(tmp_path, "milo"))
    firings = fire_reflexes(make_notice(), kit)
    assert [f.applied for f in firings] == [True]
    assert firings[0].ask == HOLD_ASK and firings[0].capability_key == "payroll.hold"
    assert len(runs) == 1
    # Second delivery of the same envelope: NO second run, but a REPORTED firing (Dragon D5).
    again = fire_reflexes(make_notice(), kit)
    assert len(runs) == 1
    assert [f.note for f in again] == ["previously applied"] and again[0].applied is True


def test_fire_reflexes_run_failure_is_honest_and_retryable() -> None:
    kit = make_kit(run=lambda proposal: (_ for _ in ()).throw(RuntimeError("boom")))
    firings = fire_reflexes(make_notice(), kit)
    assert firings[0].applied is False
    assert "RuntimeError" in firings[0].note
    assert not kit.log.seen("rtw-402", "payroll.hold")  # not marked -> a retry may try again


def test_fire_reflexes_refusal_is_a_non_event() -> None:
    kit = make_kit()
    no_provenance = make_notice(
        facts=(ClaimedFact(text="RTW check failed", claimant="vera", provenance=""),)
    )
    assert fire_reflexes(no_provenance, kit) == []  # falls through to the model-decision path


def test_fire_reflexes_one_firing_per_ask() -> None:
    bank = ReflexBank()
    bank.register(make_rule())
    bank.register(
        ReflexRule(
            capability_key="payroll.freeze",
            description="also matches hold asks",
            matcher=hold_matcher,
            run=lambda p: True,
        )
    )
    log = ReflexLog()
    kit = ReflexKit(bank=bank, policy=ReflexPolicy(bank.keys(), log), log=log)
    firings = fire_reflexes(make_notice(), kit)
    assert [f.capability_key for f in firings] == ["payroll.hold"]  # first registered wins


# Ensure ReflexFiring is exercised so the import is not stripped.
def test_reflex_firing_dataclass() -> None:
    f = ReflexFiring(ask="x", capability_key="k", applied=True, note="ok")
    assert f.applied is True
