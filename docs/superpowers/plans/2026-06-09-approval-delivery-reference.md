# Approval Delivery Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a transport-neutral `ApprovalRequest` artifact from `walk.gate{awaiting_apply}` frames and pure helpers to render it and apply it through `CockpitClient.apply(...)`.

**Architecture:** Add one focused module, `src/clonway_cockpit/approval_delivery.py`, separate from `approval.py` so policy predicates stay separate from delivery artifacts. Add one focused test module, `tests/test_approval_delivery.py`, that drives the API by behavior: gate extraction, fail-closed validation, text rendering, policy proposal preservation, and forwarding into a fake client. No transport adapters, queues, protocol changes, or default policy changes are included.

**Tech Stack:** Python 3.14, dataclasses, `collections.abc.Mapping` / `Callable`, pytest, existing `CockpitClient.apply(...)` contract.

---

## File Structure

- Create `src/clonway_cockpit/approval_delivery.py`
  - Owns `ApprovalRequestError`, `ApprovalRequest`, `render_approval_request(...)`, and `apply_approval_request(...)`.
- Create `tests/test_approval_delivery.py`
  - Owns all behavior tests for this artifact.

No existing production module should be modified for this workstream.

## Tasks

### Task 1: Extract Approval Requests From Gate Frames

**Files:**
- Create: `tests/test_approval_delivery.py`
- Create: `src/clonway_cockpit/approval_delivery.py`

- [ ] **Step 1: Write the failing extraction tests**

Create `tests/test_approval_delivery.py` with:

```python
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
```

- [ ] **Step 2: Run the extraction tests to verify RED**

Run:

```bash
uv run pytest tests/test_approval_delivery.py -q
```

Expected:

```text
FAILED tests/test_approval_delivery.py
ModuleNotFoundError: No module named 'clonway_cockpit.approval_delivery'
```

- [ ] **Step 3: Implement the minimal extraction module**

Create `src/clonway_cockpit/approval_delivery.py`:

```python
"""Transport-neutral approval request artifacts for guarded cockpit writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ApprovalRequestError(ValueError):
    """A gate frame could not be converted into an approval request."""


def _non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalRequestError(f"approval request requires non-empty {field}")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _meta_from_gate(gate: Mapping[str, object]) -> Mapping[str, object]:
    if gate.get("kind") == "walk.gate":
        meta = gate.get("meta")
        if not isinstance(meta, Mapping):
            raise ApprovalRequestError("walk.gate frame requires meta mapping")
        return meta
    if "kind" in gate:
        raise ApprovalRequestError("approval request requires a walk.gate frame")
    return gate


@dataclass(frozen=True)
class ApprovalRequest:
    token: str
    equivalent_cli: str
    proposal: Mapping[str, object]
    capability_key: str | None = None
    money_movement: bool | None = None
    worker: str | None = None
    intent: str | None = None
    title: str | None = None
    summary: str | None = None

    @classmethod
    def from_gate(cls, gate: Mapping[str, object]) -> "ApprovalRequest":
        meta = _meta_from_gate(gate)
        if meta.get("gate") != "awaiting_apply":
            raise ApprovalRequestError("approval request requires gate='awaiting_apply'")
        token = _non_empty_str(meta.get("token"), "token")
        equivalent_cli = _non_empty_str(meta.get("equivalent_cli"), "equivalent_cli")
        money = meta.get("money_movement")
        if money is not None and not isinstance(money, bool):
            raise ApprovalRequestError("money_movement must be a bool when present")
        proposal = dict(meta)
        proposal["token"] = token
        proposal["equivalent_cli"] = equivalent_cli
        return cls(
            token=token,
            equivalent_cli=equivalent_cli,
            proposal=proposal,
            capability_key=_optional_str(meta.get("capability_key")),
            money_movement=money,
            worker=_optional_str(meta.get("worker")),
            intent=_optional_str(meta.get("intent")),
            title=_optional_str(meta.get("title")),
            summary=_optional_str(meta.get("summary")),
        )
```

- [ ] **Step 4: Run the extraction tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_approval_delivery.py -q
```

Expected:

```text
9 passed
```

- [ ] **Step 5: Commit Task 1**

```bash
git add src/clonway_cockpit/approval_delivery.py tests/test_approval_delivery.py
git commit -m "feat(approval): extract approval requests from gates"
```

### Task 2: Render Requests And Preserve Policy Proposals

**Files:**
- Modify: `tests/test_approval_delivery.py`
- Modify: `src/clonway_cockpit/approval_delivery.py`

- [ ] **Step 1: Add failing rendering/proposal tests**

Append to `tests/test_approval_delivery.py`:

```python
from clonway_cockpit.approval_delivery import render_approval_request


