# [Plan] Extract shared utilities: runlog, logging setup, UK bank holidays

**Status:** draft plan — not implemented
**Source:** fleet audit 2026-06-11, items C7, C11, C13
**Wave:** 1

## Why

The fleet's "three before factoring" rule has been satisfied for three small utilities that still live as per-worker copies. This repo already proved the extraction pattern twice — `src/clonway_cockpit/obs.py` (the run/stage telemetry emitter, extracted from four near-identical worker `obs.py` files) and `src/clonway_cockpit/signals/emit.py` (the Signal flush, extracted from four worker `emit.py` files) — both keep workers byte-identical on the wire while deleting the copies. This plan applies the same move to the remaining three.

**Runlog (C7).** Verified at each worker's 2026-06-11 `origin/main`: `src/xbook/runlog.py`, `src/xhr/runlog.py`, `src/xletter/runlog.py` are 30 lines each and identical except for one constant (`DEFAULT_RUNS_DIR = Path(".xbook/runs")` / `.xhr/runs` / `.xletter/runs` — the only diff hunk between any pair is that line). Public API in all three: `new_run_file(run_id, *, runs_dir=None) -> Path`, `append(run_file, **entry) -> None` (JSONL, auto `ts`), `hash_request(body) -> str` (canonical sha256, `"sha256:"`-prefixed). Note the audit's catalogue described these as "byte-identical ×3, ~100 LOC" — the verified reality is 30 LOC and identical-modulo-one-constant; the extraction case stands either way.

**Logging setup (C11).** Scattered `logging.basicConfig`/handler wiring re-done per entrypoint across at least five workers (verified call sites include `xbook/calendar_webhook/__main__.py`, `xbook/server/__main__.py`, `xhr/server/__main__.py`, `xletter/watchdog_runner.py`, `xletter/cli/entrypoints.py`, `xletter/intake/webhook_server.py`, `xops/web/app.py`, `xquill/cli.py`). Meanwhile `obs.py` here already emits structured `key=value` extras through a stdlib logger and mirrors to a Cloud Logging sink when `runtime_env=cloud_run` — but every worker hand-rolls the root-logger setup those lines flow through, with per-repo drift in format, level handling, and noisy-library silencing.

**UK bank holidays (C13).** `Auto-Bookkeeper/src/xbook/calendar/bank_holidays.py` (97 lines): hardcoded England & Wales gov.uk list 2024–2027, API `is_bank_holiday(d)` / `is_business_day(d)` / `next_business_day(d)`, with a documented manual-refresh obligation ("call sites should be refreshed annually"). The HR worker independently needs the same calendar for leave/statutory logic (its `config/holiday_policy.py` and records models reference bank holidays), and any worker that schedules around payment/working days will need it next. A date table that silently runs out in 2028 inside one repo is exactly the audit's "silent-stale data" failure mode (dragon D7) — centralise it once, with an expiry tripwire.

## Scope

**In:**
- `clonway_cockpit.obs` grows a runlog module (obs becomes a package; existing import surface preserved).
- `clonway_cockpit.obs.logsetup` — one `setup_logging()` for CLI entrypoints, servers, and scheduled jobs.
- `clonway_cockpit.uk_calendar` — bank-holiday/business-day utility with a data-horizon tripwire.
- Migration recipe per worker (delete the copy, import the shared module) — documented here, executed as per-worker PRs.

**Out:**
- Changing the runlog JSONL format or the obs wire contract (consumers exist; byte-identical is the bar).
- The Google-auth, config-loader, and Sheets extractions (companion plans `2026-06-fleet-audit-shared-google-auth.md`, `2026-06-fleet-audit-shared-config-sheets.md`).
- gov.uk API fetching at runtime (workers must work offline/credential-less; the table stays static data with a refresh discipline).

## Spec

### 1. `clonway_cockpit.obs` becomes a package (C7, C11)

```
src/clonway_cockpit/obs/__init__.py   # re-exports today's obs.py API verbatim
src/clonway_cockpit/obs/_telemetry.py # current obs.py content, moved
src/clonway_cockpit/obs/runlog.py     # new
src/clonway_cockpit/obs/logsetup.py   # new
```

