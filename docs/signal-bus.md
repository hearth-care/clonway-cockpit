# Signal bus — consumption contract

This document covers the **consumer side** of the fleet signal bus. The emit
side (how workers write signals) is in `src/clonway_cockpit/signals/emit.py`
and its module docstring. This document assumes you have read
[`docs/onboarding-a-worker.md`](onboarding-a-worker.md) and understand the
Signal model.

---

## 1. Source of truth: the dated archive

Every non-empty emit run writes a dated archive object:

```
signals/<worker>/<YYYY-MM-DD>/<run_id>.jsonl
```

This is the **source of truth for consumers**. Each object is append-only with
a stable name; a cursor over object names is exact.

`signals/<worker>/latest.jsonl` is a human/dashboard snapshot that is
overwritten on every run (including empty runs that clear the open set). **Never
use `latest.jsonl` as the basis for cursor-based state.** The bus does not
deliver closure events (see §5 below).

---

## 2. The `poll()` API

```python
from clonway_cockpit.signals.subscribe import poll, Subscription, Delivery, FileCursorStore

sub = Subscription(
    consumer_id="xbook",          # namespaces your cursor — must be unique per consumer
    workers=("xbook", "xhr"),     # None = all emitters discovered from the bucket
    kinds=("action.required",),   # None = all kinds
    min_urgency="soon",           # None = all urgencies
)
cs = FileCursorStore("/path/to/state/.xbook")   # or GcsCursorStore for Cloud Run

def handle_delivery(d: Delivery) -> None:
    # Dedup before acting: (d.signal.dedup_key, d.signal.emitted_at)
    handle_signal(d.signal)

deliveries: list[Delivery] = poll(sub, cursor_store=cs, on_delivery=handle_delivery)
```

### `Delivery` fields

| Field | Type | Meaning |
|---|---|---|
| `signal` | `Signal` | The full Signal object (see `signals/model.py`) |
| `emitted_by_run` | `str` | The `run_id` of the archive object (provenance) |
| `object_path` | `gs://…` | Stable GCS path — useful for audit and dedup |

### Subscription filters

| Field | Type | Semantics |
|---|---|---|
| `workers` | `tuple[str,…] \| None` | Explicit worker allow-list; `None` = auto-discover |
| `kinds` | `tuple[str,…] \| None` | Exact kind match; `None` = all |
| `min_urgency` | `str \| None` | Urgency ladder: `info < soon < due < overdue` |

---

## 3. Cursor stores

### `FileCursorStore`

Persists to `<state_dir>/signal_cursors.json`. Suitable for workers with a
persistent local state directory (the `.<worker>/` pattern already used by
`private_memory` and `obs`).

```python
from clonway_cockpit.signals.subscribe import FileCursorStore
cs = FileCursorStore(state_dir)
```

### `GcsCursorStore`

Persists to `subscriptions/<consumer_id>/cursor.json` in the shared signals
bucket. Suitable for stateless Cloud Run consumers (no disk between runs).

```python
from clonway_cockpit.signals.subscribe import GcsCursorStore
cs = GcsCursorStore(consumer_id="xbook")
```

Uses a generation-match precondition on writes — see the **single-writer
assumption** in §6.

---

## 4. Delivery semantics

### At-least-once

`poll()` delivers at least once. The cursor advances **per-object** inside
`poll()`. For consumers that act during polling, pass `on_delivery=...`; the
callback is called for every matching `Delivery`, and the object cursor advances
only after those callbacks return. If a callback raises, or if
`cursor_store.save()` raises (disk full, GCS quota), that object is re-delivered
on the next call.

Calling `poll()` without `on_delivery` remains useful for read-only inspection
and compatibility with older callers; in that form, the cursor advances when
the list has been built. For write/action consumers, prefer the callback form so
a crash before processing does not lose a signal.

