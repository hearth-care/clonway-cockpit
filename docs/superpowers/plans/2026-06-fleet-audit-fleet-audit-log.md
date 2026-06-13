# [Plan] Framework-level fleet audit log

**Status:** implemented on PR #96
**Source:** fleet audit 2026-06-11, item C14
**Wave:** 3

## Why

Every write in the fleet funnels through framework chokepoints — that is the architecture's central achievement — but the framework keeps **no record** of what passed through them. Verified at `dcda649`:

- `walk.confirm_apply` (`src/clonway_cockpit/walk.py:465`) is "the single write gate. … The ONLY place a walk may post." In agent mode it emits `walk.gate` / `applied` / `declined` **ScreenModel frames** described in-code as "the on-the-wire audit" — but those frames exist only when `ctx.on_screen` is set (agent channel) and persist only if the *driving* side records them. A human operator pressing the gate key in the TUI leaves no framework-level trace at all.
- `shell._open_capability` launches capabilities and threads `capability_key` / `capability_money_movement` into the context (`registry.py:53-58`) — launch events are not recorded anywhere.
- `reflex.py` (auto-approval policy) and `approval.py` / `approval_delivery.py` (approval routing) make or move authorisation decisions; each keeps at most its own idempotency state, not an operator-readable ledger.
- Individual workers maintain their own domain audit trails (append-only stores, signed approvals — per the audit's per-worker assessments), but they are eight different formats in eight different places. The audit's C14: an operator asking "what did the fleet *do* yesterday — what launched, what hit a gate, what was approved, by whom/what?" has no single place to look. As autonomy expands (the orchestrator's launcher, reflex auto-approvals, agent-driven walks with guarded apply), that question changes from nice-to-have to governance requirement.

The framework is the right layer precisely because the chokepoints already exist: instrumenting `confirm_apply`, the capability launcher, the reflex policy, and approval delivery covers every worker at once on their next pin bump, with zero per-worker work.

There is also settled precedent for the privacy posture: the model gateway's per-call telemetry is **"content-free (counts + metadata only)"** (`CLAUDE.md` §persona platform; `gateway/telemetry.py`). The audit log adopts the same rule — framework metadata, never domain content.

## Scope

**In:**
- An `AuditEvent` record + `AuditSink` contract in the framework.
- Instrumentation at the four chokepoints: capability launch, write gate, reflex decision, approval routing.
- A default sink: local JSONL (append-only, per-run files) + best-effort GCS mirror under `audit/<worker>/…` in the shared fleet bucket (same degrade idiom as `obs.py`).
- A read/render helper so any cockpit (and the orchestrator's fleet bridge) can show a ledger panel.
- PII-redaction as a structural property (field whitelist), not a filter.

**Out:**
- Worker domain audit trails (they remain; this is the cross-cutting layer above them).
- Tamper-evidence/signing (the orchestrator's HMAC-signed launcher ledger is audit item P9, its repo; this log is operational, not cryptographic — noted as a future hardening hook).
- The orchestrator's operator ledger *view* (its repo consumes the read helper; out of this PR).
- Retention/lifecycle on the GCS prefix (operator bucket policy).

## Spec

### 1. `AuditEvent` — `src/clonway_cockpit/audit_log.py`

```python
@dataclass(frozen=True)
class AuditEvent:
    ts: datetime                      # UTC, sealed by the sink at record time
    worker: str
    run_id: str | None                # resolve_run_id() — joins obs/run telemetry
    event: str                        # closed set, see below
    capability_key: str | None
    actor: str                        # "human" | "agent" | "reflex" | "policy"
    dry_run: bool
    money_movement: bool
    outcome: str | None               # per-event closed set, e.g. "applied"/"declined"
    equivalent_cli: str | None        # already operator-facing copy, never domain data
    focus: str | None
    ref: str | None                   # opaque correlation id (gate token id,
                                      # approval id, task id) — never content
```

`EVENTS = frozenset({"capability.launched", "gate.offered", "gate.applied", "gate.declined", "reflex.approved", "reflex.refused", "approval.routed", "approval.resolved"})`.

**PII rule (structural):** the dataclass has no free-text field except `equivalent_cli` (which is the capability's own CLI string — operator copy by construction, pinned in `CapabilitySpec`). There is no `detail`/`payload`/`kwargs` field, so domain content (names, amounts, message bodies) is *unrepresentable*, mirroring the gateway-telemetry posture. `to_wire()` / `from_wire()` like `Signal`'s, with a `schema` field (`"audit/1"`).

### 2. `AuditSink` + default implementation

```python
AuditSink = Callable[[AuditEvent], None]   # must never raise (sink wraps itself)

def make_audit_sink(worker_id: str, *,
                    base_dir: Path | None = None,      # default .{worker}/audit/
                    bucket: str = emit._BUCKET,
                    gcs: bool | None = None,           # default: same flag-gating
                                                       # discipline as signals emit
                    storage_client_factory=None,
                    now: Callable[[], datetime] | None = None) -> AuditSink
```

- **Local:** append JSONL to `<base_dir>/<YYYY-MM-DD>.jsonl` (date from event ts; compact separators; one line per event; mirrors the runlog format family).
- **GCS mirror:** buffered per process, flushed best-effort on interpreter exit *and* every N events (N=20) to `audit/<worker>/<YYYY-MM-DD>/<run_id>.jsonl` — same lazy-import, same `_QUIET_ERROR_NAMES` silent-degrade, same never-crash guarantee as `signals/emit.py` / `obs.py`. The local file is the source of truth; GCS is the fleet-visible mirror.
- Sink failures log at debug/exception and never propagate (audit must never break the work it observes — same posture as observability everywhere in this repo).

### 3. Wiring — `WizardContext` callback threaded by the shell

- `WizardContext` (`registry.py`) gains `audit: AuditSink | None = None` (default keeps every existing construction valid — same pattern as `on_screen`).
- `shell.Host` gains an optional `audit_sink` (worker supplies `make_audit_sink(worker_id)` at host construction; the orchestrator's driving side may supply its own when driving over stdio). `shell._open_capability` records `capability.launched` (actor from agent-mode flags: `dry_run` ctx → "agent", else "human") and threads the sink into the context it builds.
- `walk.confirm_apply` records `gate.offered` when it draws/announces the gate, then exactly one of `gate.applied` / `gate.declined` with `actor` = "human" (key press), "agent" (guarded-apply token), or "policy" (authorize_apply path), `ref` = the gate token id when present. The existing ScreenModel frames are unchanged — the log complements, never replaces, the wire frames.
- `reflex.py` records `reflex.approved` / `reflex.refused` with `ref` = its idempotency key.
- `approval_delivery.py` records `approval.routed` / `approval.resolved` with `ref` = the approval id.
- All four sites guard `if sink is not None` — workers that never wire a sink are byte-for-byte unaffected.

### 4. Read/render helper

```python
def read_events(base_dir: Path, *, since: Date | None = None) -> Iterator[AuditEvent]
def render_ledger(events: Sequence[AuditEvent]) -> RenderableType   # + model_ twin
```

`render_ledger`/`model_ledger` follow the repo's render/model parity contract (`tests/test_contract.py` discovers the pair) so the ledger is agent-readable for free. Columns: time · worker · event · capability · actor · outcome. The orchestrator's fleet bridge can later read the GCS mirror across workers with the same `from_wire` — its repo.

### 5. What this is not (documented in the module docstring)

Not tamper-evident (no signatures — P9 hooks in later by wrapping the sink); not a domain audit trail (workers keep theirs); not guaranteed-delivery (local file is authoritative; GCS is best-effort); not a metrics system (`obs` owns run telemetry — `run_id` joins the two).

## Implementation plan

### Phase 1 — record + sink
- [x] `src/clonway_cockpit/audit_log.py`: `AuditEvent` (+wire round-trip + schema pin test), `EVENTS`, `make_audit_sink` with fake-GCS tests (flush cadence, exit flush, silent degrade, local-append always-wins), never-raise wrapper test (sink whose file write fails → logged, caller unaffected).
- Files: `audit_log.py`, `tests/test_audit_log.py`.

### Phase 2 — chokepoint wiring
- [x] `registry.py` (+field), `shell.py` (`audit_sink` on Host, launched-event in `_open_capability`), `walk.py` (three gate events in `confirm_apply`, all paths: human key, agent dry-run decline, guarded-apply applied/declined), `reflex.py`, `approval_delivery.py`.
- [x] Tests: drive the stub host (`tests/conftest.py` `make_stub_host`) headlessly with a recording sink and assert the event sequence for: launch→gate→human-decline; agent dry-run (launch→gate.offered→gate.declined, actor=agent); guarded apply (…→gate.applied, ref=token id). Reflex/approval events via their existing test harnesses extended with a sink.
- [x] Behavioural-parity proof: full existing suite green with no sink wired anywhere (all-new tests are additive).

### Phase 3 — read/render
- [x] `read_events` + `render_ledger`/`model_ledger` (parity contract picks the pair up automatically — verify the discovery does); golden render test in the existing style.
- Files: `audit_log.py` or `render_panels`-adjacent placement consistent with the render-split plan if it has merged (check at build time), tests.

### Phase 4 — template, docs, changelog
- [x] Worker-template: host construction gains `audit_sink=make_audit_sink("{{ worker_id }}")` (on by default for local; GCS mirror behind the same env-flag discipline as signals).
- [x] `docs/audit-log.md`: contract, PII posture (with the structural-whitelist explanation), wiring recipe, what-this-is-not.
- [x] Changelog `[Unreleased]`; delivery-table row if applicable.

## Acceptance criteria

- Driving the stub host end-to-end produces the exact expected `AuditEvent` sequences for human, agent-dry-run, and guarded-apply paths (asserted on event/actor/outcome/ref).
- An `AuditEvent` cannot carry domain content: constructing one with unexpected fields fails (dataclass), and a code search shows no chokepoint passes anything beyond the whitelisted metadata (reviewed; plus a test asserting `to_wire()` keys equal the frozen schema set).
- With no sink configured, the full pre-existing test suite passes unmodified.
- Sink misbehaviour (disk full simulation, GCS exceptions) never propagates to the walk/shell caller (tests).
- A second process can `read_events` what the first wrote and `render_ledger` it; the model twin satisfies the parity contract.
- `make check` + `make template-smoke` green; changelog updated; `docs/audit-log.md` complete.

## Risks & dependencies

- **Chokepoint line-anchors will drift:** `walk.py:465`, `registry.py:53-58` etc. are `dcda649` positions; re-locate at build time. If the framework-quality plan's render split or the signal-hardening factory merged first, place render helpers / reuse `resolve_run_id` accordingly (both are soft dependencies; neither blocks).
- **Double-instrumentation risk at the gate:** `confirm_apply` already emits agent-channel frames; the driving side (orchestrator) may *also* log. The `ref`/token-id correlation makes that a join, not a conflict — document it so nobody "deduplicates" by removing the framework record.
- **Performance/noise:** events are O(operator actions), not O(data) — no buffering concern locally; the GCS flush cadence (20) is a guess to re-examine against the longest real walk.
- **Privacy review is the merge gate:** the structural whitelist is the defence, but `equivalent_cli` strings in *workers* could theoretically embed domain values (e.g. an id baked into a CLI string at spec-registration time). Survey worker `CapabilitySpec.equivalent_cli` values at build time; if any embed per-record data, the field gets the same closed treatment (`capability_key` only) — decide with evidence, record in the doc.
- Cross-repo: the orchestrator's cross-worker ledger view and any P9 signing wrapper are follow-ups in its repo; worker pin bumps deliver the instrumentation (release-engineering plan provides the tags).
- Wave 3: schedule after the Wave-1 plans; the sink reuses their conventions (obs package layout from the shared-utils plan if merged — check `obs.py` vs `obs/` at build time).

## Next-agent pickup

- Branch: `claude/fleet-audit-log` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- Phases 1→4 in order, TDD; one PR, phase-per-commit. Start by re-locating the four chokepoints at current main and pasting the updated anchors into the PR description.
- Run the worker `equivalent_cli` survey (grep `equivalent_cli=` across the eight worker repos) before freezing the field whitelist — the privacy decision in Risks must be made on evidence.
- Do NOT: add any free-text/payload field to `AuditEvent` (the structural whitelist IS the feature); let a sink exception reach a caller; change the existing gate ScreenModel frames; build the orchestrator's ledger view from this branch; name projects/accounts/people in fixtures or docs (public repo — fixtures use placeholder worker ids).
- Done = acceptance criteria demonstrated, `make check` + `make template-smoke` green, privacy survey recorded in the PR, changelog updated.

## HANDOFF NOTES

- Current phase: finish protocol after verified takeover gates.
- Completed: Phase 1 added `clonway_cockpit.audit_log` with schema-pinned `AuditEvent`, local JSONL sink, best-effort GCS mirror, `read_events`, and focused tests. Phase 2 added `WizardContext.audit`, `Host.audit_sink`, launch/gate/reflex/approval audit events, and additive coverage. Phase 3 added `render_ledger`/`model_ledger`, `since` readback coverage, and contract parity discovery. Phase 4 wired the worker template, added `docs/audit-log.md`, updated the persona-platform delivery table plus README scaffold copy, and added the `[Unreleased]` changelog entry.
- Verification so far: baseline `make test` before edits reported `758 passed in 20.02s`; Phase 1 `uv run pytest -q tests/test_audit_log.py` reported `5 passed in 0.02s`; Phase 2 affected set `uv run pytest -q tests/test_audit_log.py tests/test_shell.py tests/test_walk.py tests/test_reflex.py tests/test_approval_delivery.py tests/test_agent_dry_run.py` reported `155 passed in 0.27s`; Phase 3 `uv run pytest -q tests/test_audit_log.py tests/test_contract.py tests/test_contract_module.py` reported `19 passed in 0.06s`; Phase 4 `uv run pytest -q tests/test_worker_template.py` reported `13 passed in 17.91s`; post-rebase `make check` reported ruff `All checks passed!`, ruff format `151 files already formatted`, mypy `Success: no issues found in 63 source files`, and pytest `973 passed in 25.81s`; post-rebase `make template-smoke` reported generated pytest `15 passed, 1 xfailed in 0.18s`, ruff `All checks passed!`, ruff format `18 files already formatted`, mypy `Success: no issues found in 12 source files`, CLI signals off/on passed, and `template-smoke PASSED for xsmoke (job)`; `pre-commit run --all-files` reported all hooks passed; takeover verification `make test` reported `973 passed in 29.33s`; focused takeover check `uv run pytest -q tests/test_audit_log.py tests/test_worker_template.py tests/test_contract.py` reported `35 passed in 23.88s`; final `make check` reported ruff `All checks passed!`, ruff format `151 files already formatted`, mypy `Success: no issues found in 63 source files`, and pytest `973 passed in 26.46s`; final `make template-smoke` reported generated pytest `15 passed, 1 xfailed in 0.20s`, ruff `All checks passed!`, ruff format `18 files already formatted`, mypy `Success: no issues found in 12 source files`, CLI signals off/on passed, and `template-smoke PASSED for xsmoke (job)`; final `pre-commit run --all-files` reported all hooks passed.
- Decisions: GCS audit mirroring is gated by `<WORKER>_AUDIT_GCS` or `CLONWAY_AUDIT_GCS` when `gcs=None`; local JSONL remains authoritative.
- Deviations: none known. `CHANGELOG.md` exists and now includes the framework audit log under `[Unreleased]`.
- Privacy survey: searched `equivalent_cli=` across local Auto-Admissions, Auto-Bookkeeper, Auto-HR, Auto-Inspector, Auto-Orchestrator, Auto-Procurer, and Auto-Secretary checkouts. Values are static operator commands or command templates; noted dynamic examples are command-shaped (`payroll-clear --group {group}`, `open {worker_link(worker)}`), not arbitrary domain payload fields. `docs/audit-log.md` documents that record-specific names, amounts, message bodies, and document text must not be placed in `equivalent_cli`.
- Known failing tests: none at this checkpoint.
- QA finding fix (fixer-claude-20260613T004338Z-4067): `_LocalJsonlAuditSink.__call__` now calls `resolve_run_id(event.run_id)` once and writes the resolved value into the wire dict before `_append_local` and `_remember_for_gcs`. `_remember_for_gcs` reads `wire["run_id"]` directly — no second resolution, no random uuid fallback. Local JSONL rows and GCS mirror keys now share the same resolved run_id, joining to obs telemetry correctly.  Added two new regression tests: `test_sink_resolves_run_id_from_env_for_local_and_gcs` and `test_sink_multiple_none_run_id_events_share_gcs_key`. Full suite: `975 passed in 28.47s`.
- Next concrete step: push the verified branch with lease, mark the PR ready, move labels from `agent:claimed` to `agent:needs-qa`, post the DONE comment, then remove the temporary worktree.
- CI-FAIL round (fixer-claude-20260613T011621Z-4067, 2026-06-13): the dispatcher's "CI FAIL ... Gitleaks PR diff, docs" was a concurrency-cancellation false alarm. Run `27452172822` was cancelled mid-flight by `concurrency: cancel-in-progress` (superseded by `27452175394` when the FIX-CLAIM label add fired a second `pull_request` event); its cancelled docs+gitleaks jobs read as failures. The actual latest run `27452175394` is **success** on both. Reproduced locally on HEAD `7bc037d`: gitleaks v8.21.2 `origin/main..HEAD` -> `no leaks found`; `make docs` -> exit 0 (`build/docs/clonway_cockpit/audit_log.html` generated; warnings are pre-existing pdoc forward-ref noise, not errors); `uv run pytest -q` -> `975 passed`; `uv run pre-commit run --all-files` -> all hooks passed. Branch is up to date with `origin/main` (no rebase needed). No code change required this round.
- CONFLICT/rebase round (fixer-claude-20260613T053305Z-38021, 2026-06-13): siblings (signal-bus PR #95, safe-command-matrix PR #103, acceptance-checklist PR #102) merged ahead; rebased `claude/plan-fleet-audit-log` onto `origin/main` (`a4560fa`). Single manual conflict, in `CHANGELOG.md` `[Unreleased] > Added` only — both sides appended new bullets; resolved by keeping both (main's Signal-subscription / Handoff-callback / worker-template-signals entries plus our `clonway_cockpit.audit_log` entry). No code conflicts; the run_id sink fix and its two regression tests are intact post-rebase (`audit_log.py:137` `wire["run_id"] = resolve_run_id(...)`; `audit_log.py:151` `rid = wire["run_id"]`). Full gates re-run green: `uv run pytest -q` -> `1046 passed in 28.76s` (975 + signal-bus's new tests merged cleanly); `make check` -> ruff/format/mypy pass, pytest `1046 passed`; `make template-smoke` -> generated pytest `15 passed, 1 xfailed`, ruff/format/mypy pass, CLI signals off/on passed, `template-smoke PASSED for xsmoke`; `make docs` -> exit 0 (`audit_log.html` generated); `uv run pre-commit run --all-files` -> all hooks passed. gitleaks not installed locally (CI runs it on push); manual secret-pattern scan of `origin/main..HEAD` clean. Because the rebase needed manual resolution, routing to normal re-QA (`agent:needs-qa`), not the clean-rebase shortcut. No operator-facing step changed — existing runbook delta on auto-orchestrator#196 stands.
