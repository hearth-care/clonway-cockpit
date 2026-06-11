# CI Adoption Checklist — Fleet Workers

How each existing fleet worker adopts `reusable-ci.yml` (this repo) and the pre-commit baseline.
One PR per worker. Survey re-verified against `origin/main` of each repo on 2026-06-11.

## Before opening any adoption PR

1. **Pin the reusable workflow by tag or SHA** — never `@main`.
   Tag `v0.2.0` is the intended pin; until it is cut from the release-engineering plan
   (`docs/superpowers/plans/2026-06-fleet-audit-release-engineering.md`), use the
   SHA at which `reusable-ci.yml` first landed on `main`:

   ```
   hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
   ```

   Replace `<SHA>` with the merge-commit SHA of this PR once it lands on `main`.

2. **Cross-repo `workflow_call` access** — this repo is public, so worker repos can
   call it without org-level policy changes. Verify once with one worker (auto-hr is
   the cleanest candidate: no extra jobs, no system deps) before rolling out to all.

3. **Required-check renames** — when a job moves into a called workflow the check name
   changes from `lint` to `ci / lint` (caller-job-name / callee-job-name). If branch
   protection (audit item O1) has required checks pointing at the old names, re-point
   them after the adoption PR lands. Noted per-row below.

---

## Worker adoption rows