`from clonway_cockpit import obs; obs.make_obs(...)` and every existing import keep working (`__init__` re-exports `make_obs`, `flush_buffer`, `resolve_run_id`, and the rest of the current public surface — enumerate from the module at build time). A test pins the re-export list.

**`obs/runlog.py`** — the three workers' API, with the worker-varying constant turned into a parameter:

```python
def default_runs_dir(worker_id: str) -> Path:        # Path(f".{worker_id}/runs")
def new_run_file(run_id: str, *, runs_dir: Path) -> Path
def append(run_file: Path, **entry: Any) -> None     # unchanged semantics
def hash_request(body: dict) -> str                  # unchanged semantics
def make_runlog(worker_id: str, *, runs_dir: Path | None = None) -> Runlog
```

`Runlog` is a tiny frozen dataclass binding `runs_dir` with the same three methods, so a worker's shim is two lines (`_runlog = make_runlog("xbook")` + re-export) and existing call signatures inside the worker keep working. Bytes on disk: identical to today (same JSONL separators, same `ts` default, same hash canonicalisation) — assert with a golden test that replays a fixture entry and compares output to a captured string from the current worker copies.

**`obs/logsetup.py`**:

```python
def setup_logging(
    worker_id: str,
    *,
    level: str | None = None,          # default: env <WORKER_ID>_LOG_LEVEL, else INFO
    runtime_env: str | None = None,    # "cloud_run" → plain stream handler, no colour,
                                       #   single-line records (Cloud Logging splits on \n)
    quiet: Sequence[str] = (),         # logger names forced to WARNING (noisy libs)
) -> None
```

Behaviour: idempotent (second call reconfigures, never duplicates handlers); format `%(asctime)s %(levelname)s %(name)s %(message)s` UTC; never touches loggers outside the root + `quiet` list; no third-party deps. It deliberately does *not* attempt JSON logging — `obs` events are the structured channel; this is the human/log-explorer channel.

### 2. `clonway_cockpit/uk_calendar.py` (C13)

- Data: England & Wales bank holidays as `frozenset[date]`, seeded from the bookkeeper's verified 2024–2027 table and extended through the latest year published on gov.uk at build time (record the retrieval date in a module comment).
- API (superset of the bookkeeper's, signature-compatible):

```python
def is_bank_holiday(d: Date) -> bool
def is_business_day(d: Date) -> bool          # Mon–Fri and not a bank holiday
def next_business_day(d: Date) -> Date        # idempotent
def previous_business_day(d: Date) -> Date
def business_days_between(a: Date, b: Date) -> int
DATA_HORIZON: Date                             # last 31 Dec covered
```

- **Horizon tripwire:** querying a date beyond `DATA_HORIZON` raises `BankHolidayHorizonError` (callers asking about dates the table cannot answer must not get a silent "not a holiday"). Plus `horizon_needs_refresh(today, *, lead: timedelta = 180 days) -> bool` so worker Doctor screens / `scan_horizon()` can raise an operator signal *before* the cliff — turning the "refresh annually" comment into an observable.
- Refresh discipline: a unit test fails when `DATA_HORIZON - <test-run date>` < 12 months **in this repo's CI** (the framework's own CI becomes the annual reminder; the fix is a data-only PR).

### 3. Worker migration recipe (executed per-repo, after a release tag)

Per worker (bookkeeper/HR/marketer for runlog; all for logsetup as touched): delete `src/<pkg>/runlog.py`, replace with a two-line shim or rewrite imports; swap entrypoint `basicConfig` blocks for `setup_logging(...)`; bookkeeper swaps `calendar/bank_holidays.py` for `uk_calendar` (keeping a deprecation shim one release). Each migration PR must include the golden byte-equivalence test run against the worker's previously-captured output.

## Implementation plan

