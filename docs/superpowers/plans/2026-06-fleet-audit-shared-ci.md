# [Plan] Reusable CI workflow + pre-commit baseline for the fleet

**Status:** implemented — PR #89 (claude/plan-shared-ci)
**Source:** fleet audit 2026-06-11, items O6, O7
**Wave:** 1

## Why

All nine fleet repos run the same CI by copy-paste. Verified at 2026-06-11 `origin/main` of each repo, the nine `ci.yml` files total **903 lines** (cockpit 94, and across the eight workers: 140 / 76 / 83 / 65 / 213 / 68 / 98 / 66) and share an identical skeleton:

```
actions/checkout@v6 → astral-sh/setup-uv@v7 (enable-cache,
cache-dependency-glob: pyproject.toml) → actions/setup-python@v6 (3.12)
→ uv sync → ruff check → ruff format --check → mypy → pytest
```

with only cosmetic divergence: lint paths (`.` vs `src tests scripts`), mypy invocation (`mypy src` vs bare `mypy`), pytest selectors (`-q` vs `-m "not integration and not live"`), and trigger shape (one worker runs PR CI only on `ready_for_review`). Several repos carry extra repo-specific workflows (deploy, watchdog, scheduled jobs) that are *not* duplication and stay put.

The cost is not the lines; it is that improvements never propagate. This repo's `ci.yml` grew a `prod-import` job (catches a module leaking a dev-only dependency at PR time) and a `concurrency` cancel group — no worker has either unless someone hand-copies them eight times. Conversely, an actions version bump (`checkout@v6` → v7) is currently nine PRs.

