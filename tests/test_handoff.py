"""Envelope contract tests — validation, codec, parse rules, shape pin."""

from __future__ import annotations

import pytest
from clonway_cockpit.handoff import (
    HANDOFF_SCHEMA_VERSION,
    AskDecision,
    ClaimedFact,
    HandoffEnvelope,
    HandoffError,
    PlanStep,
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
                text="RTW check failed — employee 402 (M. Okafor)",
                claimant="vera",
                provenance="xhr:rtw-checks/RTW-2026-0142",
            ),
        ),
        asks=(
            "@milo — hold June payroll for employee 402",
            "write to employee 402 requesting evidence",
        ),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def make_response(**over) -> HandoffEnvelope:
    base = dict(
        kind="response",
        task_id="rtw-402",
        origin="milo",
        recipient="vera",
        summary="re: right-to-work failed for employee 402",
        decisions=(
            AskDecision(
                ask="@milo — hold June payroll for employee 402",
                decision="reflexed",
                capability="payroll.hold",
                applied=True,
            ),
            AskDecision(
                ask="write to employee 402 requesting evidence",
                decision="decline",
                redirect="quill",
            ),
        ),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def make_plan(**over) -> HandoffEnvelope:
    base = dict(
        kind="plan",
        task_id="rtw-402",
        origin="vera",
        summary="right-to-work failed for employee 402",
        steps=(
            PlanStep(owner="milo", action="hold June payroll for employee 402", status="done"),
            PlanStep(owner="", action="write to employee 402", status="unassigned"),
        ),
    )
    base.update(over)
    return HandoffEnvelope(**base)


def test_valid_envelopes_construct() -> None:
    assert make_notice().schema_version == HANDOFF_SCHEMA_VERSION
    assert make_response().kind == "response"
    assert make_plan().recipient == ""


def test_field_validation_rejects() -> None:
    with pytest.raises(HandoffError):
        make_notice(kind="offer")  # unknown kind
    with pytest.raises(HandoffError):
        make_notice(task_id="../etc")  # not a safe slug
    with pytest.raises(HandoffError):
        make_notice(task_id="t" * 65)  # over MAX_TASK_ID
    with pytest.raises(HandoffError):
        make_notice(origin="Vera")  # uppercase — not a slug
    with pytest.raises(HandoffError):
        make_notice(summary="two\nlines")
    with pytest.raises(HandoffError):
        make_notice(summary="")
    with pytest.raises(HandoffError):
        make_notice(schema_version=2)  # cannot compose an unparseable frame
    with pytest.raises(HandoffError):
        ClaimedFact(text="x", claimant="not a slug!", provenance="")
    with pytest.raises(HandoffError):
        ClaimedFact(text="a" * 501, claimant="vera")  # over MAX_LINE
    with pytest.raises(HandoffError):
        PlanStep(owner="milo", action="x", status="maybe")  # unknown status


def test_per_kind_shape_rules() -> None:
    with pytest.raises(HandoffError):
        make_notice(recipient="")  # notice requires a recipient
    with pytest.raises(HandoffError):
        make_notice(
            decisions=(AskDecision(ask="x", decision="accept"),)
        )  # notice carries no decisions
    with pytest.raises(HandoffError):
        make_response(decisions=())  # response needs >= 1 decision
    with pytest.raises(HandoffError):
        make_response(facts=(ClaimedFact(text="x", claimant="milo"),))  # response carries no facts
    with pytest.raises(HandoffError):
        make_plan(recipient="milo")  # plan is owner-facing — recipient must be ""
    with pytest.raises(HandoffError):
        make_plan(steps=())  # plan needs >= 1 step
    with pytest.raises(HandoffError):
        make_notice(asks=tuple(f"ask {i}" for i in range(17)))  # over MAX_ITEMS


def test_decision_field_coupling() -> None:
    # reflexed requires a capability; others forbid capability/applied.
    with pytest.raises(HandoffError):
        AskDecision(ask="x", decision="reflexed")  # missing capability
    with pytest.raises(HandoffError):
        AskDecision(ask="x", decision="accept", capability="payroll.hold")
    with pytest.raises(HandoffError):
        AskDecision(ask="x", decision="accept", applied=True)
    # redirect only travels with decline.
    with pytest.raises(HandoffError):
        AskDecision(ask="x", decision="accept", redirect="quill")
    with pytest.raises(HandoffError):
        AskDecision(ask="x", decision="decline", redirect="Not A Slug")
