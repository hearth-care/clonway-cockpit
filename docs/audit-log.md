# Framework Audit Log

`clonway_cockpit.audit_log` records framework-level operator activity at the shared
chokepoints every worker inherits:

- capability launches through `shell.open_capability`
- write gates through `walk.confirm_apply`
- reflex policy decisions through `reflex.fire_reflexes`
- guarded approval routing/resolution through `approval_delivery`

This is an operational fleet ledger, not a worker domain audit trail. Workers keep their own
domain records for names, amounts, documents, messages, and business state.

## Privacy Posture

The event schema is a structural whitelist. `AuditEvent` has no `detail`, `payload`, `body`, or
arbitrary metadata field, so domain content is not representable.

Allowed fields are:

- `ts`, `worker`, `run_id`
- `event`
- `capability_key`
- `actor`
- `dry_run`
- `money_movement`
- `outcome`
- `equivalent_cli`
- `focus`
- `ref`

`equivalent_cli` is allowed because it is already operator-facing capability copy. Do not put
record-specific names, amounts, message bodies, or document text into a capability's
`equivalent_cli`; use stable command templates and capability keys.

## Wire Contract

`AuditEvent.to_wire()` emits compact JSON-compatible records with `schema: "audit/1"`.

Events are:

- `capability.launched`
- `gate.offered`
- `gate.applied`
- `gate.declined`
- `reflex.approved`
- `reflex.refused`
- `approval.routed`
- `approval.resolved`

Actors are `human`, `agent`, `reflex`, or `policy`.

## Sink Behaviour

Workers wire the framework sink at host construction:

```python
from clonway_cockpit.audit_log import make_audit_sink

host = shell.Host(
    ...,
    audit_sink=make_audit_sink("xworker"),
    audit_worker="xworker",
)
```

Local JSONL is authoritative and appends to `.<worker>/audit/YYYY-MM-DD.jsonl` by default.
GCS mirroring is best-effort and never allowed to break cockpit work. It is enabled by either:

- `<WORKER>_AUDIT_GCS=1`
- `CLONWAY_AUDIT_GCS=1`

The mirror path is `audit/<worker>/<YYYY-MM-DD>/<run_id>.jsonl` in the shared fleet bucket.

## Reading And Rendering

Use `read_events(base_dir, since=...)` for local JSONL readback, and render the ledger with:

```python
from clonway_cockpit import render
from clonway_cockpit.audit_log import read_events

events = list(read_events(Path(".xworker/audit")))
renderable = render.render_ledger(events)
model = render.model_ledger(events)
```

`render_ledger` has a `model_ledger` twin, so the same ledger is agent-readable through the
framework ScreenModel contract.

## What This Is Not

- Not tamper-evident. A future signing wrapper can wrap `AuditSink`.
- Not guaranteed delivery. Local JSONL is the source of truth; GCS is a mirror.
- Not a metrics system. `obs` owns run telemetry; `run_id` joins audit records to it.
- Not a domain audit trail. Workers still own their own business records.
