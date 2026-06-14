# Changelog

All notable changes to clonway-cockpit. Workers pin release tags, not raw SHAs; see
docs/release-policy.md and docs/pin-sync.md.

The format is based on Keep a Changelog 1.1.0, and this project follows the
pre-1.0 rules documented in docs/release-policy.md.

Input renames on `reusable-ci.yml` are breaking changes for all callers.
Record them here and bump the release tag before merging.

## [Unreleased]

## [0.2.0] - 2026-06-14

### Added

- **`clonway_cockpit.testing`** — pytest plugin that snapshots/restores the
  capability registry around each test. The framework suite now uses it
  autouse, and worker suites can opt in with
  `pytest_plugins = ["clonway_cockpit.testing"]`.

- **`Gateway.validate()`** — no-network startup checks for configured roles,
  required env vars, LiteLLM availability, and pricing/model mismatches.

- `WizardContext` is generic over the worker client type, with
  `AnyWizardContext` as the Python 3.12-compatible alias for loose call sites.

- pdoc API reference build via `make docs`, plus a CI docs job that deploys to
  GitHub Pages on pushes to `main`.

- **`clonway_cockpit.config`** — pydantic-backed worker config loader with YAML
  file loading, double-underscore env overlay, aggregated provenance errors, and
  the `SecretEnvName` convention. Optional dependency extra:
  `clonway-cockpit[config]`.

- **`clonway_cockpit.gsheets`** — injected-service Google Sheets helper with A1
  utilities, record shaping, append/update/batch-format calls, and 429/5xx retry
  handling. Credential resolution stays worker-owned.

- **`clonway_cockpit.obs` is now a package** (`obs/`). All existing imports
  (`from clonway_cockpit.obs import make_obs`, `from clonway_cockpit import obs`)
  continue to work unchanged — `__init__.py` re-exports the full prior public
  surface. The implementation moves to `obs/_telemetry.py`.

- **`clonway_cockpit.obs.runlog`** — per-worker JSONL run log extracted from the
  three identical worker copies (`xbook/xhr/xletter`). Public API:
  `default_runs_dir(worker_id)`, `new_run_file(run_id, *, runs_dir)`,
  `append(run_file, **entry)`, `hash_request(body)`, `Runlog` dataclass,
  `make_runlog(worker_id, *, runs_dir=None)`. Wire format is byte-identical to
  the originals (compact JSON separators, auto-injected `ts`, `sha256:` hash
  prefix).

- **`clonway_cockpit.obs.logsetup`** — idempotent root-logger setup for worker
  entrypoints and servers (`setup_logging(worker_id, *, level, runtime_env,
  quiet)`). Replaces scattered per-worker `logging.basicConfig` calls; stdlib-
  only; UTC format; level from `<WORKER_ID>_LOG_LEVEL` env-var or explicit arg.

- **`clonway_cockpit.uk_calendar`** — England & Wales bank-holiday and
  business-day utilities extracted from `Auto-Bookkeeper`. Data covers
  2024–2028 (verified 2026-06-11). Public API: `is_bank_holiday(d)`,
  `is_business_day(d)`, `next_business_day(d)`, `previous_business_day(d)`,
  `business_days_between(a, b)`, `horizon_needs_refresh(today, *, lead)`,
  `DATA_HORIZON`, `BankHolidayHorizonError`. Querying beyond `DATA_HORIZON`
  raises `BankHolidayHorizonError`; CI fails when the table has < 12 months of
  runway (the annual refresh reminder).

- **`clonway_cockpit.google_auth`** — shared optional-extra Google credential
  seam for Clonway workers. It covers token stores, credential resolution,
  locked refresh, interactive OAuth, and service-account/DWD construction while
  keeping the core package importable without Google dependencies.

- **`clonway_cockpit.signals.factory.SignalFactory`** — sealed worker-bound
  Signal construction and emission, with identity checks before flushing.

- Public `dedup_key(...)` and `urgency_from_due_at(...)` helpers. The private
  `_dedup_key(...)` and `_urgency_from_due_at(...)` aliases remain for one
  release and emit `DeprecationWarning`.

- Observable unknown-title fallback for factory-built Signals, including
  warn-once logging, `unknown_title_kinds=N` emit logging, and
  `CLONWAY_SIGNALS_STRICT_KINDS=1` for worker CI.

