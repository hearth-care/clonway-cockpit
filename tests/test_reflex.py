"""Safe-direction reflex tests — bank, log slugging, policy fuzz, provenance, firing order."""

from __future__ import annotations

from pathlib import Path

import pytest
from clonway_cockpit.reflex import (
    ReflexBank,
    ReflexLog,
    ReflexRule,
    _slug_key,
)

from clonway_cockpit.handoff import ClaimedFact, HandoffEnvelope
from clonway_cockpit.private_memory import PersonaMemory

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
