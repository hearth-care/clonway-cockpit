# [Plan] Platform versioning & release engineering

**Status:** implementation in progress on PR #88
**Source:** fleet audit 2026-06-11, items C1, C2, C17
**Wave:** 0

## Why

clonway-cockpit is the load-bearing spine under eight workers, and it has no release story at all:

- `pyproject.toml:3` — `version = "0.1.0"`, never bumped since extraction.
- `git tag` returns nothing. There is no `CHANGELOG.md`. The only workflow is `.github/workflows/ci.yml` (lint/test/prod-import; no release job).
- Every worker consumes the framework as a git dependency pinned by raw SHA in `[tool.uv.sources]` (the consumption model is documented in `CLAUDE.md` §"Consumption model"). There is no named thing to pin *to*, so pins drift apart silently and get re-synced ad hoc.

The audit snapshot (2026-06-11, morning) found **five distinct pinned revisions across the eight workers, one of them pinned to `main`** (i.e. unpinned — a framework push could change that worker's dependency closure with no PR on its side). By the time this plan was drafted (same day, after an unrelated rollout that happened to touch every `pyproject.toml`), the spread had collapsed to two revisions — `4c63daf` ×7 and `a75f7a0` ×1 — which proves the point rather than refuting it: pin convergence currently happens only as a *side effect* of unrelated fleet-wide changes, and the next drift cycle starts with the next framework merge. `origin/main` (`dcda649`) is already ahead of every pin.

Why drift matters here specifically:

- The Signal wire shape (`src/clonway_cockpit/signals/model.py` — `Signal.to_wire()`) and the run-telemetry wire (`src/clonway_cockpit/obs.py`) are cross-worker contracts: an emitter on one rev and a consumer (the orchestrator's bridge) on another can disagree about fields. `ScreenModel.schema_version` mitigates the agent-channel wire only.
- `~100` public symbols across the framework's modules have no deprecation path: a rename is discovered by whichever worker bumps its pin first.

C17 rides along because it is also release/`history` hygiene: this repo is **public** and its pre-extraction history originated in a private worker repo. The audit found no committed secrets, but there is no documented checklist asserting that the rotation/review was actually done, so the claim is unverifiable and unrepeatable.

## Scope

**In:**
- `CHANGELOG.md` (Keep a Changelog format) seeded retroactively from the merged-PR history.
- A retroactive `v0.1.0` tag and a tag-on-merge release workflow.
- A written semver policy: what counts as a breaking change for this framework.
- A pin-sync advisory document: the "supported revision" statement plus the per-worker update recipe.
- A security-rotation checklist for the pre-extraction public history (process doc; deliberately contains **no** secret names, project identifiers, or account identifiers — it instructs the operator where to look, privately).

**Out:**
- Actually bumping any worker's pin (that is eight one-line PRs in the worker repos, listed in the advisory's checklist; they happen after the first tag exists).
- Publishing to PyPI. Workers stay on git+tag pins.
- Branch protection (org-level audit item O1, handled outside this repo).
- Any code change to the framework itself.

## Spec

### 1. CHANGELOG.md (C1)

Root-level `CHANGELOG.md`, Keep a Changelog 1.1 layout:

```markdown
# Changelog
All notable changes to clonway-cockpit. Workers pin tags, not SHAs — see
docs/release-policy.md.

## [Unreleased]

## [0.1.0] - 2026-06-XX
Retroactive baseline: everything from extraction through <tag SHA>...
```

Rules (enforced, not aspirational — see test below):
- Every PR that touches `src/` adds a line under `## [Unreleased]` in the same PR.
- A release = move `Unreleased` into a dated `## [x.y.z]` section + bump `pyproject.toml` version, in one commit on `main` (via PR).

### 2. Semver policy (`docs/release-policy.md`)

One page. The contract surface, in precedence order:

| Surface | Breaking change examples | Bump |
|---|---|---|
| Wire shapes: `Signal.to_wire()`, obs run-log JSONL, `ScreenModel.to_dict()` (`schema_version`), handoff envelope (`handoff.py` payload) | field removed/renamed/retyped; semantics changed | **major** (post-1.0) / minor + loud changelog (pre-1.0) |
| Public Python API (documented modules: `shell`, `walk`, `registry`, `render`, `keys`, `signals.*`, `gateway.*`, persona modules) | signature change, removal, behaviour change a worker test would catch | major / minor as above |
| Underscore-prefixed names, `tests/`, `worker-template/` internals | anything | patch |

Pre-1.0 rule (we are pre-1.0): minor = may break with changelog callout; patch = never breaks. Deprecations: keep the old name re-exported with a `DeprecationWarning` for ≥1 minor version before removal.

### 3. Tag-on-merge release workflow (C1)

`.github/workflows/release.yml`:

- Trigger: `push` to `main`, path filter `pyproject.toml` (plus `workflow_dispatch` for the retroactive `v0.1.0`).
- Job: read `project.version` from `pyproject.toml` (`python -c` over `tomllib`, no new deps); if tag `v<version>` does not exist, create it and a GitHub Release whose body is that version's CHANGELOG section.
- Idempotent: tag exists → no-op success (re-runs and non-version merges stay green).
- `permissions: contents: write` on this workflow only; `ci.yml` stays `contents: read`.

A release is therefore: PR that edits `CHANGELOG.md` + `pyproject.toml` → merge → tag appears. No manual tagging, no second source of truth.

### 4. Pin-sync advisory (C2) — `docs/pin-sync.md`

- States the **one currently supported tag** (a single line, updated each release — machine-greppable: `Supported: v0.1.0`).
- Worker recipe: change `[tool.uv.sources]` `rev = "<sha>"` → `rev = "v0.1.0"` (uv accepts tags as revs), run `uv lock`, run the worker's suite, one-line PR.
- Policy: workers MUST pin a tag (never a bare SHA, never `main`); the fleet-level config file (`~/.config/clonway/fleet.json`, operator-side, not in this repo) gains a per-worker `cockpit_pin` key so the orchestrator's doctor can diff actual vs supported — that key addition is specced here, implemented in the orchestrator repo.
- Skew window: at most one minor version between any two workers; the advisory documents the order to update when a wire shape changes (consumers before emitters).

### 5. Rotation checklist (C17) — `docs/security/public-history-checklist.md`

Process-only document (safe for a public repo):

1. Enumerate history: `git log --all --diff-filter=A --name-only` reviewed for config/credential-shaped files; `gitleaks detect --no-banner` (or `trufflehog git`) over the full clone.
2. For each *category* of credential the pre-extraction code could have referenced (OAuth client configs, API tokens, service-account keys), confirm in the operator's private notes that the credential was rotated on or after the repo went public, or rotate now.
3. Record completion as a dated line in this checklist file (e.g. `2026-06-XX — sweep run, tool versions, 0 findings`) — the file is the auditable artefact the 2026-06-11 audit found missing.
4. Re-run the sweep in CI: add a `gitleaks` job to `ci.yml` (scan the PR diff, not full history, for speed) so new leaks are blocked at PR time.

The checklist never names a specific secret, service account, project, or domain. Findings, if any, go to the operator privately — never into an issue or PR on this repo.

## Implementation plan

### Phase 1 — policy + changelog (no workflow yet)
- [x] Write `docs/release-policy.md` per Spec §2.
- [x] Write `CHANGELOG.md`: seed `[0.1.0]` retroactively from `git log --first-parent main --oneline` grouped by area (cockpit spine / signals / persona platform / worker-template); `[Unreleased]` section empty.
- [x] Test `tests/test_release_policy.py`: (a) `pyproject.toml` version appears as a `## [<version>]` heading in `CHANGELOG.md`; (b) `CHANGELOG.md` contains an `## [Unreleased]` heading. Style: mirrors the existing docs-pinning test `tests/test_docs_delivery_truth.py`.

### Phase 2 — release workflow + retroactive tag
- [x] Add `.github/workflows/release.yml` per Spec §3 (tag + GitHub Release from changelog section; idempotent).
- [ ] Run it once via `workflow_dispatch` to cut `v0.1.0` at the merged plan-implementation commit.
- [ ] Verify: `git ls-remote --tags origin` shows `v0.1.0`; release body matches the changelog section.

### Phase 3 — pin-sync advisory + rotation checklist
- [x] Write `docs/pin-sync.md` per Spec §4, naming `v0.1.0` as supported and listing the eight worker repos as a checklist (repo name + current pin at time of writing).
- [x] Write `docs/security/public-history-checklist.md` per Spec §5 (steps only; no identifiers).
- [x] Add the `gitleaks` PR-diff job to `ci.yml` (continue-on-error **false**; pin the action by SHA).
- [x] Update `CLAUDE.md` §"Consumption model": pins are tags; releases via changelog+version PR.

### Phase 4 — worker follow-ups (tracked here, executed per-repo)
- [ ] Eight one-line pin PRs (`rev = "v0.1.0"` + `uv lock`) — consumers (orchestrator) first.
- [ ] Orchestrator doctor check: actual pin vs `docs/pin-sync.md` supported line (separate repo, separate plan).

## Acceptance criteria

- `git tag` lists `v0.1.0`; the tag SHA is on `main`; a GitHub Release exists with the changelog body.
- Merging a PR that bumps `project.version` to `0.2.0` (and only such a PR) produces tag `v0.2.0` automatically; merging a non-version PR produces no tag and a green release workflow run.
- `tests/test_release_policy.py` fails if version and changelog drift apart (verified by mutating one locally).
- `docs/pin-sync.md` names exactly one supported tag and a recipe a fresh agent can follow in a worker repo without reading this plan.
- `docs/security/public-history-checklist.md` exists, contains zero identifiers (manual review + the gitleaks job passes on it), and has at least one dated completion line after the operator runs the sweep.
- gitleaks job green on `main`.

## Risks & dependencies

- **Tag permissions:** `release.yml` needs `contents: write`; confirm org settings allow the default `GITHUB_TOKEN` to create releases on a public repo. Fallback: a fine-grained PAT is *not* acceptable here (public repo) — use the token or fail loudly.
- **Pin state will have moved again** by build time: re-run the pin survey (`git show origin/main:pyproject.toml | grep clonway-cockpit.git` per worker) before writing the advisory's table; do not copy this plan's numbers.
- **uv tag-rev behaviour:** verify `rev = "v0.1.0"` resolves and locks reproducibly with the fleet's uv version before recommending it in the advisory (it pins the resolved SHA in `uv.lock`, which is the behaviour we want — confirm).
- **gitleaks false positives** on docs/fixtures: tune `.gitleaks.toml` allowlist in the same PR; never allowlist a real finding.
- Cross-repo: Phase 4 touches all eight worker repos and the orchestrator doctor; those are separate PRs and must not be bundled into this one.
- C17 verification step requires operator action (private credential records); the repo-side deliverable is the checklist + CI job only.

## Next-agent pickup

- Branch: `claude/release-engineering` off `origin/main` of `hearth-care/clonway-cockpit` (work in a fresh worktree; never commit to `main`).
- Order: Phase 1 → 2 → 3 as separate commits in one PR (or 1+2 / 3 as two PRs if review size warrants); Phase 4 is per-worker follow-ups, NOT in this repo's PR.
- Before starting: re-verify `git tag` is still empty and no `CHANGELOG.md` has appeared; if either exists, reconcile rather than overwrite.
- Do NOT: tag anything before the changelog test is merged; add Co-Authored-By trailers or generated-with footers (repo policy); put any org/project/account identifier, secret name, or internal URL into any doc — this repo is public; bump worker pins from this repo.
- Done = acceptance criteria all demonstrably true, `make check` green, release workflow observed running on a real merge.

## HANDOFF NOTES

- Agent: `builder-codex-20260611T171402Z-89967`.
- Current phase: Phase 3 implemented locally; next concrete step is Phase 3 green verification, then full gates/rebase.
- Decisions taken: first release remains `0.1.0`; changelog baseline is grouped from first-parent history through current `origin/main` (`8a53e3f`), while the actual `v0.1.0` tag is expected to point at the final merged PR #88 commit.
- Verification so far: baseline `uv run pytest -q` passed with `758 passed`; Phase 1 red test failed because `CHANGELOG.md` was missing; Phase 1 green `uv run pytest tests/test_release_policy.py -q` passed with `2 passed`; Phase 2 red test failed because `.github/workflows/release.yml` was missing; Phase 2 green `uv run pytest tests/test_release_policy.py -q` passed with `3 passed`; Phase 3 red test failed because `docs/pin-sync.md`, `docs/security/public-history-checklist.md`, and the gitleaks CI job were missing; Phase 3 green `uv run pytest tests/test_release_policy.py -q` passed with `6 passed`.
- Deferred/operator-only: workflow_dispatch for `v0.1.0` cannot be truthfully run until this no-merge PR is merged to `main`, because the required target is the merged plan-implementation commit; private full-history credential rotation confirmation must be done from operator records; worker pin PRs and orchestrator doctor work are separate repos.
- Known-failing tests: none.