- **Signal subscription API** (`clonway_cockpit.signals.subscribe`) — cursor-based
  polling over the dated archive (`signals/<worker>/<date>/<run_id>.jsonl`).
  Public surfaces:
  - `Subscription` — what a consumer wants (worker filter, kind filter,
    min-urgency filter) and who it is (namespaces the cursor).
  - `Delivery` — one delivered `Signal` with `emitted_by_run` and `object_path`
    provenance fields for audit and dedup.
  - `CursorStore` (Protocol) — per-`(consumer_id, worker)` high-water mark.
    The cursor is an opaque token recording the latest date reached plus the
    run_ids processed within it, so listing is robust to the non-monotonic
    trailing `run_id` (no same-day emission is skipped); legacy bare-object-name
    cursors still decode.
  - `FileCursorStore` — local-state-directory backed cursor store (atomic
    write via rename; suitable for persistent workers).
  - `GcsCursorStore` — GCS-backed cursor store with generation-match
    precondition for stateless Cloud Run consumers.
  - `poll(sub, *, cursor_store, ..., on_delivery=None)` — returns
    `list[Delivery]` since the last cursor; callback consumers commit after
    `on_delivery` returns; degrades to `[]` on creds/offline.
  - See `docs/signal-bus.md` for the full consumption contract, Phase-B
    push-trigger recipe, and new-worker wiring checklist.

