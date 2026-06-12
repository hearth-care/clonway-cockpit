# [Plan] Framework quality hardening

**Status:** implementation in progress on PR #93
**Source:** fleet audit 2026-06-11, items C3, C4, C5, C18, C20, C16
**Wave:** 1

Six self-contained hardening items on the framework itself. They share a theme — the cockpit is load-bearing under eight workers, so its internal softness has fleet-wide blast radius — but they are independently landable; the phases below are ordered by risk, not dependency.

## Why

- **C3 — `render.py` is a 1,560-line monolith** (verified: `wc -l src/clonway_cockpit/render.py` = 1560, the largest module in the package; next is `shell.py` at 990). It mixes three concerns: page chrome (`page`, `_Page`, `render_header` :143, `render_pulse` :184, `render_needs_you` :216, `render_toolkit` :258, `_legend` :1008, `render_cockpit_screen` :1047), flow panels (`render_menu` :335, `render_preflight` :401, `render_walk_*` :489–624, `render_doctor*` :662/936, `render_usage_section` :843, `render_filter` :971), and the entire `model_*` agent-projection family (:1109–:1545). Every worker imports from it; any edit risks everything.
- **C4 — the capability registry is mutable module-global state with manual test cleanup.** `registry.py:96` `_CAPABILITIES: dict[str, CapabilitySpec] = {}`; `clear_capabilities()` (:113) is "test-only" but `tests/conftest.py` has **no autouse fixture** — `tests/test_seam_rest.py` alone calls `clear_capabilities()` manually at 10+ sites, and any new test that registers a capability and forgets to clear leaks state into whichever test runs next. Worker suites inherit the same hazard (workers register at import time per the module docstring).
- **C5 — `WizardContext.client` is `object | None`** (`registry.py:27`, with a comment explaining the spine never calls methods on it and workers "narrow it to a real client where they need it"). In practice worker capability cores narrow with casts/asserts; the type system gives no help connecting a worker's `build_walk_ctx` to what its handlers receive.
- **C18 — gateway config validates shape, not runtime viability.** `gateway/config.py` `from_dict` checks providers/models/urls/timeouts, but: the env var named by `api_key_env` is only read when an adapter is built **per call** (`gateway.py` `_build_adapter`), so a missing key surfaces mid-conversation, not at startup; a typo'd role name fails at first `resolve()` call; non-mapping pricing entries are silently skipped (`config.py:75-76` `continue`). For colleague personas answering live DMs, "fails at the first turn" is the bad version of "fails at boot".
- **C20 — no API reference.** The package exposes a large public surface (modules: `shell`, `walk`, `registry`, `render`, `keys`, `signals.*`, `gateway.*`, plus the persona platform) documented only via docstrings and hand-written docs/*.md; the audit counted ~100 exported symbols with no generated reference, so consumers grep the source.
- **C16 — delivery-truth stamps: mostly landed since the audit snapshot, residual gap remains.** Verified at `dcda649`: `docs/persona-platform-architecture.md` now carries a delivery table with an explicit four-rung status ladder (designed → coded → deployed → watched-working) and `tests/test_docs_delivery_truth.py` pins the most failure-prone claims. The residual gap: rows encode their rung in free prose inside one **Status** cell (e.g. "DONE (#78 — framework core; the live deploy is the remaining operator step)"), so the table cannot be linted row-by-row and a new row can silently omit its rung.

## Scope

**In:** the six items above, framework-repo only.
**Out:** worker-side adoption (only C4's plugin and C3's import stability touch workers, both designed to need zero worker changes); the signal-layer hardening (companion plan `2026-06-fleet-audit-signal-hardening.md`); any new feature surface.

## Spec

### C3 — split `render.py`

```
src/clonway_cockpit/render_chrome.py   # page/_Page, breadcrumbs, header, pulse,
                                       # needs-you, toolkit, chip, screen_header,
                                       # _legend, cockpit_screen, help
src/clonway_cockpit/render_panels.py   # menu, capability card, preflight,
                                       # remedy/doctor confirms, walk/sync/staged
                                       # progress, walk result, note, doctor,
                                       # usage section, filter
src/clonway_cockpit/render_models.py   # every model_* twin + model_unstructured
src/clonway_cockpit/render.py          # facade: re-exports the entire current
                                       # public surface; no logic remains
```

Rules: pure mechanical move — zero behaviour change; `render.py` keeps re-exporting **everything** currently importable (workers import from `clonway_cockpit.render`; the facade is permanent API, not a transition aid); the render↔model parity contract (`tests/test_contract.py`, `contract.assert_render_model_parity`) must keep discovering pairs across the new module boundary — extend its discovery to scan the three modules (a `render_*` in chrome/panels pairs with `model_*` in models). A pin test asserts the facade's `dir()` superset against a recorded symbol list.

### C4 — autouse registry isolation

In `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _isolated_capability_registry():
    saved = dict(registry._CAPABILITIES)
    yield
    registry._CAPABILITIES.clear()
    registry._CAPABILITIES.update(saved)
```

Snapshot/restore (not blind clear) so module-import-time registrations survive. Additionally export the same fixture for workers as a pytest plugin: `src/clonway_cockpit/testing.py` with `capability_registry_guard` and a documented `pytest_plugins = ["clonway_cockpit.testing"]` one-liner for worker conftests. Existing manual `clear_capabilities()` calls in `test_seam_rest.py` stay (they clear *within* tests deliberately); the fixture removes the *forgot-to-clean* class of bug.

### C5 — typed `WizardContext.client`

PEP 695 generic, default preserves today's looseness:

```python
@dataclass(frozen=True)
class WizardContext[ClientT = object]:
    state: dict
    client: ClientT | None
    ...
```

- Spine code keeps treating it as opaque (unchanged).
- A worker annotates its builder `def build_walk_ctx(...) -> WizardContext[XeroClient]` and its handlers `Handler = Callable[[WizardContext[XeroClient]], None]`; mypy then tracks the narrowing end-to-end.
- `Handler` alias becomes `Handler = Callable[[WizardContext[Any]], None]` so existing un-annotated workers type-check unchanged.
- Verify mypy (repo pins a current mypy) supports PEP 696 defaults for the generic; if not, fall back to `WizardContext(Generic[ClientT])` with an exported `AnyWizardContext = WizardContext[object]` alias — decide at build time, record in changelog.

### C18 — gateway startup validation

```python
class Gateway:
    def validate(self, *, roles: Iterable[str] | None = None,
                 check_env: bool = True) -> list[str]:
        """Return problems (empty = healthy). roles=None → all configured.
        Checks per role: resolvable; api_key_env set AND the named env var
        non-empty (when check_env); litellm extra importable when provider
        is litellm. Plus config-level: pricing models that match no role's
        model (likely typo) → warning string."""
```

- Pure inspection — builds no adapter, sends no request (a network "ping" is explicitly out: startup must not cost tokens or hang on a provider).
- `GatewayConfig.from_dict` tightening: non-mapping pricing entry becomes a `GatewayError` (today silently skipped — silent-config-loss is the exact class the audit flags); unknown top-level keys produce a warning list accessible on the config (not an exception — forward-compat).
- Worker wiring recipe (docs): call `gateway.validate(roles=("chat",...))` at boot/Doctor; non-empty → fail fast in servers, render as Doctor probes in cockpits.

### C20 — pdoc API reference in CI

- Dev-dep `pdoc`; `make docs` target: `uv run pdoc clonway_cockpit -o build/docs` (build/ gitignored).
- CI: a `docs` job in `ci.yml` (or the reusable workflow once the shared-CI plan lands) that runs `make docs` — pdoc failures (import errors, broken refs) fail the build. Publishing: GitHub Pages via `actions/deploy-pages` on push to `main` only, `permissions` scoped to that job. The repo is public; generated docs expose nothing the source doesn't.
- Module docstrings already carry the contract prose (verified across `obs.py`, `signals/emit.py`, `registry.py`); no mass docstring-writing phase — fix only what pdoc errors on.

### C16 — delivery-table rung columns (residual)

- Restructure both tables in `docs/persona-platform-architecture.md` to explicit columns: `| Slice | Designed | Coded | Deployed | Watched-working | Refs |` with per-cell `yes/no/—` + PR refs; prose nuance moves to a Notes column.
- Extend `tests/test_docs_delivery_truth.py`: every row in the delivery tables parses (column count), each rung cell is from the closed vocabulary, and a row cannot claim a later rung without all earlier rungs (`deployed=yes` requires `coded=yes`).
- The update rule ("advance a rung only in the PR that records the observed run") stays; the test makes malformed claims unrepresentable rather than merely discouraged.

## Implementation plan

Ordered phases; each lands with `make check` green and is independently mergeable (one PR with phase commits, or split C3 out if review size demands).

- [x] **Phase 1 (C4):** autouse fixture + `clonway_cockpit/testing.py` plugin + a regression test that deliberately registers without cleanup and asserts the next test sees a clean registry. Files: `tests/conftest.py`, `src/clonway_cockpit/testing.py`, `tests/test_registry_isolation.py`.
- [x] **Phase 2 (C18):** `Gateway.validate` + `from_dict` tightening + tests (missing env var named, typo'd role, bad pricing entry now raising, litellm-extra check with import shim). Files: `src/clonway_cockpit/gateway/{gateway,config}.py`, `tests/test_gateway_validate.py`. Changelog: pricing tightening is a behaviour change — call it out.
- [x] **Phase 3 (C3):** mechanical split per spec; parity-contract discovery extended; facade pin test. Files: four render modules, `src/clonway_cockpit/contract.py` (discovery scan), `tests/test_render_facade.py`. **Zero diff** in any other test file is the proof of mechanical-ness.
- [x] **Phase 4 (C5):** generic `WizardContext`; mypy-strict clean; a typed-worker example in `docs/onboarding-a-worker.md`; verify worker-template still generates type-clean code. Files: `src/clonway_cockpit/registry.py`, docs, template if needed.
- [ ] **Phase 5 (C20):** pdoc dev-dep, `make docs`, CI job, Pages publish. Files: `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml` (+ pages workflow).
- [ ] **Phase 6 (C16):** table restructure + test extension. Files: `docs/persona-platform-architecture.md`, `tests/test_docs_delivery_truth.py`.
- [ ] Changelog entries per phase under `[Unreleased]`.

## Acceptance criteria

- C4: the deliberate-leak regression test fails without the fixture and passes with it; full suite green with the fixture active (proves no test depended on leaked state).
- C3: `git diff --stat` shows no test-file changes besides the two named; `from clonway_cockpit.render import <any previously-public name>` works for the recorded symbol list; parity contract still enumerates the same pair count as before the split (assert the count).
- C5: `uv run mypy src` clean; a snippet with `WizardContext[FakeClient]` narrows `.client` without cast (checked by a mypy-run test or a typed test file).
- C18: `Gateway.validate` returns precise problem strings for each seeded defect class; a clean config returns `[]`; no network access in any validate test (no mocks of HTTP needed = proof).
- C20: CI `docs` job green; Pages serves the generated reference for `main` (verify the deployed URL renders `clonway_cockpit.walk`).
- C16: mutating any rung cell to an out-of-vocabulary value or an inconsistent ladder locally makes the suite fail.

## Risks & dependencies

- **C3 is the blast-radius item.** Mitigations are structural (facade permanence, parity-count assertion, zero-test-edit rule), but re-verify at build time that no worker imports private names (`_`-prefixed) from `render` — survey the eight worker repos' imports first (`grep -rn "from clonway_cockpit.render import" ../*/src`); anything private that workers touch must stay importable from the facade too.
- **C5 mypy/PEP 696 support:** check the pinned mypy's changelog before choosing the default-generic form; the fallback is specced.
- **C18 pricing tightening** may break a worker with a sloppy pricing block at its next pin bump — changelog + pin-sync advisory must flag it (release-engineering plan provides the channel).
- **C20 Pages** needs repo settings (Pages enabled, Actions as source) — operator step; CI job must be green independently of publish.
- **C16** edits a doc other plans also reference; rebase-late, keep the diff table-only.
- Interplay with the shared-CI plan (reusable workflow): if it lands first, the docs job goes into the reusable workflow's optional inputs instead of `ci.yml` — check before wiring.

## Next-agent pickup

- Branch: `claude/framework-quality` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- Run phases in the listed order (cheap isolation wins first, the risky mechanical split only once the suite is guarded by Phase 1).
- Before Phase 3: run the worker-import survey (grep above) and paste results into the PR; before Phase 4: confirm mypy PEP 696 support.
- Do NOT: change any render/model output bytes in Phase 3 (parity + golden behaviour is the bar); make `validate()` perform network calls; deprecate `clonway_cockpit.render` (the facade is permanent); add docs-publishing credentials of any kind (Pages uses the workflow token); include internal identifiers anywhere (public repo).
- Done = all six phase acceptance criteria demonstrated, `make check` green, changelog updated per phase.

## HANDOFF NOTES

- Current phase: Phase 4 (C5) implemented; preparing full `make check` before commit/push.
- Next concrete step: start Phase 5 (C20) by adding a failing docs-build/Makefile or CI assertion for `make docs`, then add pdoc dev dependency and workflow wiring.
- Decisions taken: `.claude/` was already gitignored; no `.gitignore` change required. No existing changelog file was present, so `CHANGELOG.md` was created with an `[Unreleased]` section. Gateway unknown top-level config keys are stored as `GatewayConfig.warnings` and reported by `Gateway.validate()`. Render split kept a static facade import list so mypy can see `clonway_cockpit.render` attributes. PEP 696 default type parameters were rejected by mypy under `--python-version 3.12`, so Phase 4 used Python 3.12 generic syntax without a default (`WizardContext[ClientT]`) and exported `AnyWizardContext = WizardContext[object]` for loose call sites.
- Worker import survey: `grep -R "from clonway_cockpit.render import" -n /Users/olliepage/Developer/*/src` found only facade imports in Auto-Admissions (`render_note`), Auto-Bookkeeper (star/explicit primitive re-export and `render_needs_you`), and Auto-HR (`render_note`); no worker imports from the new implementation modules are required.
- Known-failing tests: none known after `uv run pytest -q tests/test_wizard_context_typing.py`, `uv run pytest -q tests/test_worker_template.py`, and `uv run mypy src` passed.
