# [Plan] Shared config loader + Sheets helpers

**Status:** implementation in progress on PR #92
**Source:** fleet audit 2026-06-11, items C9, C10
**Wave:** 1

## Why

**Config loading (C9).** Five workers hand-roll the same load-YAML → validate → overlay-env pipeline. Verified at 2026-06-11 worker `origin/main`s: the bookkeeper's `src/xbook/config.py` (228 lines), the orchestrator's `src/xops/config.py` (64), the secretary's `xquill/config.py`, the HR worker's `src/xhr/config/` package (multiple loader modules besides its domain policy files), and `yaml.safe_load` call sites spread through the inspector (`src/xcqc/readiness/config.py`, `src/xcqc/cadence/catalog.py`, `src/xcqc/readiness/homes.py`, …). The audit sized the duplicated loader logic at ~500 LOC combined. Every copy answers the same questions slightly differently — where the file lives, which env var overrides which key, what happens on a missing/invalid field, whether unknown keys are rejected — so config bugs are per-worker surprises rather than framework behaviour. Two new workers (admissions, procurement) are pre-live and about to write copy number six and seven.

The framework already has a validated-config precedent: `src/clonway_cockpit/gateway/config.py` (`GatewayConfig.from_dict` — plain-dict validation, "API keys are referenced by the NAME of an env var, never stored here"). That convention (secrets by env-name, storage format is the caller's choice) is the right one and this plan generalises it.

**Sheets helpers (C10).** Verified: `xbook/workspace/sheets.py` (107 lines — `extract_sheet_id`, `_build_service`, `list_tabs`, `read_values`) and `xhr/integrations/sheets.py` (124 lines — `GoogleSheetClient.get_all_records` / `append_row` / `update_row`, `_col_letter`, credential bootstrap) are two independent wrappers over the same Sheets v4 surface; the audit's duplication table also attributes a third copy to the marketer worker (re-verify at build time — see Risks). Each clone re-solves A1-notation, column-letter arithmetic, service construction, and (nowhere consistently) rate-limit retry. Sheets are load-bearing across the fleet (registers, trackers, occupancy sheets), and the audit's post-incident history in the bookkeeper (sheet-layout drift breaking a script) argues for one hardened helper rather than three soft ones.

## Scope

**In:**
- `clonway_cockpit.config` — pydantic-validated loader with env overlay, aggregated errors, and the env-name-for-secrets convention.
- `clonway_cockpit.gsheets` — typed thin wrappers over Sheets v4: batch read, append, update, A1/column utilities, 429/5xx retry with backoff; injected service for tests.
- Optional dependency extras: `clonway-cockpit[config]` (pydantic, pyyaml) and reuse of the `[google]` extra from the google-auth plan (google-api-python-client).
- Migration recipe per worker (executed as per-worker PRs).

**Out:**
- Workers' *domain* config models and policy files (leave/cadence/templates etc. — they become `BaseModel`s passed *into* the loader, not framework code).
- Credential acquisition (companion plan `2026-06-fleet-audit-shared-google-auth.md`; `gsheets` accepts a built service or credentials object — it never resolves credentials itself).
- Sheets *write-gating* semantics (workers' plan→confirm→apply discipline stays at the worker/walk layer; `gsheets` is transport).
- Drive/Docs/Gmail helpers (separate surfaces; out until three copies exist — the factoring rule).

## Spec

### 1. `clonway_cockpit/config.py` (C9)

```python
class ConfigError(Exception):
    """All problems found in one pass — .problems: list[str], each
    'where: what' (file path, env var, or field locator)."""

def load_config(
    model: type[ModelT],                  # any pydantic BaseModel
    *,
    worker_id: str,                       # drives defaults below
    paths: Sequence[Path] | None = None,  # default: ($<WORKER>_CONFIG,
                                          #   ./<worker>.yaml, ~/.config/clonway/<worker>.yaml)
    env_prefix: str | None = None,        # default: WORKER_ID.upper()
    require_file: bool = False,           # False → all-defaults model is legal
) -> ModelT
```

Behaviour, in order:

1. **File layer:** first existing path wins (no merging across files). YAML via `yaml.safe_load`; must be a mapping. Missing file with `require_file=False` → `{}`.
2. **Env overlay:** for every env var `f"{env_prefix}__{KEY}"` (double underscore = nesting: `XBOOK__SYNC__WINDOW_DAYS` → `sync.window_days`), the string value is set into the mapping; pydantic does the type coercion. Single-underscore legacy names are NOT guessed (explicitness over magic; workers keep any legacy names in their own shim during migration).
3. **Validation:** `model.model_validate(merged, strict=False)` with `extra="forbid"` *recommended* on worker models (documented, not forced). A `ValidationError` is re-raised as `ConfigError` with **all** field problems listed, each prefixed by the value's provenance (`file <path>:` or `env <VAR>:`) — provenance tracking is the feature no worker copy has and the reason config errors currently take a debugging session.
4. **Secrets convention:** documented at the top of the module, mirroring `gateway/config.py`: config stores the *name* of an env var for anything secret; a `SecretEnvName = Annotated[str, ...]` alias is provided so models mark such fields, and `load_config` warns (not fails) when a named env var is unset — workers decide hard/soft at their boundary.

Pure function; no global state, no caching (workers cache if they want). `pydantic`/`yaml` imports are module-level **inside this module only** — the module is importable only with the `[config]` extra; the package `__init__` must not import it eagerly (prod-import CI job stays green without extras).

### 2. `clonway_cockpit/gsheets.py` (C10)

```python
def extract_sheet_id(value: str) -> str          # URL or bare id → id (port of xbook's)
def col_letter(n: int) -> str                    # 1 → "A", 27 → "AA" (port of xhr's)
def a1(tab: str, *, row: int | None = None, col: int | None = None, ...) -> str

class SheetsClient:
    def __init__(self, service: Any, spreadsheet_id: str): ...
    def list_tabs(self) -> list[str]
    def batch_get(self, ranges: Sequence[str]) -> dict[str, list[list[str]]]
    def get_records(self, tab: str, *, header_row: int = 1) -> list[dict[str, str]]
    def append_rows(self, tab: str, rows: Sequence[Sequence[object]],
                    *, value_input: str = "RAW") -> None
    def update_range(self, range_: str, values: Sequence[Sequence[object]],
                     *, value_input: str = "RAW") -> None
    def batch_format(self, requests: Sequence[dict]) -> None   # raw batchUpdate passthrough
```

- **Retry:** every call retries on HTTP 429 and 5xx with exponential backoff + jitter (base 1s, factor 2, max 5 tries, then raise). Injectable `sleep` for tests. This is the one behaviour every copy lacks and every live worker has needed.
- **No credential logic:** the constructor takes a built `service` (from `googleapiclient.discovery.build`, e.g. via the google-auth plan's `build_service`). Tests use an in-memory fake recording requests.
- **Read shaping:** `get_records` returns header-keyed dicts with row-length normalisation (Sheets API truncates trailing empties — pad to header width; this exact pitfall is hand-handled in the HR copy today).
- Lazy import discipline: `googleapiclient` is only touched by callers who pass a real service; the module itself imports nothing google at import time.

### 3. Extras

```toml
[project.optional-dependencies]
config = ["pydantic>=2", "pyyaml>=6"]
# google extra defined by the shared-google-auth plan; gsheets needs nothing
# at import time and documents google-api-python-client as the runtime need.
```

## Implementation plan

### Phase 1 — config loader
- [x] `src/clonway_cockpit/config.py` per Spec §1; `[config]` extra in `pyproject.toml`.
- [x] Tests (`tests/test_config_loader.py`): file-only / env-only / both (env wins) / nested `__` keys / provenance strings in errors / aggregated multi-field `ConfigError` / missing-file with and without `require_file` / unset secret env warns / non-mapping YAML rejected.
- [x] Prod-import job still green without extras (no eager import from package `__init__`).

### Phase 2 — gsheets
- [x] `src/clonway_cockpit/gsheets.py` per Spec §2 with a `FakeSheetsService` test double in `tests/`.
- [x] Tests: A1/col-letter round-trips (1, 26, 27, 52, 703); `get_records` ragged-row padding; retry sequence on 429 (count + backoff schedule via injected sleep) and give-up raise; append/update payload shapes pinned against captured request dicts from the existing worker copies (golden-request tests — capture by reading the two verified modules' call construction, not by network).

### Phase 3 — docs, template, changelog
- [x] Usage sections in `docs/onboarding-a-worker.md` (config: a 10-line worker example with a 3-field model; gsheets: construct-with-injected-service example).
- [x] `worker-template/`: generated worker's config module becomes a `BaseModel` + `load_config` call (template smoke green).
- [x] Changelog `[Unreleased]` entries (two new public surfaces, one new extra).

### Phase 4 — migration recipe (documented here, executed per-repo)
- [x] Table: worker · current loader file(s) · model to define · env vars affected (names only) · sheets call sites. Rule: migrations are mechanical only where behaviour is identical; any worker quirk (e.g. legacy single-underscore env names) stays in a worker-side shim, listed explicitly in the recipe.

## Migration recipe

Survey source: current worker `origin/main`s fetched during build on 2026-06-12.
Pydantic floor: all pydantic-using workers are already on v2 (`xops`/`xcqc`
floor `>=2.7`; `xletter`/`xadmissions`/`xhr` floor `>=2.13.3`; `xbook` floor
`>=2.13.4`), so `clonway-cockpit[config]` at `pydantic>=2` is compatible.
`Auto-Secretary` has no pydantic config loader yet.

| Worker | Current loader file(s) | Model to define/reuse | Env vars affected (names only) | Sheets call sites | Migration rule |
|---|---|---|---|---|---|
| Auto-Bookkeeper | `src/xbook/ai/gateway.py`, `src/xbook/cashflow/config.py`, `src/xbook/cashflow/payroll.py`; leave catalogue/data YAML such as valuation/rows configs separate unless they are promoted to operator config models. | Reuse existing gateway/cashflow/payroll models; add thin worker-side wrappers that call `load_config(..., worker_id="xbook")`. | `XBOOK_MODELS_CONFIG`, `OCCUPANCY_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_KEY`. | `src/xbook/workspace/sheets.py`, plus callers in `src/xbook/cli/__init__.py`, `src/xbook/cli/occupancy.py`, `src/xbook/agent/tools.py`. | Mechanical for pydantic-backed loaders; preserve any existing explicit path args. Sheets migration can replace `extract_sheet_id`, `list_tabs`, and `read_values` after credentials remain worker-owned. |
| Auto-Orchestrator | `src/xops/config.py`; leave `src/xops/fleet/metrics/config.py` as a bundled metric catalog/data YAML unless the operator starts editing it as runtime config. | Existing `Config`/`WorkerConfig`. | `XOPS_CONFIG`, `XOPS_GCS_BUCKET`, `XOPS_DIGEST_TO`, `XOPS_DASHBOARD_URL`. | None found. | Replace path resolution with a worker shim: `XOPS_CONFIG` path first, then `~/.xops/config.yaml`; call shared loader with explicit `paths`. |
| Auto-Secretary | No shared pydantic/YAML app config loader found on current `origin/main`. | Introduce `WorkerConfig` only when a real operator config bundle appears. | None for loader migration. | None found. | No-op for config and Sheets in the first wave; do not invent a config model. |
| Auto-HR | `src/xhr/config/` package (domain modules), `src/xhr/integrations/sheets.py` for Sheets wrapper. | Keep domain config models in `xhr.config`; wrap file loads through shared `load_config` where they are single-file YAML models. | `XHR_SHEETS_SA`, `WORKSPACE_SA_KEY`, `DBS_REGISTER_SHEET_ID` and existing config-specific env names in `xhr.config`. | `src/xhr/integrations/sheets.py`, `src/xhr/cli/onboarding.py`, `src/xhr/cli/tracker.py`, `src/xhr/jobs/tracker_digest.py`, `src/xhr/onboarding_kickoff/apply.py`, `src/xhr/onboarding/hr_matrix_writer.py`, `src/xhr/integrations/mandatory_training.py`. | Replace `GoogleSheetClient` with `SheetsClient` where methods match; keep HR-matrix writer custom batch update logic until its range semantics are separately pinned. Credential helper stays in `xhr`. |
| Auto-Inspector | `src/xcqc/readiness/config.py`, `src/xcqc/readiness/homes.py`; `src/xcqc/cadence/catalog.py` and `src/xcqc/standards/sources.py` are catalog/data YAML, not generic app config. | Existing readiness/home models. | Existing readiness config path/env seams only; keep Google auth envs in `readiness/google/auth.py`. | Protocol-style `SheetsClient` in `src/xcqc/readiness/sources.py`; readers under `src/xcqc/readiness/readers/`; Google auth scopes in `src/xcqc/readiness/google/auth.py`. | Migrate loader-shaped readiness/home files only. Leave catalog/data YAML in place until there is a worker-owned pydantic model and operator-facing config contract. |
| Auto-Marketer | `src/xletter/audience/store.py`, `src/xletter/consent/store.py`, `src/xletter/dossier/policy.py`, `src/xletter/drive_config.py`; audience/consent use ruamel round-trip because comments/ordering are data. | Existing `DriveConfig` and `EditorialPolicy` are candidates; audience/consent stay custom round-trip stores. | `XLETTER_CONFIG_DIR`, `WORKSPACE_SA_KEY`, `XLETTER_ACTIVITIES_SHEET_ID`. | `src/xletter/journal/sync/activities.py` (`GoogleSheetsClient`), no standalone Sheets helper found. | Keep `XLETTER_CONFIG_DIR` as a worker-side path shim; do not force legacy single-underscore names into shared loader. Use shared Sheets only inside the journal sync client after credential construction remains local. |
| Auto-Admissions | `src/xadmissions/config.py` (`load_config_dir`, `_read_yaml`, optional models). | Existing `ConfigBundle` and per-file models (`MailboxConfig`, `TrackerConfig`, etc.). | `XADMISSIONS_SA_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`; config directory remains CLI/path supplied. | `src/xadmissions/google_read.py`; tracker sheet id lives in `TrackerConfig`. | Mechanical per YAML file using explicit `paths=[config_dir / "...yaml"]`; keep sign-off hash logic and optional-file semantics in worker code. |

General migration rule: start with files that already read a single YAML mapping
into a pydantic model. Do not migrate catalog/data YAML, round-trip YAML stores
that preserve comments, or sign-off/hash workflows until their domain behaviour
is explicitly pinned in the worker's own tests. Any legacy single-underscore or
directory-style env convention remains a worker-side shim that passes explicit
`paths`/`env_prefix` to the shared loader; the framework only understands the
new double-underscore overlay.

## Acceptance criteria

- A three-field example model loads from (a) YAML only, (b) env only, (c) both with env winning — demonstrated in tests and the onboarding doc.
- A config with two bad fields and one unset secret env produces ONE `ConfigError` listing three problems, each with provenance.
- `SheetsClient` survives a simulated 429 storm (4 × 429 then 200) and fails after the 5th consecutive error; payloads for append/update byte-match the golden requests derived from the two verified worker copies.
- `import clonway_cockpit` and the prod-import CI job pass with no extras installed.
- `make check` + `make template-smoke` green; changelog updated.

## Risks & dependencies

- **The marketer's "third sheets copy" was not directly verified** in this plan's survey (the bookkeeper and HR copies were). Re-verify at build time; if absent, the extraction still stands on two copies + two pre-live workers about to need it, but the migration table must reflect reality.
- **Pydantic version skew:** workers pin their own pydantic; the extra's floor (`>=2`) must be compatible with every worker's pin — survey at build time and pick the highest common floor.
- **Env overlay typing edge cases** (lists, dates) are pydantic's job, but document the string-in/coerced-out rule prominently; do not invent a mini-parser.
- **Sheets quota behaviour in CI:** all tests are offline against the fake; never add a live-API test here.
- Cross-repo: migrations (5+ workers for config, 2–3 for sheets) are separate PRs gated on a release tag (release-engineering plan) and each worker's own suite; the inspector's many `yaml.safe_load` sites include *catalog* files that may be better left untouched — the recipe must distinguish loader-shaped sites from data-file reads.
- Companion-plan coupling: `gsheets` examples reference the google-auth plan's `build_service`; if that plan lands second, use a plain `discovery.build` example meanwhile.

## Next-agent pickup

- Branch: `claude/shared-config-sheets` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- TDD per phase; Phase 1 and 2 are independent — commit separately, one PR.
- First actions: (1) re-verify the marketer sheets copy and the five loader files at current `origin/main`; (2) survey worker pydantic pins for the extra floor. Paste both surveys into the PR description.
- Do NOT: add pydantic/pyyaml to core dependencies (extra only); put credential resolution inside `gsheets`; encode any real spreadsheet id, account, or project value in tests/docs (public repo — use obviously-fake ids); attempt the worker migrations from this branch.
- Done = acceptance criteria verified, `make check` + prod-import + template-smoke green, changelog entry present.

## HANDOFF NOTES

- Current phase: final PR finish protocol after full post-rebase gates.
- Completed: Phase 1 config loader with optional `[config]` extra and dev test deps for CI; Phase 2 `gsheets` helper with injected-service API, fake tests, no google imports; Phase 3 onboarding docs, worker-template config module, and changelog; Phase 4 migration recipe table; QA-fix RED/GREEN tests added for `get_records(header_row=2)`, unset `SecretEnvName` provenance, and release-tag onboarding docs.
- Verification so far:
  - `uv run pytest tests/test_config_loader.py -q` -> `10 passed in 0.38s`
  - `uv run --no-dev python -c "import clonway_cockpit"` -> exit 0, no output
  - `uv run pytest tests/test_gsheets.py -q` -> `13 passed in 0.01s`
  - `uv run pytest tests/test_config_loader.py tests/test_gsheets.py -q` -> `23 passed in 0.07s`
  - `uv run pytest tests/test_worker_template.py::test_template_generates_expected_layout tests/test_worker_template.py::test_template_config_loads_defaults_and_env_overlay tests/test_shared_config_sheets_docs.py -q` -> `4 passed in 2.01s`
  - `uv run pytest tests/test_worker_template.py -q` -> `13 passed in 14.07s`
  - `uv run pytest tests/test_shared_config_sheets_docs.py::test_plan_contains_worker_migration_recipe -q` -> RED before recipe (`assert '## Migration recipe' in text`)
  - `uv run pytest tests/test_shared_config_sheets_docs.py -q` -> `3 passed in 0.01s`
  - `make check` after rebase -> ruff passed; format `131 files already formatted`; mypy `Success: no issues found in 54 source files`; pytest `879 passed in 16.16s`
  - `uv run --no-dev python -c "import clonway_cockpit"` -> exit 0, no output
  - `make template-smoke` after rebase -> generated xsmoke; generated pytest `15 passed, 1 xfailed`; ruff passed; format `18 files already formatted`; mypy `Success: no issues found in 12 source files`; CLI off `signals: disabled`; CLI on `signals: emitted 0`; `template-smoke PASSED for xsmoke (job)`
  - `pre-commit run --all-files` after rebase -> `InvalidConfigError: .pre-commit-config.yaml is not a file` (repo has no pre-commit config)
  - QA-fix RED: `uv run pytest tests/test_gsheets.py::test_get_records_with_non_default_header_row_fetches_data_rows -q` -> failed because requested range was `'Register'!2:2`, not `'Register'!2:`
  - QA-fix RED: `uv run pytest tests/test_config_loader.py::test_aggregates_validation_errors_and_unset_secret_env tests/test_config_loader.py::test_unset_secret_env_error_uses_env_overlay_provenance -q` -> failed because unset secrets were reported as `env MISSING_API_KEY`
  - QA-fix RED: `uv run pytest tests/test_shared_config_sheets_docs.py::test_onboarding_docs_include_config_and_sheets_examples -q` -> failed because onboarding still used `rev = "<sha>"`
  - QA-fix GREEN: `uv run pytest tests/test_gsheets.py::test_get_records_with_non_default_header_row_fetches_data_rows -q` -> `1 passed in 0.01s`
  - QA-fix GREEN: `uv run pytest tests/test_config_loader.py::test_aggregates_validation_errors_and_unset_secret_env tests/test_config_loader.py::test_unset_secret_env_error_uses_env_overlay_provenance -q` -> `2 passed in 0.05s`
  - QA-fix GREEN: `uv run pytest tests/test_shared_config_sheets_docs.py::test_onboarding_docs_include_config_and_sheets_examples -q` -> `1 passed in 0.01s`
  - `git rebase origin/main` after QA fix -> `Current branch claude/plan-shared-config-sheets is up to date.`
  - `make check` after QA fix -> ruff passed; format `131 files already formatted`; mypy `Success: no issues found in 54 source files`; pytest `881 passed in 17.71s`
  - `uv run --no-dev python -c "import clonway_cockpit"` after QA fix -> exit 0, no output
  - `pre-commit run --all-files` after QA fix -> `InvalidConfigError: .pre-commit-config.yaml is not a file` (repo has no pre-commit config)
  - `make template-smoke` after QA fix -> generated xsmoke; generated pytest `15 passed, 1 xfailed`; ruff passed; format `18 files already formatted`; mypy `Success: no issues found in 12 source files`; CLI off `signals: disabled`; CLI on `signals: emitted 0`; `template-smoke PASSED for xsmoke (job)`
- Decisions:
  - `SecretEnvName` is a pydantic `Annotated[str, ...]` marker; unset secret env vars warn for otherwise-valid configs and are folded into `ConfigError.problems` when validation already fails. QA fix: those `ConfigError` entries now use the config value provenance (`file <path>` or `env <VAR>`) and name the missing secret env var in the message body.
  - `pydantic`/`pyyaml` are optional under `[config]` and also in the dev dependency group so CI's existing `uv sync` can run the config tests without changing core dependencies.
  - Template tests now pass `vcs_ref="HEAD"` to Copier so they exercise the branch head, including newly added template files.
  - Re-verified Auto-Marketer on `origin/main`: no standalone sheets helper; Sheets access lives in `src/xletter/journal/sync/activities.py`.
  - QA docs fix changes an operator-facing onboarding step: worker pins now use the release tag named in `docs/pin-sync.md` (example `rev = "v0.1.0"`), not raw commit SHAs.
- Known-failing tests: none from focused QA-fix runs.
- Next concrete step: commit/push this final handoff-note update, post the required runbook delta, mark PR ready/needs-qa, and add DONE evidence.