**You MUST dedup by `(signal.dedup_key, signal.emitted_at)`.** The
`dedup_key` is stable across cycles for the same logical signal instance
(same worker, title, capability_key, focus, source_id). `emitted_at` is set
at emit time and is the chronological anchor.

### In-object-name order per worker

Within a worker, deliveries arrive in archive object-name order. Archive
names are `signals/<worker>/<ISO-date>/<run_id>.jsonl` — lexicographic order
is chronological.

Across workers, order follows the iteration order of `sub.workers` (or
discovery order for `workers=None`).

### Fail-open

`poll()` returns `[]` and logs at DEBUG on creds/offline errors (`GoogleAuthError`,
`DefaultCredentialsError`, `Forbidden`). It never raises. Worker logic that
calls `poll()` is unaffected by GCS outages.

---

## 5. What the bus does NOT deliver

The archive contains only **raised** signals from non-empty emit runs. There is
no closure event when a signal disappears from `latest.jsonl`.

Consumers tracking open/closed state must either:
- Snapshot `latest.jsonl` directly (the orchestrator's briefing model today), or
- Use the orchestrator's lifecycle layer (Firestore-backed, separate repo).

This is a deliberate Phase-A decision — re-evaluate when the first production
consumer chain needs closure semantics (Phase-C item).

---

## 6. Don't-do list

| Don't | Why |
|---|---|
| Consume `latest.jsonl` for cursor-based state | It's overwritten every run, including empties — not an archive |
| Couple emitters to consumers | Emitters never know consumers exist (fail-open by design) |
| Use the same `consumer_id` from two replicas | They will double-process; the GCS precondition only narrows, not eliminates, the race |
| Emit `anomaly.detected` from consumer code | Use `failure_to_signal` (see §7) so failures enter the bus through a consistent bridge |

---

## 7. Phase-B push trigger (doorbell design)

For latency-sensitive consumers, bucket notifications can reduce polling lag:

```
OBJECT_FINALIZE (prefix signals/)
    → one Pub/Sub topic
    → per-consumer subscription (filtered to worker prefix)
    → consumer HTTP endpoint
```

The push payload is a **doorbell only**. On receiving it, call the same
`poll()` — correctness never depends on Pub/Sub delivery:

- A missed notification → healed by the next scheduled poll.
- A duplicate notification → absorbed by the cursor (already advanced).

Phase A (polling) and Phase B (push) are behaviourally identical from the
consumer's perspective. The infra provisioning (topic, subscriptions, IAM) is
operator work; nothing in this repo names topics, projects, or GCP resources
beyond the `emit._BUCKET` symbol reference.

---

## 8. Handoff failure bridge

When the negotiation layer fails to complete a cross-worker handoff, the
`failure_to_signal` bridge emits an `anomaly.detected` signal, putting the
failure on the bus:

```python
from clonway_cockpit.signals.bridge import failure_to_signal

space = NegotiatedSpace(
    ...
    on_handoff_failed=failure_to_signal(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        storage_client_factory=...,   # injected in tests, omit for production
    ),
)
```

The emitted signal carries `source_id=task_id` for stable per-task dedup and
`kind="anomaly.detected"` so any subscriber filtering on that kind picks it up.

---

## 9. New worker — wiring checklist

1. **Add subscription call** to your scheduled entry-point (off by default):
   ```python
   # In your worker's main loop or scheduled job:
   deliveries = poll(
       Subscription(consumer_id=WORKER_ID, kinds=("action.required",)),
       cursor_store=FileCursorStore(STATE_DIR),
       on_delivery=lambda d: handle_signal(d.signal),
   )
   ```
2. **Dedup** on `(d.signal.dedup_key, d.signal.emitted_at)` before acting.
3. **Never touch `latest.jsonl`** for cursor state.
4. **Wire `on_handoff_failed`** on your `NegotiatedSpace` if you use the
   negotiation layer — failures should enter the bus, not only the chat room.
