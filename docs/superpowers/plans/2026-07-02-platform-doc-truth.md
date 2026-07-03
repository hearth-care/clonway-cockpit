# [Plan] Platform doc truth: conformance tracker + pin/release narrative refresh

- **Date:** 2026-07-02 · **Branch:** `claude/plan-platform-doc-truth` · **Status:** implementation complete — finish protocol in progress
- **Surfaces:** [`docs/fleet-conformance.md`](../../fleet-conformance.md), [`docs/pin-sync.md`](../../pin-sync.md), [`docs/persona-platform-getting-started.md`](../../persona-platform-getting-started.md) (§"Fleet adoption matrix" + §C), `README.md` (status table)

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task (Claude: superpowers:subagent-driven-development or superpowers:executing-plans; Codex: the same phase/verification discipline). Steps use checkbox (`- [ ]`) syntax. Tick checkboxes as work lands and commit this plan with the edits. **This PR is documentation-only — every changed file is `.md`. Do not touch code, scripts, or workflows.**

## Why (problem & goal)

The adoption/conformance story this repo tells is frozen at 2026-06-12/14 and has been overtaken by
events: the wave-5 pin-sync PRs landed across the fleet (2026-06-21 → 2026-06-28), `v0.2.0` was
released 2026-06-14, and two workers gained `--agent-stdio`. Today the tracker still claims two
workers are not cockpit-drivable and that the whole fleet sits on raw SHAs — both false. A doc that
is the declared "single source of truth for cockpit adoption status" (fleet-conformance.md's own
words) actively misleads planning while stale.

**Goal:** every adoption/pin claim across the four surfaces is re-verified against the **live
`origin/main` of each worker repo on the day the builder edits it**, corrected, and stamped
`verified <date> against <sha>` per row — using the tracker's own verification recipe and the
repo's own pin-survey script as the evidence trail.

## Binding decisions (do not re-litigate)

- **Truth source = live remotes, not local checkouts and not this plan.** The recon table below
  (2026-07-02, local disk) is *advisory*. The builder re-verifies every cell with the tracker's
  recipe (`gh api` / `gh search code`) and `python3 scripts/check_fleet_pins.py` at build time, and
  stamps what was actually observed. If live truth differs from this plan's expectation, **the
  observed value wins** — record the delta in HANDOFF NOTES.
- **The `Supported: v0.1.0` line in pin-sync.md is policy, not narrative — do NOT change it.**
  Which tag the fleet baselines on is an operator/release decision (PR #108 deliberately made the
  survey accept workers on a *newer* release tag). This PR corrects descriptions of reality only.
- **No policy edits, no code edits, no CI edits.** `scripts/check_fleet_pins.py` is run, not
  modified.
- **fleet-conformance.md stays the single adoption source of truth (HR6).** The duplicated
  per-worker pin/channel cells in `persona-platform-getting-started.md`'s matrix are replaced by a
  pointer plus only the platform-adoption notes that doc uniquely owns — never a second hand-synced
  copy of pins. The boundary validator for pin claims is `scripts/check_fleet_pins.py` (it reads
  the supported line and the live remotes; its pasted output is the acceptance evidence).
- **Not operator-facing.** No command, key, flag, provisioning, sign-off, or rhythm changes —
  **no RUNBOOK DELTA required**; this is explicitly a docs-truth PR.

## Recon evidence (2026-07-02, read-only, local checkouts — advisory, builder re-verifies)