- **Handoff failure callbacks** (`clonway_cockpit.negotiation`) — programmatic
  hook for cross-worker handoff failures, closing the C19 audit item:
  - `HandoffFailure` dataclass — `task_id`, `initiator`, `counterparty`,
    `reason` (closed set: `"declined" | "stalled" | "parse_failed" |
    `"reflex_refused"`), `summary`, `occurred_at`.
  - `NegotiatedSpace.on_handoff_failed` — optional `Callable[[HandoffFailure],
    None]`; fires at each of the four failure paths (stall sweep, bare
    decline, origin-mismatch parse failure, refused reflex). Default `None`
    preserves existing behaviour exactly.
  - `failure_to_signal` (`clonway_cockpit.signals.bridge`) — reference bridge
    callback: emits `kind="anomaly.detected"` with `source_id=task_id` (stable
    per-task dedup) so failures enter the fleet bus.

- **Worker-template** — `signals/subscribe.py.jinja` scaffold with a commented
  `poll_signals()` example; opt-in per worker, off by default.

- **`clonway_cockpit.audit_log`** — metadata-only framework audit ledger for capability
  launches, write gates, reflex decisions, and approval delivery, with local JSONL storage,
  best-effort GCS mirroring, readback helpers, render/model ledger projections, and worker-template
  wiring.

### Changed

- Gateway pricing config is stricter: non-mapping pricing entries now raise
  `GatewayError` instead of being silently skipped.

- `clonway_cockpit.render` is now a permanent compatibility facade over split
  chrome, panel, and model implementation modules.

- Persona-platform delivery tables now use explicit delivery-rung columns, with
  tests for vocabulary and ladder order.

- **Worker template** now generates `src/<worker>/runlog.py` (a two-line shim
  over `obs.runlog.make_runlog`) and calls `setup_logging` from `main()` — new
  workers are born without hand-rolled logging setup or a local runlog copy.

- Calling `build_signals(...)` without `worker=` is deprecated. This release
  keeps the old `xbook` default with a `DeprecationWarning`; a future release
  will require the worker id explicitly.

- **`reusable-ci.yml`** — new public contract surface: a `workflow_call` reusable CI
  workflow for the fleet. Inputs: `lint-paths` (default `.`), `mypy-args` (default
  `src`), `pytest-args` (default `-q`), `prod-import-package` (default empty),
  `python-version` (default `3.12`), `runs-on` (default `ubuntu-latest`), and
  `uv-python-downloads` (default `automatic`; use `never` for workers that must
  use preinstalled Python). Jobs: `lint` (ruff + ruff-format + mypy), `test`
  (pytest), `prod-import` (conditional). Callers pin by release tag (`@v0.2.0`)
  or full SHA — never `@main`. See `docs/ci-adoption.md` for the per-worker
  adoption checklist.

- **`.pre-commit-config.yaml`** — fleet pre-commit baseline: trailing-whitespace,
  EOF fixer, check-added-large-files, check-merge-conflict, detect-private-key
  (pre-commit-hooks v6.0.0); ruff + ruff-format (ruff-pre-commit v0.15.17); mypy
  via `uv run` (uses the repo's own pinned mypy, not a hook venv). No pytest hook
  (fleet policy: full suite in CI only).

- **`worker-template/.pre-commit-config.yaml.jinja`** — stamps the pre-commit
  baseline into every new worker generated from the template.

- **`docs/ci-adoption.md`** — per-worker adoption checklist: divergence table for
  all 8 workers, caller shapes, gotchas, and mechanical steps.

- **`ci.yml`** — this repo's CI converted to a thin `workflow_call` caller
  (`uses: ./.github/workflows/reusable-ci.yml`). The `prod-import-package:
  clonway_cockpit` input enables the import-smoke job. The `concurrency` stanza
  and `gitleaks` job remain in the caller.

- **`worker-template/.github/workflows/ci.yml.jinja`** — rewritten as a thin caller
  (delegates to `reusable-ci.yml@{{ ci_rev }}`). Default worker inputs:
  `lint-paths: "src tests"`, `mypy-args: ""` (bare mypy, config-driven). Includes
  label guard (`run-ci`) and `merge_group` trigger matching the fleet's adopted shape.

### Fixed

- **Gateway telemetry now writes `model_usage.jsonl` atomically** (temp-sibling
  `os.replace`) instead of an in-place `open("a")` append. In-place appends to a
  GCSFuse-mounted file triggered 'stale file handle / generation mismatch' retry
  storms — the root cause of the 2026-06-11 xbook `xero sync` stall (~9 min blocked
  after the sync itself succeeded, exhausting the Cloud Run task timeout). The write
  is lock-guarded so the read-rewrite-rename keeps the atomicity the single-syscall
  append had under concurrent gateway calls.

## [0.1.0] - 2026-06-11

Retroactive baseline for the first tagged framework release. This section covers the
extraction history through the release-engineering implementation merge; at plan time,
`origin/main` had reached `8a53e3f`.

### Added

- Cockpit spine: extracted the shared walk machine, guarded `confirm_apply` write gate,
  capability registry, host threading, render primitives, adaptive page width, staged progress
  rendering, raw-mode hardening, live-log panel, navigation stack, and doctor UI affordances.
- Agent channel: added the agent-navigable cockpit contract, `ScreenModel` wire shape,
  headless `CockpitClient`, stdio serving path, template dogfood coverage, and contract checks
  that keep render/model projections in parity.
- Signals and telemetry: added the Signal model, app labels, emit helpers, horizon scanning,
  run telemetry, usage fan-in, and related worker-template signal tests.
- Worker template: added the generated-worker scaffold, local/job deploy shapes, born
  agent-navigable tests, generic home hooks, statutory hook consolidation, template smoke
  coverage, and Auto-Procurer/xsource planning docs.
- Approval and safety: added allowlist policies, autonomous write authorization boundaries,
  apply identity in awaiting-apply frames, approval delivery references, and conversation
  hardening around the money/write gate.
- Persona platform: added the model gateway, LiteLLM adapter, tool-use port, multimodal content
  parts, prompt-caching pass-through, persona identity, soul and constitution composition,
  shared/private/thread memory, group spaces, receptionist, colleague responder, chat transport,
  and public architecture/operator documentation.
- Cross-worker handoffs: added governed write support, negotiation spaces, per-space ledgers,
  plan composition, stall escalation, operator setup guidance, and delivery-truth docs.

### Changed

- Made agent navigability part of the repository contract in CLAUDE.md and README-adjacent docs,
  including the rule that page-framing `render_*` functions need matching `model_*` projections.
- Updated persona-platform docs repeatedly to match delivered behaviour and fleet adoption state.
- Added merge-queue CI triggering in the baseline history before the first release tag.

### Fixed

- Hardened the agent driver around broken pipes, EOF-preserving drains, quit handling, timeouts,
  dry-run authority, and AST-backed page detection.
- Fixed persona, approval, conversation, doctor, walk, render, and getting-started correctness
  gaps found during the pre-release rollout.
