# [Plan] Signal subscriptions (fleet bus) + handoff failure callbacks

**Status:** implemented on PR #95
**Source:** fleet audit 2026-06-11, items C15, C19
**Wave:** 3

## Why

**C15 — every worker emits; exactly one consumer polls.** The emit side is uniform and framework-owned: `src/clonway_cockpit/signals/emit.py` writes each worker's open set to `signals/<worker>/latest.jsonl` (overwritten every run, empty included) plus a dated append-only archive `signals/<worker>/<YYYY-MM-DD>/<run_id>.jsonl`, in the shared fleet bucket (`emit._BUCKET`). The consume side is a single reader in the orchestrator repo (`src/xops/bridge/signal_store.py` — `read_worker` / `read_all` over the same `latest.jsonl` objects), driven by its scheduled briefing. Verified consequences:

- **No worker ever reacts to another worker's signal.** The audit's §3 finding: the obvious business chains (procurement→books, enquiry→admission→billing, mail→routing→execution) "are all broken at the handoff" — each would start with one worker consuming a signal another worker emitted.
- **Latency is the orchestrator's schedule**, effectively up to a day; a signal emitted at 09:00 is acted on at the next briefing.
- Anyone wanting to consume today must copy the orchestrator's reader and invent their own cursor/dedup story — the next ×8 duplication in the making.

