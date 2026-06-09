# Approval Delivery Reference Design

**Date:** 2026-06-09
**Repo:** `clonway-cockpit`
**Status:** approved design -> spec review

## Goal

Define a transport-neutral approval request artifact for `walk.gate{awaiting_apply}` so future
Chat, email, xops, or CLI surfaces can show the same safe approval object and feed the decision
back through `CockpitClient.apply(...)`.

## Context

The framework already has the safety mechanism:

- `serve_stdio(..., allow_apply=False)` defaults to dry-run and never posts.
- With guarded apply enabled, a write gate emits `walk.gate` metadata including
  `gate="awaiting_apply"`, `token`, `equivalent_cli`, `capability_key`, and `money_movement`.
- `CockpitClient.apply(token, approve=..., proposal=...)` sends `{"apply": true, "token": token}`
  only when the caller's policy returns `True`; any other decision declines.
- `approval.deny_all`, `approval.prompt_human`, and `approval.AllowlistPolicy` are policy seams,
  not delivery artifacts.

The missing part is the neutral "please approve this action" envelope. Without one, each future
surface would invent its own interpretation of a gate frame. That creates drift exactly where the
framework needs one contract: what the human is asked to approve, what proposal the policy sees,
and what token is echoed back to the worker.

## Design

Add a new module, `clonway_cockpit.approval_delivery`, with an immutable
`ApprovalRequest` and pure helpers. It should not import or mention Google Chat, Gmail, xops
storage, or a queue. It is a reference shape and conversion layer.

### `ApprovalRequest`

`ApprovalRequest` is the stable transport-neutral envelope. Required fields:

- `token: str`
- `equivalent_cli: str`
- `proposal: Mapping[str, object]`

Optional display/context fields derived from the proposal when present:

- `capability_key: str | None`
- `money_movement: bool | None`
- `worker: str | None`
- `intent: str | None`
- `title: str | None`
- `summary: str | None`

`proposal` preserves the original gate metadata so existing policies keep seeing the same
decision input. The request must always include `token` in the proposal passed to
`CockpitClient.apply(...)`.

### Gate Conversion

Provide one conversion entry point:

```python
ApprovalRequest.from_gate(gate: Mapping[str, object]) -> ApprovalRequest
```

It accepts either:

- a full frame with `{"kind": "walk.gate", "meta": {...}}`, or
- a gate `meta` mapping directly.

It fails closed with a typed `ApprovalRequestError` when:

- the frame is not a `walk.gate`;
- `gate != "awaiting_apply"`;
- `token` is missing or not a non-empty string;
- `equivalent_cli` is missing or not a non-empty string;
- `money_movement`, when present, is not a bool.

This keeps a malformed or stale frame from becoming an approvable object.

### Rendering

Provide a pure text renderer:

```python
render_approval_request(request: ApprovalRequest) -> str
```

It should include the action (`equivalent_cli`), token, capability key when present, and an explicit
money movement line:

- `yes` for `True`
- `no` for `False`
- `unknown` when absent

This is not the future Chat card. It is the reference content every transport can use as its source
of truth.

### Policy And Apply Helpers

Provide two small helpers:

```python
request.to_policy_proposal() -> Mapping[str, object]
apply_approval_request(client: CockpitClient, request: ApprovalRequest, *, approve) -> Mapping[str, object]
```

`to_policy_proposal()` returns a plain dict copy of the preserved proposal with `token` guaranteed.
`apply_approval_request(...)` calls:

```python
client.apply(request.token, approve=approve, proposal=request.to_policy_proposal())
```

It does not choose a policy and does not auto-approve. The caller still supplies
`approval.deny_all`, `approval.prompt_human`, `AllowlistPolicy`, or a future transport-specific
human decision function.

## Data Flow

1. A worker reaches a guarded write and emits `walk.gate{gate:"awaiting_apply", token, ...}`.
2. A driver calls `ApprovalRequest.from_gate(frame)` to build the neutral request.
3. A transport renders the request using its own UI, or uses `render_approval_request(...)` as the
   reference text.
4. The human or policy returns yes/no.
5. The driver calls `apply_approval_request(client, request, approve=policy)`.
6. `CockpitClient.apply(...)` performs the existing matched-token handshake with the worker.

## Error Handling

Malformed gates fail before rendering or applying. `ApprovalRequestError` should carry a concise
message suitable for logs/tests, not a raw frame dump. The default posture remains deny/dry-run:
when a request cannot be built, there is no approval object to show and no token to echo.

## Out Of Scope

- Google Chat cards or Workspace add-on delivery.
- Email approval links.
- xops approval queues or storage.
- Durable audit history.
- Any change to `serve_stdio`, the wire protocol, token generation, or `CockpitClient.apply`.
- Any default policy change. Nothing in this workstream authorizes a write by itself.

## Test Plan

- Request extraction from full `walk.gate` frames and from direct metadata.
- Malformed gates fail closed.
- `render_approval_request(...)` includes action, token, capability, and money movement.
- `to_policy_proposal()` preserves proposal metadata and guarantees `token`.
- `apply_approval_request(...)` forwards the request token and proposal to `CockpitClient.apply`.
- Existing approval and cockpit-client tests remain green.