### Phase 1 — obs package conversion (pure move)
- [ ] Move `src/clonway_cockpit/obs.py` → `obs/_telemetry.py`; create `obs/__init__.py` re-exporting the full current public surface.
- [ ] Test `tests/test_obs_package.py`: import-path compatibility (`from clonway_cockpit.obs import make_obs` and `from clonway_cockpit import obs`) + re-export list pinned.
- [ ] Full suite green with zero other edits (proves the move is behaviour-free).

### Phase 2 — runlog
- [ ] `obs/runlog.py` per Spec §1; golden tests: fixture entry → bytes equal to the captured output of the current worker copy (capture from `Auto-Bookkeeper/src/xbook/runlog.py` semantics: separators `(",", ":")`, `ts` injection, `default=str`).
- [ ] Property-ish test: `hash_request` stable under key reordering.

### Phase 3 — logsetup
- [ ] `obs/logsetup.py` per Spec §1; tests: idempotency (handler count after double call), env-level resolution, `quiet` list applied, cloud_run single-line format.

### Phase 4 — uk_calendar
- [ ] `uk_calendar.py` with data through the latest published year (verify against gov.uk at build time; cite retrieval date in a comment, not a URL-fetch at runtime).
- [ ] Tests: known fixtures (2026 Early May = 2026-05-04; Christmas substitution days), horizon error, `horizon_needs_refresh` boundaries, idempotent `next_business_day`, freshness tripwire (12-month rule).

### Phase 5 — docs + release
- [ ] Changelog `[Unreleased]` entries (three new public surfaces); short usage section in `docs/onboarding-a-worker.md`.
- [ ] `worker-template/`: generated worker uses `obs.runlog.make_runlog` and `setup_logging` instead of growing copies (template smoke green).
- [ ] Migration recipe appended to this doc or `docs/ci-adoption.md`-style checklist (per-worker rows; executed as separate worker-repo PRs after the next release tag).

## Acceptance criteria

- All existing imports of `clonway_cockpit.obs` work unchanged (suite green at Phase 1 with no test edits).
- Golden tests prove runlog byte-equivalence with the current worker copies' output for the same inputs.
- `setup_logging` double-call leaves exactly one root handler; cloud_run mode emits single-line records.
- `uk_calendar` raises on beyond-horizon queries; CI fails when the table has <12 months of runway; 2024–2027 dates match the bookkeeper's existing table exactly (no regressions for current users).
- `make check` green; changelog updated; worker-template generates shimless usage of all three.

## Risks & dependencies

- **Module→package conversion** is the riskiest mechanical step (hatchling packaging, mypy namespace handling): Phase 1 lands alone and proves itself before any new code. If packaging friction appears, fallback: keep `obs.py` and add sibling modules `obs_runlog.py` / `obs_logsetup.py` (less tidy, zero risk) — decide at build time, document the choice.
- **Worker copies may drift before migration:** re-diff the three `runlog.py` files at build time; if one has grown a feature since 2026-06-11, fold it in or scope it out explicitly.
- **Bank-holiday data correctness:** proclamation dates can change; the table must cite its retrieval date and the refresh test is the guard. Do not add network fetching.
- Depends on the release-engineering plan for the tag workers will pin when migrating (migrations are blocked until a tag exists; the framework-side work is not).
- Cross-repo: migration PRs touch three+ worker repos; they are out of this PR's scope and must verify the worker's own suite + any consumer of `.{worker}/runs` paths (the run dir constant must not change value during migration).

## Next-agent pickup

- Branch: `claude/shared-utils` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- Land Phase 1 as its own commit before writing any new module; if the package conversion fights the toolchain, take the documented fallback and update this doc in the same PR.
- Capture the golden runlog fixtures by running the *current* worker module semantics (the 30-line file is quoted in §Why's description — reproduce locally; do not import from a worker repo in this repo's tests).
- Do NOT: change any wire/disk byte format; add `google-*`, `requests`, or YAML deps for any of these modules (all three are stdlib-only); start worker migration PRs from this branch; mention internal project/account identifiers in code comments or docs (public repo).
- Done = acceptance criteria demonstrated, `make check` + `make template-smoke` green, changelog entry present.