| Repo | Current `ci.yml` lines | `lint-paths` input | `mypy-args` input | `pytest-args` input | Extra jobs to keep locally | Pre-commit status | Gotchas |
|---|---|---|---|---|---|---|---|
| [auto-bookkeeper](#auto-bookkeeper) | 136 | `src tests` | `""` (bare) | — keep matrix locally | `test` (12-domain matrix), `prod-import` | Replace existing | Matrix job stays local |
| [auto-secretary](#auto-secretary) | 69 | `xquill xquill_review tests` | — omit (no mypy) | `""` (bare pytest) | None | New file | No mypy in current CI — see gotcha |
| [auto-inspector](#auto-inspector) | 219 | `.` (via `make lint`) | `""` (bare) | — keep test locally | `test` (via `make test`), `dashboard_changes`, `deploy_cqc_dashboard` | New file | Deploy jobs stay; test job stays (uses make) |
| [auto-hr](#auto-hr) | 79 | `src tests` | `""` (bare) | `-m "not integration and not live"` | None | New file | Cleanest candidate — start here |
| [auto-marketer](#auto-marketer) | 86 | `src tests` | `""` (bare) | `-m "not integration and not live"` | `test` (needs weasyprint apt-get) | New file | Test job stays local (system dep pre-step) |
| [auto-admissions](#auto-admissions) | 71 | `src tests scripts` | `""` (bare) | `-m "not integration and not live"` | None | New file | |
| [auto-orchestrator](#auto-orchestrator) | 100 | `src tests` | `src` | `-v` | `deploy` (GCP WIF) | New file | Deploy job stays; `UV_PYTHON_DOWNLOADS=never` stays in caller |
| [Auto-Procurer](#auto-procurer) | 70 | `.` | `src` | `-q` (default) | None | New file | All-defaults caller — simplest after auto-hr |

---

## Per-repo caller shapes

### auto-hr

Cleanest adoption — no extra jobs, no system deps, standard shape. Recommended first.

```yaml
name: CI

on:
  push:
    branches: [main]
    paths-ignore: ["docs/**", "**/*.md"]
  pull_request:
    types: [labeled]
    paths-ignore: ["docs/**", "**/*.md"]
  workflow_dispatch:
  merge_group:

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  ci:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
    with:
      lint-paths: "src tests"
      mypy-args: ""
      pytest-args: "-m \"not integration and not live\""
```

### auto-admissions

```yaml
# same trigger shape as auto-hr (no paths-ignore for this repo)
jobs:
  ci:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
    with:
      lint-paths: "src tests scripts"
      mypy-args: ""
      pytest-args: "-m \"not integration and not live\""
```

### Auto-Procurer

All inputs are defaults — minimal caller:

```yaml
jobs:
  ci:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
```

### auto-orchestrator

Keep the `deploy` job (GCP WIF, push-only) alongside the reusable call.
`UV_PYTHON_DOWNLOADS=never` is needed at the job level — pass it via `env:` on the caller
job (note: `env:` is not supported on `uses:` jobs; move env to the workflow-level `env:` key,
or open a follow-up to add an `extra-env` input to the reusable workflow).

```yaml
jobs:
  ci:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
    with:
      lint-paths: "src tests"
      mypy-args: "src"
      pytest-args: "-v"

  deploy:
    # keep as-is — GCP WIF deploy, push to main only
    ...
```

### auto-marketer

Test job stays local due to weasyprint system dependency pre-step. Use reusable for lint only.

```yaml
jobs:
  lint:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
    with:
      lint-paths: "src tests"
      mypy-args: ""
      pytest-args: "skip"   # suppress the test job via a sentinel

  test:
    # keep locally — weasyprint needs apt-get before uv sync
    ...
```

> **Note:** The reusable workflow does not yet have a way to suppress the `test` job without
> running `pytest skip` (which would fail). A cleaner option is to add a `skip-test` boolean
> input to `reusable-ci.yml` in a follow-up, or to promote the apt-get step to a
> `pre-test-command` string input. Until then, auto-marketer keeps its test job local.

### auto-bookkeeper

Matrix test (12 domains) and prod-import stay local. Use reusable for lint only — same
`skip-test` limitation as auto-marketer applies.

### auto-inspector

`make lint` / `make test` wrapping and the CQC dashboard deploy jobs stay local. The lint and
test steps can be adopted once the repo's Makefile targets are aligned with the direct invocation
shape (`uv run ruff check .` etc.), or the reusable workflow gets a `lint-command` override input.

### auto-secretary

Currently has **no mypy step**. Adopting the reusable workflow's lint job (which always runs
mypy) would add a new gate. Options before adopting:
1. Add a `mypy.ini` / `[tool.mypy]` config and fix any errors (recommended).
2. Wait for a `skip-mypy` input on the reusable workflow.

Until resolved, auto-secretary can adopt the `test` job only:

```yaml
jobs:
  lint:
    # keep locally until mypy situation resolved
    ...
  test:
    if: github.event_name != 'pull_request' || github.event.label.name == 'run-ci'
    uses: hearth-care/clonway-cockpit/.github/workflows/reusable-ci.yml@<SHA>
    with:
      # override all lint steps to no-op by pointing at non-existent paths
      # — not ideal; prefer adding a skip-lint input in a follow-up
      lint-paths: ""
      pytest-args: ""
```

---

## Mechanical steps for each adoption PR

1. Replace `ci.yml` body with the caller shape above (keep extra jobs as-is).
2. Add `.pre-commit-config.yaml` (copy from this repo or run `copier update`).
3. Run `uv run pre-commit run --all-files` once; commit any mechanical fixes separately.
4. Open the PR; add the `run-ci` label to trigger CI.
5. Verify all jobs run (check the GitHub Actions run log, not just the green tick).
6. If branch protection has required checks: re-point from `lint` → `ci / lint` and
   `test` → `ci / test` after the PR lands (or do it on the adoption PR branch — check names
   take effect on next run).

---

## Open follow-ups (not in scope for this PR)

- `skip-test` / `skip-mypy` boolean inputs on `reusable-ci.yml` — unblocks auto-marketer,
  auto-bookkeeper (test), auto-secretary (mypy).
- `pre-test-command` string input — clean alternative to `skip-test` for system dep installs.
- `UV_PYTHON_DOWNLOADS` env propagation — needed for auto-orchestrator (see [CI CI 504 note](../memory-not-applicable/ci-504.md)).
- Cut the `v0.2.0` release tag — all eight worker adoption PRs should reference it, not a SHA.
- Branch protection (O1) — required checks must be re-pointed after adoption.