def test_to_policy_proposal_returns_copy_with_token_guaranteed() -> None:
    req = ApprovalRequest.from_gate({"gate": "awaiting_apply", "token": "gate-1", "equivalent_cli": "x"})

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
    req = ApprovalRequest.from_gate({"gate": "awaiting_apply", "token": "gate-1", "equivalent_cli": "x"})

    text = render_approval_request(req)

    assert "Money movement: unknown" in text
    assert "Capability:" not in text
```

- [ ] **Step 2: Run rendering/proposal tests to verify RED**

Run:

```bash
uv run pytest tests/test_approval_delivery.py -q
```

Expected:

```text
ImportError: cannot import name 'render_approval_request'
```

or:

```text
AttributeError: 'ApprovalRequest' object has no attribute 'to_policy_proposal'
```

- [ ] **Step 3: Implement proposal copy and text renderer**

Update `src/clonway_cockpit/approval_delivery.py`:

```python
def _money_label(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"
```

Add this method inside `ApprovalRequest`:

```python
    def to_policy_proposal(self) -> dict[str, object]:
        proposal = dict(self.proposal)
        proposal["token"] = self.token
        proposal["equivalent_cli"] = self.equivalent_cli
        return proposal
```

Add this function below the class:

```python
def render_approval_request(request: ApprovalRequest) -> str:
    lines = [
        "Approval request",
        f"Action: {request.equivalent_cli}",
        f"Token: {request.token}",
        f"Money movement: {_money_label(request.money_movement)}",
    ]
    if request.capability_key is not None:
        lines.append(f"Capability: {request.capability_key}")
    if request.worker is not None:
        lines.append(f"Worker: {request.worker}")
    if request.intent is not None:
        lines.append(f"Intent: {request.intent}")
    if request.title is not None:
        lines.append(f"Title: {request.title}")
    if request.summary is not None:
        lines.append(f"Summary: {request.summary}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the approval-delivery tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_approval_delivery.py -q
```

Expected:

```text
12 passed
```

- [ ] **Step 5: Commit Task 2**

```bash
git add src/clonway_cockpit/approval_delivery.py tests/test_approval_delivery.py
git commit -m "feat(approval): render approval requests"
```

### Task 3: Apply Requests Through CockpitClient

**Files:**
- Modify: `tests/test_approval_delivery.py`
- Modify: `src/clonway_cockpit/approval_delivery.py`

- [ ] **Step 1: Add the failing apply-helper test**

Append to `tests/test_approval_delivery.py`:

```python
from clonway_cockpit.approval_delivery import apply_approval_request


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
```

- [ ] **Step 2: Run apply-helper test to verify RED**

Run:

```bash
uv run pytest tests/test_approval_delivery.py::test_apply_approval_request_forwards_token_policy_and_proposal -q
```

Expected:

```text
ImportError: cannot import name 'apply_approval_request'
```

- [ ] **Step 3: Implement the apply helper**

Update imports in `src/clonway_cockpit/approval_delivery.py`:

```python
from collections.abc import Callable, Mapping
```

Add below `render_approval_request(...)`:

```python
def apply_approval_request(
    client,  # noqa: ANN001
    request: ApprovalRequest,
    *,
    approve: Callable[[Mapping[str, object]], bool],
) -> Mapping[str, object]:
    return client.apply(
        request.token,
        approve=approve,
        proposal=request.to_policy_proposal(),
    )
```

- [ ] **Step 4: Run the approval-delivery tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_approval_delivery.py -q
```

Expected:

```text
13 passed
```

- [ ] **Step 5: Commit Task 3**

```bash
git add src/clonway_cockpit/approval_delivery.py tests/test_approval_delivery.py
git commit -m "feat(approval): apply approval requests"
```

### Task 4: Verification

**Files:**
- Test only: `tests/test_approval_delivery.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_approval_delivery.py tests/test_approval.py tests/test_cockpit_client.py -q
```

Expected:

```text
31 passed
```

If the exact count differs because upstream tests changed, all selected tests must pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected:

```text
614 passed
```

If the exact count differs because upstream tests changed, all tests must pass.

- [ ] **Step 3: Run lint/format/typecheck gate**

Run:

```bash
make check
```

Expected:

```text
ruff passes, format check passes, mypy passes, pytest passes
```

- [ ] **Step 4: Check working tree**

Run:

```bash
git status --short --branch
```

Expected:

```text
## Codex/approval-delivery-reference...origin/main [ahead 4]
```

## Self-Review

- Spec coverage: Task 1 covers request extraction and fail-closed validation; Task 2 covers text rendering and proposal preservation; Task 3 covers `CockpitClient.apply(...)` forwarding; Task 4 covers existing approval/client compatibility.
- Unfinished-marker scan: no incomplete implementation instructions remain.
- Type consistency: `ApprovalRequest`, `ApprovalRequestError`, `render_approval_request`, `to_policy_proposal`, and `apply_approval_request` names match across tasks.
- Scope check: no Chat, email, xops queue, storage, protocol, token generation, or default policy changes are included.
