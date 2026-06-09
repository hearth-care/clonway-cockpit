from __future__ import annotations

import pytest

from clonway_cockpit.approval_delivery import ApprovalRequest, ApprovalRequestError


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
