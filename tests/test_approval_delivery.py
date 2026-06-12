from __future__ import annotations

import pytest

from clonway_cockpit.approval_delivery import (
    ApprovalRequest,
    ApprovalRequestError,
    apply_approval_request,
    render_approval_request,
)
from clonway_cockpit.audit_log import AuditEvent


def _gate_meta() -> dict[str, object]:
    return {
        "gate": "awaiting_apply",
        "token": "gate-1",
        "equivalent_cli": "xbook bills schedule",
        "capability_key": "schedule-bills",
        "money_movement": False,
        "worker": "xbook",
        "intent": "schedule bills",
        "title": "Schedule bills",
        "summary": "Posts planned payment dates.",
    }


def test_from_gate_accepts_full_walk_gate_frame() -> None:
    req = ApprovalRequest.from_gate({"kind": "walk.gate", "meta": _gate_meta()})

    assert req.token == "gate-1"
    assert req.equivalent_cli == "xbook bills schedule"
    assert req.capability_key == "schedule-bills"
    assert req.money_movement is False
    assert req.worker == "xbook"
    assert req.intent == "schedule bills"
    assert req.title == "Schedule bills"
    assert req.summary == "Posts planned payment dates."
    assert req.proposal["token"] == "gate-1"
    assert req.proposal["equivalent_cli"] == "xbook bills schedule"


def test_from_gate_accepts_gate_meta_directly() -> None:
    req = ApprovalRequest.from_gate(_gate_meta())

    assert req.token == "gate-1"
    assert req.equivalent_cli == "xbook bills schedule"


@pytest.mark.parametrize(
    ("gate", "message"),
    [
        ({"kind": "home", "meta": _gate_meta()}, "walk.gate"),
        ({**_gate_meta(), "gate": "declined"}, "awaiting_apply"),
        ({**_gate_meta(), "token": ""}, "token"),
        ({**_gate_meta(), "token": 7}, "token"),
        ({**_gate_meta(), "equivalent_cli": ""}, "equivalent_cli"),
        ({**_gate_meta(), "equivalent_cli": None}, "equivalent_cli"),
        ({**_gate_meta(), "money_movement": "no"}, "money_movement"),
    ],
)
def test_from_gate_fails_closed_for_malformed_gates(gate: dict[str, object], message: str) -> None:
    with pytest.raises(ApprovalRequestError, match=message):
        ApprovalRequest.from_gate(gate)


def test_to_policy_proposal_returns_copy_with_token_guaranteed() -> None:
    req = ApprovalRequest.from_gate(
        {"gate": "awaiting_apply", "token": "gate-1", "equivalent_cli": "x"}
    )

    proposal = req.to_policy_proposal()
    proposal["token"] = "mutated"

    assert proposal["token"] == "mutated"
    assert req.to_policy_proposal()["token"] == "gate-1"
    assert req.to_policy_proposal()["equivalent_cli"] == "x"


def test_render_approval_request_includes_reference_fields() -> None:
    req = ApprovalRequest.from_gate(_gate_meta())

    text = render_approval_request(req)

    assert "Action: xbook bills schedule" in text
    assert "Token: gate-1" in text
    assert "Capability: schedule-bills" in text
    assert "Money movement: no" in text
    assert "Worker: xbook" in text
    assert "Intent: schedule bills" in text
    assert "Title: Schedule bills" in text
    assert "Summary: Posts planned payment dates." in text


def test_render_approval_request_marks_unknown_money_movement() -> None:
    req = ApprovalRequest.from_gate(
        {"gate": "awaiting_apply", "token": "gate-1", "equivalent_cli": "x"}
    )

    text = render_approval_request(req)

    assert "Money movement: unknown" in text
    assert "Capability:" not in text


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def apply(self, token: str, *, approve, proposal):  # noqa: ANN001
        self.calls.append({"token": token, "approve": approve, "proposal": proposal})
        return {"kind": "walk.gate", "meta": {"status": "declined", "token": token}}


def test_apply_approval_request_forwards_token_policy_and_proposal() -> None:
    req = ApprovalRequest.from_gate(_gate_meta())
    client = _FakeClient()

    def approve(proposal):  # noqa: ANN001
        return proposal["capability_key"] == "schedule-bills"

    frame = apply_approval_request(client, req, approve=approve)

    assert frame["meta"]["status"] == "declined"
    assert client.calls == [
        {
            "token": "gate-1",
            "approve": approve,
            "proposal": req.to_policy_proposal(),
        }
    ]


def test_approval_delivery_audits_routed_and_resolved() -> None:
    events: list[AuditEvent] = []
    req = ApprovalRequest.from_gate(
        {"kind": "walk.gate", "meta": _gate_meta()},
        audit=events.append,
        worker="demo",
    )
    client = _FakeClient()

    apply_approval_request(client, req, approve=lambda proposal: False, audit=events.append)

    assert [(event.event, event.actor, event.outcome) for event in events] == [
        ("approval.routed", "policy", "routed"),
        ("approval.resolved", "policy", "declined"),
    ]
    assert {event.worker for event in events} == {"demo"}
    assert {event.capability_key for event in events} == {"schedule-bills"}
    assert {event.ref for event in events} == {"gate-1"}
    assert {event.equivalent_cli for event in events} == {"xbook bills schedule"}