**C19 — a failed handoff notifies a human, never the initiating code.** The cross-worker negotiation layer is built and merged here (`handoff.py` envelope; `negotiation.py` task ledger). Verified at `dcda649`: when an ask ends in decline, redirect-limbo, or no response, the only escalation is prose — `negotiation.py:494` `stall_text(...)` posts ONE owner-directed message and `mark_stalled` (:484) prevents repeats. There is no programmatic hook: the worker that *initiated* the handoff cannot retry, compensate, pick an alternative counterparty, or emit a signal about the failure. As chains get wired (Wave 3's whole point), "the owner reads a chat message" cannot be the only failure path.

These two land together because the natural first consumer of a handoff-failure event is the bus: failure → `anomaly.detected` signal → subscribers (orchestrator briefing today, the initiating worker's retry logic tomorrow).

## Scope

**In:**
- A framework-owned **subscription read API** with durable cursors over the existing archive objects (works with zero new infrastructure — Phase A).
- A **push trigger** design: bucket notifications → Pub/Sub → per-worker subscription, as an optional latency upgrade with the same consumer-facing API (Phase B; design + adapter seam now, infra later).
- `on_handoff_failed` callback contract on the negotiation layer + a standard failure→Signal bridge.
- Consumer-side dedup/ordering rules as a documented contract.

**Out:**
- Changing the emit wire or paths (frozen; consumers exist).
- The orchestrator's briefing/triage logic and its Firestore lifecycle (its repo; it becomes the first *migrated* consumer, later).
- Worker-specific reactions (what a worker does with a consumed signal is per-worker Wave-3 work, e.g. the procurement→books chain).
- Autonomy/dispatch (the orchestrator's launcher layer; separate audit items).

## Spec

### 1. Consumption contract (`src/clonway_cockpit/signals/subscribe.py`)

```python
@dataclass(frozen=True)
class Subscription:
    consumer_id: str                      # e.g. "xbook"; namespaces the cursor
    workers: tuple[str, ...] | None = None    # None = all emitters
    kinds: tuple[str, ...] | None = None       # filter on Signal.kind
    min_urgency: str | None = None             # info<soon<due<overdue ladder

@dataclass(frozen=True)
class Delivery:
    signal: Signal
    emitted_by_run: str        # archive object's run_id
    object_path: str           # gs path of the archive object (for audit/debug)

def poll(sub: Subscription, *, cursor_store: CursorStore,
         bucket: str = emit._BUCKET,
         storage_client_factory: Callable[[], Any] | None = None,
         now: datetime | None = None) -> list[Delivery]
```

Semantics (the contract consumers code against, identical under Phase A polling and Phase B push):

- **Source of truth is the dated archive**, not `latest.jsonl`: archives are append-only with stable names (`signals/<worker>/<date>/<run_id>.jsonl`), so a cursor over object names is exact; `latest.jsonl` stays the human/dashboard snapshot. (Emit writes archives only for non-empty sets — already true, no change.)
- **At-least-once, in object-name order per worker.** Consumers MUST dedup by `(dedup_key, emitted_at)`; the helper provides `Delivery` ordering and never re-delivers behind the cursor, but crash-between-process-and-commit yields repeats — document loudly.
- **Cursor:** per `(consumer_id, worker)` high-water mark = last fully-processed archive object name. `CursorStore` protocol (`load/save`), two implementations: `FileCursorStore` (consumer-local state dir — workers already keep `.{worker}/` state) and `GcsCursorStore` (`subscriptions/<consumer_id>/cursor.json` in the same bucket, for stateless Cloud Run consumers). Commit cursor AFTER the consumer's callback returns (at-least-once).
- **Fail-open both directions:** emitters never know consumers exist; `poll` degrades to `[]` on creds/offline (same `_QUIET_ERROR_NAMES` idiom as `emit.py`), and a consumer exception leaves the cursor uncommitted — never half-advanced.
- Lazy google imports + injected fake client, exactly per `emit.py` (no new core dependency).

### 2. Phase B — push trigger (design now, build when latency matters)

- Bucket notification (OBJECT_FINALIZE, prefix `signals/`) → one Pub/Sub topic → one subscription per consumer with a filter on the object-name prefix.
- The push payload is only a **doorbell**: consumers receiving it call the *same* `poll()`; correctness never depends on Pub/Sub delivery (a missed notification is healed by the next poll; a duplicate is absorbed by the cursor). This keeps Phase A/B behaviourally identical and makes the infra reversible.
- Framework ships `handle_push_notification(envelope) -> Subscription`-shaped glue only as a documented recipe (the HTTP endpoint is per-worker server surface); no Pub/Sub client dependency lands in this repo. Infra provisioning (topic, subscriptions, IAM) is operator work recorded against the fleet config (`~/.config/clonway/fleet.json`, per-worker keys), not in this public repo.

### 3. `on_handoff_failed` (C19) — `negotiation.py`

```python
@dataclass(frozen=True)
class HandoffFailure:
    task_id: str
    initiator: str                  # persona/worker handle
    counterparty: str | None
    reason: str                     # closed set: "declined" | "stalled" |
                                    # "parse_failed" | "reflex_refused"
    summary: str                    # one line, PII-light (title-level, no bodies)
    occurred_at: datetime

# NegotiatedSpace gains:
on_handoff_failed: Callable[[HandoffFailure], None] | None = None
```

- Invocation points (all exist today as code paths that end in prose or silence): terminal decline of a blocking ask; `mark_stalled` (the once-only stall sweep — callback fires at the same moment the stall text posts); envelope parse failure on a reply attributed to an open task; reflex refusal of an otherwise-accepted ask.
- **Default unchanged:** callback `None` → exactly today's behaviour (stall prose to owner). Callback errors are swallowed-and-logged (the negotiation loop must never die to an observer).
- **Standard bridge** (the reference callback, shipped here): `failure_to_signal(factory: SignalFactory) -> Callable[[HandoffFailure], None]` — emits `kind="anomaly.detected"`, `title="Handoff failed"`, `detail=f"{reason}: {summary}"`, `source_id=task_id` (stable dedup per task), via the worker's sealed factory (depends on the signal-hardening plan). Failure thus enters the bus, reaching the briefing today and any subscriber tomorrow — closing the loop C15 opens.

### 4. First-chain proof (documented, executed cross-repo later)

The acceptance demo for the whole design is one wired chain in a sandbox: worker A emits `payment.required`-style signal → worker B's `poll()` with `kinds=("action.required",)` picks it up exactly once across restarts. The *production* first chain (procurement→books AP intake) is audit item S6/B-side work in those repos; this plan only proves the rail.

## Implementation plan

### Phase 1 — subscription read API
- [x] `signals/subscribe.py`: `Subscription`, `Delivery`, `CursorStore` protocol, `FileCursorStore`, `poll()` per Spec §1; fake-GCS client fixture mirroring `tests`' existing emit fakes.
- [x] Tests: ordering across multiple archive objects; filters (workers/kinds/urgency ladder); cursor commit-after-callback (consumer raises → re-delivery next poll); creds-less degrade to `[]`; at-least-once duplicate surfaced when cursor write is interposed-crashed.
- Files: `src/clonway_cockpit/signals/subscribe.py`, `tests/test_signals_subscribe.py`.

### Phase 2 — GcsCursorStore + contract doc
- [x] `GcsCursorStore` (read-modify-write with generation-match precondition to avoid two replicas clobbering; document the single-writer-per-consumer assumption).
- [x] `docs/signal-bus.md`: the consumption contract (§1 semantics verbatim), the Phase-B doorbell design (§2), the dedup obligations, and the don't-do list (never consume `latest.jsonl` for state; never couple emitters to consumers).
- Files: subscribe.py, docs, `tests/test_signals_subscribe_gcs.py`.

### Phase 3 — handoff failure callback
- [x] `HandoffFailure` + `on_handoff_failed` field + the four invocation points in `negotiation.py`; default-None behavioural-parity tests (existing negotiation suite untouched and green = parity proof); callback-error-swallowed test; one test per failure reason.
- [x] `failure_to_signal` bridge (guarded import of the factory; if the signal-hardening plan hasn't merged, take `worker_id`/`flag_env` directly and build via `build_signals` — adapt at build time).
- Files: `src/clonway_cockpit/negotiation.py`, `src/clonway_cockpit/signals/bridge.py`, tests.

### Phase 4 — template + changelog + chain demo
- [x] Worker-template: commented subscription example in the generated worker (off by default — consuming is opt-in per worker).
- [x] End-to-end test: emit (via existing `emit_signals` with fake GCS) → `poll` → `Delivery` round-trips the wire; restart-resume across a fresh `poll` with persisted cursor.
- [x] Changelog `[Unreleased]` (two new public surfaces); delivery-table row if the persona docs track this slice.

## HANDOFF NOTES

- Current phase: implementation complete; final verification/PR finish protocol in progress.
- Next concrete step: run `make check`, `pre-commit run --all-files`, rebase onto `origin/main`, push with `--force-with-lease`, mark ready, relabel to `agent:needs-qa`, and post DONE with real gate tails.
- Decisions taken: stayed on branch `claude/plan-signal-bus` per dispatcher override; ignored the older "Next-agent pickup" instruction to start `claude/signal-bus`. Signal-hardening sealed factory was not present in this branch/main shape, so `failure_to_signal` uses the planned fallback (`worker_id`/`flag_env` plus `emit_signals`).
- Deviation recorded: `poll()` keeps the list-return API from the spec and adds optional `on_delivery` for action consumers. The callback form is the documented at-least-once path: cursor commit happens only after the consumer callback returns; a callback exception leaves the object uncommitted for re-delivery.
- Known failing tests: none at this checkpoint. Latest targeted proof: `uv run pytest -q tests/test_signals_subscribe.py -k 'callback_commits or callback_exception'` -> `2 passed, 35 deselected`.

## Acceptance criteria

- A consumer using `poll()` + `FileCursorStore` processes a three-run emission history exactly once in order, resumes correctly after a simulated crash (with the documented duplicate on the crash boundary), and gets `[]` with no exception when credentials are absent.
- Filters demonstrably exclude non-matching workers/kinds/urgencies.
- With `on_handoff_failed=None`, the full existing negotiation test suite passes unmodified.
- Each of the four failure reasons fires the callback with the right `HandoffFailure`; a raising callback is logged and does not alter ledger state.
- The bridge emits an `anomaly.detected` Signal whose `source_id` equals the task id (stable dedup), verified against the wire.
- `docs/signal-bus.md` lets a fresh agent wire a consumer without reading this plan; `make check` green; changelog updated.

## Risks & dependencies

- **Archive-only consumption assumes non-empty-set archives suffice:** a signal that *closes* (disappears from `latest.jsonl`) never appears as a closure event in archives. Consumers tracking open/closed state still need `latest.jsonl` snapshots or the orchestrator's lifecycle layer. Document this hard: the bus delivers *raised* signals; closure semantics are explicitly Phase-C/out-of-scope (re-evaluate after the first real chain).
- **Cursor stores and concurrent consumers:** one consumer_id = one logical consumer; two replicas polling the same consumer_id will double-process. The GCS generation-precondition narrows but does not eliminate this; state the single-writer assumption in docs and enforce nothing (Cloud Run min-instances=1 jobs are the current reality — re-verify at build time).
- **Bucket listing costs:** `poll` lists `signals/<worker>/` prefixes; with dated subfolders the listing grows unboundedly. Mitigate: cursor includes the date, listing starts at the cursor's date prefix (`start_offset`); add a note to revisit archive retention (operator lifecycle rule on the bucket — out of repo).
- **Pub/Sub phase touches infra and IAM** — operator-side, per-worker entries in the fleet config; nothing in this public repo names topics/projects.
- Depends on: signal-hardening plan (sealed factory for the bridge — soft dependency with a specced fallback); release-engineering (tag for consumers to pin). The orchestrator migrating its reader onto `poll()` is desirable de-duplication but a separate PR in its repo.
- Wave 3 item: do not start before the Wave-1 extraction plans merge, or the bus will be built on the unsealed construction path it's meant to compose with.

## Next-agent pickup

- Branch: `claude/signal-bus` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- Order: Phase 1 → 2 → 3 → 4; one PR per Phase 1–2 (bus) and one for Phase 3–4 (callbacks) is acceptable if review size demands — they share this plan.
- Before starting: check whether the signal-hardening plan (`2026-06-fleet-audit-signal-hardening.md`) has merged and pick the specced bridge variant accordingly; re-read `negotiation.py` at current main — the four invocation points are line-anchored to `dcda649` and may have moved.
- Do NOT: change emit paths/wire or `latest.jsonl` semantics; add `google-cloud-pubsub` (or any google package) to dependencies; build the Pub/Sub infra from this repo; let the callback default change existing negotiation behaviour; name buckets/topics/projects in new docs beyond the existing `emit._BUCKET` symbol reference (public repo).
- Done = acceptance criteria demonstrated, `make check` green, `docs/signal-bus.md` complete, changelog updated.