| Worker | Repo | Cockpit pin observed | `--agent-stdio` | Notes |
|---|---|---|---|---|
| xbook | auto-bookkeeper | `v0.2.0` (pyproject `[tool.uv.sources]`) | yes | pin bumped ~2026-07-01; final evidence later observed `v0.3.0` |
| xhr | auto-hr | `v0.1.0` | yes | pin-sync PR 2026-06-21 (`8c51f82`) |
| xletter | auto-marketer | `v0.1.0` | **yes** — added 2026-06-12 18:23, commit `855d980` (`src/xletter/cli/__init__.py`) | tracker's 06-12 row predates the same-day add |
| xquill | auto-secretary | `v0.1.0` | **yes** — added 2026-06-15, commit `43d94ea` (`src/xquill/cockpit.py`) | read-only status surface |
| xadmissions | auto-admissions | `v0.1.0` | yes | Initial recon expected a parity gap, but live verification found both contract asserts present on `main` |
| xcqc | auto-inspector | `v0.1.0` | yes | pin-sync PR 2026-06-21 |
| xsource | Auto-Procurer | `v0.1.0` | yes | pin-sync PR 2026-06-28 |
| xops bridge | auto-orchestrator | `v0.1.0` | yes | pin-sync PR 2026-06-25 |

Caveat driving the "live remotes" rule: four local checkouts (auto-hr, auto-inspector,
auto-marketer, auto-secretary) were last pulled 2026-06-21 — eleven days stale at recon time.

Release facts: `v0.2.0` tagged 2026-06-14 (CHANGELOG `## [0.2.0] - 2026-06-14`); `v0.1.0` tagged
2026-06-11; `main` @ `904e4ab` carries post-0.2.0 fixes including PR #108 (pin survey accepts
newer-than-baseline release tags).

## Functional contract — what "done" looks like

Every corrected claim is a checkbox below with exact before → after (HR5's enumeration applied to
doc rows: the full set of stale cells is listed; there is no "update the tables as needed"). After
the edit, **no data cell in any of the four surfaces contradicts the builder's fresh
verification output**, and every touched row carries a fresh `verified <sha> · <date>` stamp per
the tracker's own rule ("a row is not green without a verified commit").