Pre-commit is worse: **one repo in nine has a `.pre-commit-config.yaml`** (verified: only the bookkeeper worker; this repo has none either). The fleet policy (global + this repo's `CLAUDE.md` §"Tests") is explicit — fast hooks (ruff / format / mypy / cheap checks) on commit, full pytest in CI only — but eight repos have nothing enforcing the fast half at all.

The cockpit is the right home: it is already the fleet's shared-contract repo, it is **public** (a hard requirement — `workflow_call` across repos needs the workflow repo accessible to every caller), and `worker-template/.github/workflows/ci.yml.jinja` already stamps the duplicated skeleton into every *new* worker, so fixing the template here stops the bleeding at the source.

## Scope

**In:**
- One reusable workflow in this repo, `.github/workflows/reusable-ci.yml`, consumed by all nine repos (including this repo's own `ci.yml`, which becomes a caller — dogfooding).
- A canonical `.pre-commit-config.yaml` for the fleet: shipped in this repo (for itself) and templated into `worker-template/`.
- `worker-template/.github/workflows/ci.yml.jinja` rewritten as a thin caller.
- A per-repo adoption checklist (one doc, eight rows) for the existing workers.

**Out:**
- Deploy / watchdog / scheduled workflows in worker repos (repo-specific, not duplicated logic).
- The full-pytest pre-commit hook anywhere (explicitly against fleet policy — CI owns the suite).
- Branch protection (audit item O1, org-level).
- Actually opening the eight worker adoption PRs (mechanical follow-ups listed in the checklist).

## Spec

### 1. `reusable-ci.yml` (O6)

`on: workflow_call` with inputs (all optional, defaults = the fleet-common shape):

| Input | Type | Default | Notes |
|---|---|---|---|
| `python-version` | string | `"3.12"` | |
| `lint-paths` | string | `"."` | passed to `ruff check` / `ruff format --check` |
| `mypy-args` | string | `"src"` | bare `""` → run plain `mypy` (config-driven repos) |
| `pytest-args` | string | `"-q"` | e.g. `-m "not integration and not live"` |
| `prod-import-package` | string | `""` | non-empty → run the prod-deps import-smoke job (`uv sync --no-dev` + `python -c "import <pkg>"`) |
| `runs-on` | string | `"ubuntu-latest"` | |

Jobs: `lint` (ruff + format + mypy), `test` (pytest), `prod-import` (conditional on `prod-import-package != ''`). Each job uses the checkout → setup-uv (cached) → setup-python → `uv sync` preamble exactly as today. `permissions: contents: read`. No `concurrency` block inside the reusable workflow (a called workflow inherits the caller's ref-scoped group; callers keep their own `concurrency` stanza — document this in a comment).

Caller shape (what each repo's `ci.yml` becomes, ~15 lines):

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request:
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  ci:
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@v0.2.0
    with:
      pytest-args: '-m "not integration and not live"'
```

Pinning: callers reference the reusable workflow **by release tag** (`@v0.2.0`), never `@main` — this depends on the release-engineering plan (`2026-06-fleet-audit-release-engineering.md`) having produced tags; if it has not landed yet, pin by full SHA and leave a TODO referencing that plan. Required-status-check names change when jobs move into a called workflow (`ci / lint` → `caller-job / lint`); the adoption checklist must include re-pointing branch protection (once O1 lands) at the new check names.

### 2. Pre-commit baseline (O7)

`.pre-commit-config.yaml`, identical across the fleet:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: <current>        # trailing-whitespace, end-of-file-fixer,
    hooks: [...]          # check-added-large-files, check-merge-conflict,
                          # detect-private-key
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: <current>
    hooks:
      - id: ruff          # --fix
      - id: ruff-format
  - repo: local
    hooks:
      - id: mypy          # language: system → `uv run mypy src` (uses the
                          # repo's own pinned mypy + stubs, not a hook venv)
```

Explicitly **no pytest hook** (fleet policy: full suite in CI; a repo that wants one uses `stages: [manual]`). The mypy hook runs via `uv run` so hook results match CI exactly. The same file is added to `worker-template/` as `.pre-commit-config.yaml.jinja` (only the mypy path varies if the template's layout differs — it does not; template is `src/`-layout).

### 3. Worker-template change

`worker-template/.github/workflows/ci.yml.jinja` → thin caller per Spec §1, with `prod-import-package: "{{ package_name }}"` left **unset** (workers are applications, not libraries; the import-smoke job is the framework's own concern) and `pytest-args` defaulted. Template smoke (`make template-smoke` / `tests/test_worker_template.py`) must still pass — note the generated workflow cannot be *executed* by the smoke test; assert shape (parses as YAML, `uses:` line points at this repo and a tag) instead.

### 4. Adoption checklist — `docs/ci-adoption.md`

A table: repo · current `ci.yml` lines · caller inputs needed (from the verified divergences above) · pre-commit status (new file / replace existing) · gotchas (the `ready_for_review`-only trigger repo decides deliberately whether to keep that trigger in its caller — the reusable workflow does not dictate triggers). Each row is one mechanical worker PR: replace `ci.yml` body with the caller, add `.pre-commit-config.yaml`, `pre-commit run --all-files` once, fix what it flags, done.

## Implementation plan

### Phase 1 — reusable workflow, dogfooded here
- [x] Add `.github/workflows/reusable-ci.yml` per Spec §1.
- [x] Convert this repo's `.github/workflows/ci.yml` into a caller (`prod-import-package: clonway_cockpit`); uses relative path (`./.github/workflows/reusable-ci.yml`) for same-repo call.
- [ ] Verify on the PR itself: all three jobs run via the call, caching works (second run restores), cancellation works (push twice). ← OPERATOR: check CI run logs on PR #89.
- [x] Test: `tests/test_ci_shape.py` (12 tests) — parses YAML via PyYAML (transitive dep of copier); asserts workflow_call declared, inputs documented, no concurrency in reusable, caller does not pin @main. Note: PyYAML parses `on:` key as Python bool `True`; tests use `_on()` helper.

### Phase 2 — pre-commit baseline
- [x] Add `.pre-commit-config.yaml` per Spec §2; ran `pre-commit run --all-files`; one mechanical fix (EOF on a plan doc) committed separately.
- [x] Document in `CLAUDE.md` §"Tests": pointer to the config and install command.

### Phase 3 — worker template
- [x] Rewrite `worker-template/.github/workflows/ci.yml.jinja` as thin caller; add `worker-template/.pre-commit-config.yaml.jinja`.
- [x] `tests/test_worker_template.py` extended with 4 new tests asserting template shape. Note: tests read `.jinja` source files directly (not via copier generation) because copier clones the git repo and resolves the default branch, so in-progress branch changes are not visible to copier in tests.

### Phase 4 — adoption checklist
- [x] Write `docs/ci-adoption.md` per Spec §4 with the divergence table re-verified (numbers differ from plan snapshot — 136/69/219/79/86/71/100/70 lines).
- [x] `CHANGELOG.md` created with `[Unreleased]` entry documenting all new contract surfaces.

## Acceptance criteria

- This repo's CI runs entirely through `reusable-ci.yml` and is green; lint, test, and prod-import all demonstrably execute (check the run logs, not just the green tick).
- A worker repo can adopt with a ≤20-line `ci.yml` and zero secrets/inputs beyond Spec §1 (proved by the template-generated worker in `make template-smoke` producing exactly that file).
- `pre-commit run --all-files` is green in this repo; no pytest hook exists in any config or template.
- `docs/ci-adoption.md` lists all eight workers with their exact caller inputs.
- Reusable-workflow inputs are documented in the file header comment; renaming any input is flagged as breaking in the changelog policy.

## Risks & dependencies

- **Tag dependency:** caller pins want a release tag — depends on the release-engineering plan (C1/C2). Pin by SHA as the interim and record the upgrade in `docs/ci-adoption.md`.
- **Org policy:** cross-repo `workflow_call` from private worker repos to this public repo requires "Actions → access" defaults that allow it (public repos are callable by default; verify once with one worker before writing the checklist as fact).
- **Required-check renames:** adopting repos with branch protection (post-O1) must re-point required checks; calling this out per row in the checklist is mandatory, or adoption PRs will appear to hang.
- **The 213-line outlier** worker `ci.yml` carries extra jobs; its adoption row keeps those jobs alongside the caller rather than forcing them into the reusable workflow.
- Re-verify at build time: actions versions (`checkout@v6`, `setup-uv@v7`) and the nine current `ci.yml` shapes — this plan's survey is a 2026-06-11 snapshot.

## Next-agent pickup

- Branch: `claude/shared-ci` off `origin/main` of `hearth-care/clonway-cockpit`, in a fresh worktree.
- Implement Phases 1–4 in order; Phases can share one PR (it is all CI/template surface) but commit per phase.
- First action: re-run the nine-repo `ci.yml` survey and diff against this plan's §Why; adjust inputs if a repo has drifted.
- Do NOT: open the eight worker adoption PRs from this branch (they are per-repo follow-ups); add a pytest pre-commit hook anywhere; reference the reusable workflow as `@main` in any committed caller or template; include org/project identifiers in docs (public repo).
- Done = acceptance criteria verified with run-log evidence, `make check` + `make template-smoke` green.

## HANDOFF NOTES

**Current phase:** COMPLETE — all 4 phases + 2 rounds of QA FAIL findings fixed, all gates green.

**Branch:** `claude/plan-shared-ci` (PR #89)

**Commits:**
- `d470672` Phase 1: reusable-ci.yml + thin ci.yml caller + test_ci_shape.py
- `2474f30` Phase 2: .pre-commit-config.yaml + CLAUDE.md update + pre-commit dep
- `5cf666d` Phase 3: ci.yml.jinja + .pre-commit-config.yaml.jinja + test_worker_template.py
- `3ca8814` Phase 3 fix: template tests read jinja source directly (copier clone workaround)
- `67ec564` Phase 4: ci-adoption.md + CHANGELOG.md + plan doc ticked
- `b15a757` QA fix: import sort, adoption doc cleanup, gitleaks CLI replacement
- `de66513` QA fix: remove double blank line after imports in test_safety.py.jinja
- `abb27a4` QA fix: ruff format compliance (elif block) in test_safety.py.jinja
- `16567b3` QA fix: separate ci_rev from clonway_rev, forbid @main pin in generated CI

**QA FAIL findings addressed (fixer-claude-20260611T184408Z-16134):**
1. `make template-smoke` ruff I001 — fixed by: adding `[tool.ruff.lint.isort] known-first-party`
   to pyproject.toml.jinja; removing double blank line; reformatting elif block.
2. Invalid partial adoption snippets in ci-adoption.md — replaced with "Blocked" callouts.
3. Gitleaks CI failure (missing GITLEAKS_LICENSE) — replaced licensed action with CLI v8.21.2.
4. Missing RUNBOOK DELTA — posted on hearth-care/auto-orchestrator#196.

**QA FAIL findings addressed (fixer-claude-20260611T192423Z-42347):**
1. Generated workers pinned reusable-ci.yml to `@main` — fixed by separating `ci_rev` from
   `clonway_rev` in copier.yml. `ci_rev` has a validator that rejects "main". The jinja template
   uses `{{ ci_rev }}` for the CI pin. Two new tests assert jinja uses `{{ ci_rev }}` and that
   copier.yml rejects `ci_rev == "main"`. template_smoke.sh and `_generate()` pass a sentinel
   SHA. Generation tests read jinja source directly (copier reads from git default branch,
   not the working tree, so generation-based CI file checks are unreliable on feature branches).

**Deviations from plan:**
- Same-repo caller uses `./.github/workflows/reusable-ci.yml` (relative path) instead of
  a SHA/tag — correct approach for same-repo `workflow_call`; worker repos use the full path.
- `test_worker_template.py` new tests read `.jinja` source files directly, not copier output —
  copier clones from git default branch, not the feature branch, making generation tests
  unreliable on feature branches. The shape assertions are still correct and sufficient.
- 8th fleet member is `Auto-Procurer` (not `xhr`); fleet is 8 workers + cockpit = 9 total.
- Current CI line counts (re-verified): 136/69/219/79/86/71/100/70 (not plan's estimate).
- Gitleaks uses CLI v8.21.2 instead of the licensed gitleaks-action (deliberate: avoids
  GITLEAKS_LICENSE requirement while preserving the same PR-diff scan policy).

**OPERATOR TODO:**
- Apply `run-ci` label on PR #89 to trigger the reusable CI and verify all three jobs
  (lint, test, prod-import) run in the GitHub Actions logs.
- Merge this PR; record the merge-commit SHA.
- Replace `<SHA>` in `docs/ci-adoption.md` with that merge-commit SHA.
- Open adoption PRs for each worker per `docs/ci-adoption.md` (start with auto-hr).
- Cut `v0.2.0` release tag once release-engineering plan lands.

**Known-failing:** none — `uv run pytest -q` (782 passed), `pre-commit run --all-files` (8 hooks passed),
and `make template-smoke` all green locally (fixer-claude-20260611T192423Z-42347 2026-06-11).