Worked example of the verification arithmetic (HR7, pinned to the recon fixture — builder replaces
with observed values): `python3 scripts/check_fleet_pins.py` at recon time is expected to report
**8/8 workers on release tags — 7 × `v0.1.0` + 1 × `v0.3.0` (xbook, newer-than-baseline: accepted
per PR #108) — exit code 0**. If the run reports anything else, the observed report is what goes
in the docs.

---

## Implementation plan

**Goal:** four doc surfaces telling one verified, dated truth.
**Architecture:** n/a — doc-only. **Tech stack:** markdown + `gh` CLI + `python3
scripts/check_fleet_pins.py` (read-only run). **No new dependencies, no code changes.**

### Global constraints

- Doc-only diff: every changed file matches `\.md$` (verify with `git diff --name-only` before
  each commit).
- Truth = live `origin/main` per worker at edit time; every corrected row stamped
  `<sha> · <date>` observed via the tracker's recipe commands.
- No operator-facing changes — no RUNBOOK DELTA (stated per HR1).
- **Depends on: nothing unmerged. No `[Wave N]` tag** (HR11).
- Gates (exact canonical commands QA re-runs, verbatim — doc-only PRs still run them; paste
  tails) (HR2): `make lint`, `make format`, `make typecheck`, `make test`; plus the evidence run
  `python3 scripts/check_fleet_pins.py` (expected exit 0; paste full output in the PR/DONE
  comment).

### Task 1 — fresh evidence pass (no edits yet)

- [x] Run, verbatim, and save output: `python3 scripts/check_fleet_pins.py`
- [x] For each of the 8 worker repos, run the tracker's recipe steps 1–4
  (`gh api repos/hearth-care/<repo>/contents/pyproject.toml --jq '.content' | base64 -d | grep -A2 'clonway-cockpit'`;
  `gh search code --repo hearth-care/<repo> agent_stdio`;
  `gh search code --repo hearth-care/<repo> assert_render_model_parity` and
  `... assert_drives_clean`;
  `gh api repos/hearth-care/<repo>/commits/main --jq '{sha: .sha[0:7], date: .commit.committer.date[0:10]}'`).
  Record per worker: pin `rev`, agent-stdio evidence, both-contract-functions evidence, HEAD
  `sha · date`. (If `gh search code` is rate-limited/unavailable, fall back to
  `gh api` contents reads of the known test paths named in the recon table.)
- [x] **Commit** (evidence goes in the PR comment, not committed files): nothing to commit —
  proceed. (Checkpoint is the saved output.)

### Task 2 — `docs/fleet-conformance.md`

Each box = one claim corrected with before → after (builder substitutes freshly observed
sha/date where this plan shows recon values):

- [x] Header line 3: `read 2026-06-12` → `read <build date>` (keep the source description).
- [x] xletter row: `_(no --agent-stdio)_` / Contract test `No` / drive path `n/a` / Known
  exceptions `Not cockpit-drivable; --agent-stdio absent from CLI` → observed truth
  (`uv run xletter --agent-stdio`; contract-test cell per the Task 1 `gh search code` result —
  expected both-functions evidence or `Partial`, whichever is observed; fresh
  `Last verified` sha · date). Observed pin cell `4c63daf` → `v0.1.0`.
- [x] xquill row: same correction shape as xletter (`uv run xquill --agent-stdio`, observed
  contract-test cell, pin `4c63daf` → `v0.1.0`, fresh stamp).
- [x] xbook row: observed pin `8449c2d` → `v0.3.0`; fresh stamp.
- [x] xhr row: observed pin `a75f7a0` → `v0.1.0`; fresh stamp; keep the 60s first-frame exception
  unless Task 1 finds it resolved.
- [x] xadmissions row: plan expected `Partial` + parity-gap exception, but live evidence showed
  `tests/cockpit/test_agent_contract.py` now imports both `assert_render_model_parity` and
  `assert_drives_clean`; pin `4c63daf` → `v0.1.0`; fresh stamp.
- [x] xcqc, xsource, xops-bridge rows: pins `4c63daf` → `v0.1.0`; fresh stamps.
- [x] "Open gaps (2026-06-12)" section retitled with the build date and re-cut to observed truth:
  **remove** "xletter, xquill: No `--agent-stdio` …" (false), **remove** "Pins on raw SHA …" and
  "xbook pin …" (false — all eight on release tags), **remove** the xadmissions parity gap
  (closed on live `main`), refresh the observed contract-gate truth, and refresh the xhr
  first-frame note per observation.

- [x] **Verify:** every edited row's stamp matches Task 1 output; `git diff --name-only` shows
  only `.md`.
- [x] **Commit:** `docs(fleet-conformance): re-verify all 8 rows against live origin/main (<date>)`

### Task 3 — `docs/pin-sync.md`

- [x] Leave `Supported: v0.1.0` line untouched (binding decision).
- [x] Replace the "Last static snapshot: 2026-06-14" table (rows claiming
  `4c63daf…` / `1c86802…` / `a75f7a0…` raw-SHA pins, "9/70/122 commits behind/ahead") with a fresh
  static snapshot dated at build time, generated from the Task 1 `check_fleet_pins.py` output —
  expected shape: 7 workers `v0.1.0` (at baseline), xbook `v0.3.0` (newer release tag — accepted,
  note PR #108), plus the "re-run the script for current state" line retained.
- [x] Add one narrative sentence to the snapshot section: `v0.2.0` was released 2026-06-14; the
  supported baseline remains `v0.1.0` until the operator moves it; a worker on a newer release
  tag is conformant per the survey's newer-tag rule (PR #108). (Describes reality; changes no
  policy.)
- [x] **Verify** doc-only diff; **Commit:** `docs(pin-sync): fresh pin snapshot — fleet on release tags (<date>)`

### Task 4 — `docs/persona-platform-getting-started.md` (adoption matrix + §C)

- [x] Replace the "Fleet adoption matrix" per-worker `Cockpit pin` and `Agent channel` cells
  (stale: raw SHAs `a75f7a02…`/`200493cc…`/`21d68b35…`/`991b639…`/`21597f4`/"none observed";
  "No `--agent-stdio` marker observed" for xletter/xquill/xadmissions — all false now) with a
  pointer: pins + channel status live in `docs/fleet-conformance.md` (single source, HR6). Keep
  only the platform-adoption-note column content this doc uniquely owns, refreshed against Task 1
  observations.
- [x] §C "Decide whether xletter and xquill should become cockpit-drivable workers": rewrite the
  premise to observed truth (both ship `--agent-stdio` today; final refresh shows both now run the
  framework contract gate, so the remaining question is platform/persona adoption depth).
- [x] **Verify** doc-only diff; **Commit:** `docs(getting-started): adoption matrix defers to the conformance tracker`

### Task 5 — `README.md` status claims

- [x] "Framework status" row `Fleet adoption | Uneven — consumers are conformant only after
  pinning + wiring; see below` → reflect verified state, e.g.
  `All 8 fleet workers pin release tags and expose --agent-stdio; all 8 run the framework contract
  gate (see docs/fleet-conformance.md — verified <date>)` (builder pins the exact
  worded truth to Task 1 results; keep the pointer).
- [x] Persona-platform row: leave `no live Chat transport yet` **unless** the transport-edge work
  has merged by build time — verify against `origin/main` before touching it (it is true as of
  `904e4ab`).
- [x] **Verify** doc-only diff; **Commit:** `docs(readme): fleet-adoption status matches verified tracker truth`

### Task 6 — final verification + gates

- [x] Re-read all four surfaces; confirm zero remaining `2026-06-12`/`2026-06-14`-stamped data
  cells that Task 1 contradicted. Drift-guard command (expected: zero hits):
  `grep -rnE "4c63daf|no .--agent-stdio|2026-06-12" docs/fleet-conformance.md docs/pin-sync.md docs/persona-platform-getting-started.md README.md`
  (dated historical narrative elsewhere — e.g. CHANGELOG — is untouched and out of this grep's scope).
- [x] `git diff origin/main --name-only` → only the four `.md` surfaces + this plan.
- [x] Full gates, verbatim, paste tails in DONE (HR2): `make lint` · `make format` ·
  `make typecheck` · `make test`; paste `python3 scripts/check_fleet_pins.py` output.
- [x] **Commit:** `docs(plan): tick platform-doc-truth checkboxes + handoff`

## Self-Review

- Spec coverage: every stale claim identified in recon → an exact before→after checkbox (Tasks
  2–5); evidence discipline → Task 1; drift guard → Task 6.
- Safety invariants: n/a (no code, no writes beyond docs); the doc-integrity invariant — no green
  cell without `sha · date` — is enforced per-row in Task 2 (HR3 applied to the doc contract).
- Tests: n/a for code; the falsifiable acceptance is Task 1's pasted command output vs the edited
  cells — QA re-runs the same commands and diffs (no trust in builder claims).
- HR6: one adoption source of truth (fleet-conformance.md) + `check_fleet_pins.py` as the
  validator; getting-started matrix demoted to a pointer.
- HR7: the expected survey outcome (7×v0.1.0 + 1×v0.3.0, exit 0) is pinned, with the observed-wins
  rule stated.
- Gates: `make lint` / `make format` / `make typecheck` / `make test` + the survey script,
  verbatim (HR2).
- Operator-facing: no — explicitly no RUNBOOK DELTA (HR1).
- Dependencies: none; no wave (HR11).
- Deferred: moving the supported baseline to a newer release tag (operator/release decision).

## HANDOFF NOTES

- Current phase: implementation and review fixes complete; builder-codex-20260703T062314Z-60518-191 re-ran
  the pin survey, drift guard, rebase check, full local gates, and pre-commit by
  2026-07-03T06:26:31Z.
  auto-bookkeeper remains on `v0.3.0`, the other seven workers remain on `v0.1.0`, and the branch
  is current with `origin/main`.
- Next concrete step: push this final handoff refresh, run finish protocol, then worktree cleanup.
- Decisions taken: live-remote truth wins over this plan's recon; supported line untouched. Task 1
  used fresh shallow clones under `/tmp/pr110-evidence` after `gh search code` hit search-rate
  limits. Observed delta from plan: auto-admissions now has both `assert_render_model_parity` and
  `assert_drives_clean`; auto-secretary/xquill now has both framework contract-gate calls on live
  `main` too. Final acceptance review found auto-bookkeeper, auto-hr, and auto-marketer had
  advanced on `main`; their tracker stamps were refreshed to `c9b98b5`, `e20f14a`, and
  `759054c` while their cockpit pins stayed on release tags. A later final read-only review
  found auto-bookkeeper, auto-admissions, and auto-orchestrator had advanced again; their
  tracker stamps were refreshed to `549d69d`, `f7843b1`, and `72d1166` after confirming pins and
  contract evidence still matched the tracker. `v0.3.0` (chat_addon transport + bounded persona
  thread memory) released 2026-07-02 after this plan was written; noted in pin-sync.md and the
  getting-started checklist; auto-bookkeeper now pins `v0.3.0` on live `main`, supported baseline
  still `v0.1.0`. Final
  review found one stale advisory recon sentence for auto-admissions; it was corrected to match
  the observed contract-gate truth. A later final review found §C still duplicated worker
  pin/channel facts; §C now points back to the conformance tracker and keeps only platform/persona
  decisions. Another review found the adoption matrix still repeated channel/conformance
  wording in worker notes; those notes now stay persona/platform-only. A final review found stale
  `v0.2.0` baseline-target wording and a README duplicate verification date; both were corrected.
  A subsequent final evidence re-check hit GitHub code-search rate limits and used direct contents
  API reads of the known CLI and contract-test paths as the fallback evidence path; reviewer found
  two remaining date inconsistencies, so the open-gaps heading and persona tracker pointer were
  normalised to the 2026-07-03 verification date while leaving the persona-notes observation date
  explicit. The latest final audit also hit GitHub code-search
  rate limits during final audit and used direct contents API reads; all eight workers still expose
  `agent_stdio`, all eight contract-test files still contain both contract assertions, and all live
  worker HEAD stamps still match the tracker. A doc-truth audit then found the old one-minor-skew
  policy sentence contradicted the checker and the accepted `v0.3.0` xbook pin; pin-sync.md now
  states the checker-backed rule directly without changing the supported baseline. This builder's
  final evidence pass also hit GitHub code-search rate limits after auto-marketer and used direct
  contents API reads for the known CLI and contract-test paths; the observed pins, contract
  evidence, and live HEAD stamps still match the docs. This finish pass re-used direct contents API
  reads and found the same evidence; auto-orchestrator's `agent_stdio` proof is in
  `src/xops/cli/bridge.py` for the `xops bridge --agent-stdio` subcommand rather than
  `src/xops/cli/__init__.py`. This builder re-used direct contents API reads and found the same
  HEAD stamps, `agent_stdio` files, and contract-test evidence; GitHub code search rate-limited
  during the auto-secretary pass, so the fallback path remained the reliable evidence source.
  This builder used fresh shallow clones under `/tmp/pr110-evidence-builder-codex-189`; the
  observed pins, live HEAD stamps, `agent_stdio` files, and contract-test evidence still match the
  docs. An attempted direct API helper failed after accidentally shadowing zsh `path`; it did not
  change any repo state, and the shallow-clone pass replaced it as the evidence source.
- Known failing tests: none. Final gates after this builder's evidence refresh:
  `git rebase origin/main` → current; `grep drift-guard` → no matches;
  `git diff origin/main --name-only` → README.md, docs/fleet-conformance.md,
  docs/persona-platform-getting-started.md, docs/pin-sync.md, this plan;
  `python3 scripts/check_fleet_pins.py` → exit 0, 7×v0.1.0 + auto-bookkeeper v0.3.0;
  `make lint` → All checks passed!; `make format` → 162 files already formatted;
  `make typecheck` → no issues in 67 files; `make test` → 1114 passed in 30.01s;
  `pre-commit run --all-files` → all Passed.
- Dependencies/operator TODOs: none.
