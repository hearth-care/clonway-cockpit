# Work order — make Doctor remedies navigable and verifiable

**PR:** `hearth-care/clonway-cockpit#114`

> **Fleet Foundry routing:** implement the linked design and plan on this same branch. This is a
> shared framework contract, not a worker-specific diagnosis. Build each task RED/GREEN, preserve
> backward compatibility for existing workers, then hand the code-bearing draft to independent QA.

## Outcome

A worker can tell the shared Doctor loop exactly what failed and what kind of remedy is valid.
Doctor can then:

- render a typed build/report failure instead of replacing every exception with one canned setup
  hint;
- open an existing registered capability, including an optional focus, through the same navigation,
  effect and guarded-write path used everywhere else;
- keep callable fixes and display-only guidance backward compatible;
- re-run the worker probe after a remedy returns; and
- emit one typed receipt stating whether the remedy was opened/run/declined/skipped/failed and
  whether the original probe resolved, remained or changed.

Human Rich and agent `ScreenModel` projections carry the same probe/remedy identity and action
metadata. Agent mode may navigate a capability remedy, because the existing capability effect gate
still protects writes; it still cannot silently run an arbitrary callback.

## Why this foundation is required

The current framework at `8694e30233bcfe24f45d1a3103b95dcd252054f2` supports only:

- `Fix(run=<callable>)`, which the Doctor executes itself; or
- `Fix(run=None)`, which is display-only.

It cannot express “open the existing `reconcile-board` capability with focus `unmatched`”. A worker
would have to duplicate navigation, smuggle a global sentinel through a callback, or leave the
remedy non-runnable. The interactive loop also catches every report-build exception without
passing the exception to a worker classifier, then asks for one generic unconfigured renderable.
Finally it records only a usage-open event: it has no before/after remedy identity or closure
receipt.

Auto-Bookkeeper #1008 is the first binding consumer. Its live semantic drive proves Doctor shows a
real unmatched-lines failure but only a display-only list command while Home already opens the
Reconcile board. The consumer will remain blocked until this framework PR merges and xbook pins its
exact revision.

## Binding artifacts

- Design: `docs/superpowers/specs/2026-07-12-doctor-remedy-actions-design.md`
- Plan: `docs/superpowers/plans/2026-07-12-doctor-remedy-actions.md`
- Readiness: `docs/findings/2026-07-12-doctor-remedy-actions-readiness.md`

## Public contracts

- `Fix` remains positional/backward compatible and gains stable remedy/probe identity plus exactly
  one action route: display-only, callback or registered capability.
- `Probe` remains positional/backward compatible and may carry stable `probe_id` and evidence
  revision.
- `DoctorActionKind`, `DoctorActionResult`, `DoctorClosure` and `DoctorRemedyReceipt` are public,
  frozen data contracts.
- `Host` gains optional worker callbacks for report-failure classification and receipt emission.
- `_open_capability(..., focus=...)` remains the sole capability launch path. Doctor capability
  remedies call it; no new navigation or write path is added.
- The special `doctor` capability receives the focus passed from a Home need and selects the
  matching probe/remedy when present.
- Report-build exceptions use the worker classifier when configured; legacy workers retain the
  existing unconfigured fallback.

## Non-negotiable behavior

- Existing `Fix(title, cmd, note, run, confirm)` and `Probe(name, level, detail, fix)` calls work
  unchanged.
- A fix cannot define both `run` and `capability_key`; invalid identity/focus/action combinations
  fail validation immediately.
- Capability remedies must reference a registered capability. Unknown keys render a safe failure
  and never execute a fallback command.
- Opening a capability records/navigates exactly as a normal Home/shelf/filter open.
- Any nested write remains behind that capability's existing approval/effect gate.
- Agent mode can open and inspect a capability remedy but cannot run arbitrary callback or local-
  maintenance fixes.
- Display-only remedies never become selectable.
- Confirmation cancellation performs no callback and records `declined`.
- After an attempted runnable/capability remedy, Doctor rebuilds once, re-evaluates the same stable
  `probe_id` and records resolved/still-present/changed/unknown.
- Receipt callbacks are best-effort observability; callback failure cannot crash Doctor or change
  the action result.
- Human/model rows share action kind, remedy ID, probe ID, capability key/focus and selection.
- No domain import, worker command, accounting write or framework-owned receipt file is added.

## Acceptance proof

Foundry completes only when hermetic public-path tests prove:

1. every legacy Doctor test/worker-template fixture remains green unchanged;
2. a typed report exception renders a real probe/action in Rich and ScreenModel;
3. a Home need focused on a Doctor probe opens Doctor with the intended remedy selected;
4. Enter on a capability remedy calls the existing capability chokepoint once with exact focus;
5. an agent can navigate that read-only route and receives structured nested frames, never
   `unstructured`;
6. a nested write still reaches the existing awaiting-apply gate and defaults to decline;
7. callbacks remain disabled in agent mode and confirmation cancellation is zero-effect;
8. missing capability, action exception and rebuild exception each produce safe typed outcomes;
9. resolved, still-present, changed and unknown closure receipts carry before/after identities;
10. receipt callback failure is isolated;
11. screen-model additive fields and protocol compatibility tests pass;
12. generated-worker subprocess and framework contract drives stay clean; and
13. full pytest, Ruff, format, mypy, pre-commit and diff gates pass.

## Implementation sequence

- Task 1: strict backward-compatible Doctor action and receipt types.
- Task 2: typed report-failure classification and focus threading.
- Task 3: capability remedies through the existing navigation/effect chokepoint.
- Task 4: rebuild comparison and best-effort receipt callback.
- Task 5: Rich/model parity and agent-mode drive.
- Task 6: generated-worker compatibility, documentation and release handoff.

## HANDOFF NOTES

- Current phase: QA FAIL round 3 Tasks 2–5 complete.
- Next concrete step: drive the generated-worker unconfigured path and make its classifier example
  opt-in so the documented setup hint remains reachable.
- Decisions: public contracts live in `clonway_cockpit.doctor`; identity fields reject surrounding
  or embedded whitespace while legacy empty IDs remain accepted and produce unknown closure.
- Task 1 gates: `19 passed`; Ruff passed; mypy passed; `git diff --check` clean.
- Task 2 gates: shell/model suite `121 passed`; generated-worker mapping is
  `tests/test_worker_template.py` (no `tests/test_generated_worker.py` exists) and `25 passed`;
  Ruff and mypy passed; `git diff --check` clean.
- Task 3 gates: capability/shell/contract suite `107 passed`; Ruff and mypy passed;
  `git diff --check` clean. Real `serve_stdio` tests prove structured nested navigation,
  default-declined existing write gate, callback skip, and zero `unstructured` frames.
- Task 4 gates: receipt/unit/shell suite `120 passed`; Ruff and mypy passed;
  `git diff --check` clean. Receipts cover all four closure values, every action result,
  repeat revisions, rebuild/classifier failures, and best-effort delivery.
- Task 5 gates: real-client/model/contract suite `27 passed`; Ruff and mypy passed;
  `git diff --check` clean. `CockpitClient` drives focused Home -> Doctor -> nested capability ->
  refreshed Doctor with one receipt and unchanged schema `1.0`.
- Task 6 gates: generated-worker suite `26 passed`; true subprocess legacy and opt-in acceptance
  drives `2 passed, 4 deselected`; full suite `1,213 passed in 26.27s`; Ruff passed; Ruff format
  reported `167 files already formatted`; mypy reported no issues in 67 source files; all-file
  pre-commit passed all eight hooks; `git diff --check` clean.
- Deviation: the merge commit/release tag requested by the plan cannot exist before operator
  merge. The readiness receipt records exact post-merge pin steps and assigns the final identifier
  insertion to the release owner.
- Current-main deviation: the plan named a generated-worker test file that is not present; the
  canonical worker-template subprocess suite is used instead.
- QA FAIL round 2 known-failing tests at its handoff: none.

### QA FAIL round 3 (qa-claude-20260730T151553Z-89916-7) — fixer-codex-20260730T214708Z-84400-47

- Task 2 focus matrix now crosses selection source (`focused`, `manual`), focus identity
  (`unique_probe_id`, `duplicate_probe_id`, `unique_remedy_id`, `duplicate_remedy_id`, `unknown`)
  and rebuild shape (`unchanged`, `predecessor_removed`, `predecessor_inserted`, `reordered`,
  `target_removed`) for 50 generated cells.
- A shared `_unique_match` is the fail-closed resolver used by before attribution, focus matching,
  post-rebuild selection and after-probe comparison. Duplicate focus IDs report
  `focus_matched=None`; Enter then follows the visible first-row fallback.
- Task 2 verification: focus matrix `50 passed`; Ruff passed; mypy reported no issues in
  `shell.py`; `git diff --check` clean.
- Task 4 receipt matrix crosses 7 before-pairing states, 4 after-identity states, and 2 display
  layouts for 56 generated cells. Duplicate after IDs produce an order-independent `unknown`
  receipt with no after-state fields; absent IDs remain `resolved`; legacy consume-on-match
  pairing is preserved.
- Task 4 verification: receipt matrix `56 passed`; Ruff passed; mypy reported no issues in
  `shell.py`; `git diff --check` clean.
- Task 5 Rich/model parity now crosses matched and unmatched focus. Rich renders the stable focus
  decision and tells the operator to review selection on an unmatched focus, while ScreenModel
  retains the same requested/matched metadata.
- Task 5 verification: Doctor drive/model/contract/screen-model suite `32 passed`; Ruff passed;
  mypy reported no issues in `render_panels.py`; `git diff --check` clean.
- Current phase known-failing tests: none.
- Base inspected: `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`.
- Initial baseline: 1,122 passed in 40.61 seconds; committed publication baseline: 1,122 passed in
  35.58 seconds.
- First consumer: Auto-Bookkeeper #1008; it is blocked on this PR and must pin the merged framework
  revision.
- No current framework PR exposes this seam; this package is the sole proposed owner.
- No code, worker state or external system was mutated during authoring.
- `RUNBOOK DELTA` posted on `hearth-care/auto-orchestrator#196`: numbered/arrow remedy selection,
  Enter action/open, focused stable selection across rebuilds, guarded capability writes, one
  post-action re-probe/receipt, bounded failure copy, and explicit review after a disappeared or
  ambiguous target.

### QA FAIL round (qa-claude-20260730T084851Z-65419-1) — fixer-claude-20260730T141659Z-27593-1

- Root cause of findings 1/3/4: `_runnable_remedies` (`src/clonway_cockpit/shell.py`) recovered
  the probe<->fix pairing by searching `probes` per fix and dropping any fix it couldn't pair,
  while `render_doctor`/`model_doctor` number every non-display-only fix straight from `fixes`
  with no such condition — the two projections could diverge in both row count and index.
  Rewritten to a single pass over `fixes` (the same order/count the render/model use) that pairs
  each entry against a shrinking pool of `probes` — identity match first, falling back to equality
  only among probes not already claimed by an earlier fix (a stable "consume-on-match") — and
  never drops an entry; an unpaired fix now carries `probe=None` and stays runnable.
- Finding 2: `Fix.__post_init__`'s `confirm` guard now only rejects `confirm=True` with `run=None`
  for fixes that opt into the new identity contract (`remedy_id`/`probe_id`/`capability_key` set).
  A bare legacy `Fix(title, cmd, note, None, True)` — and the equivalent kwargs shape — construct
  unchanged, matching main and this work order's own "positional constructors remain supported"
  claim (no doc/changelog correction needed since the claim is now true rather than aspirational).
- Finding 5: Doctor's per-frame loop recomputes `focus_matched` against the CURRENT remedy list on
  every repaint (previously computed once on the first frame and reused verbatim); the initial
  cursor jump onto the focused remedy is still gated by `focus_pending` so arrow-key navigation
  after the jump is not overridden back onto the focus target on later frames.
- `build_remedy_receipt` now accepts `before: Probe | None` — an unpaired remedy still delivers a
  receipt (`probe_id=""`, closure `unknown`) instead of the caller needing to special-case a
  missing probe or silently drop the row.
- Non-blocking nits also closed: `_validate_identity` now rejects any non-printable/control
  character anywhere in an identifier, not just leading/trailing whitespace; `_deliver_doctor_receipt`
  logs a receipt-sink failure (remedy_id/probe_id/action_result/closure/exception class only, never
  raw exception text) instead of silently suppressing it; the vacuous `secret not in safe_message`
  assertion in `tests/test_doctor_receipt.py` now actually routes the secret through probe `detail`;
  the decline/skip/failed parametrized receipt test now pins the rebuild count.
- RECURRENCE on the QA FAIL was `none`, so no AXES/MATRIX block is required in the completion
  comment; the pairing-defect class (findings 1/3/4) is still closed at the root and covered by a
  dedicated parametrized unit test over the full pairing matrix (identity / equality-fallback /
  shared-instance-consume-order / unpaired, crossed with display-only interleaving) in
  `tests/test_shell.py::test_runnable_remedies_pairs_every_non_display_only_fix_across_the_pairing_matrix`.
- Gates after this round: `uv run pytest -q` -> `1186 passed`; `uv run ruff check .` -> all passed;
  `uv run ruff format --check .` -> `167 files already formatted`; `uv run mypy src` -> no issues in
  67 source files; `uv run pre-commit run --all-files` -> all 8 hooks passed.
- Superseded runbook classification: although that fixer round did not add another key, the PR as a
  whole changes the operator-facing Doctor selection/action rhythm. The required delta is now posted
  on `hearth-care/auto-orchestrator#196`.

### QA FAIL round 2 (qa-codex-20260730T143737Z-89916-1) — fixer-codex-20260730T145425Z-89916-5

- Current phase: all QA FAIL round 2 findings fixed; exact-head full gates and finish protocol next.
- Doctor now preserves the remedy the operator actually selected by unique stable remedy/probe
  identity across predecessor insertion/removal and reorder. A manual arrow selection remains
  authoritative after the initial focus jump; a disappeared target is never treated as preserved.
- Public-path focus matrix:
  `tests/test_doctor_capability_action.py::test_doctor_preserves_selected_remedy_identity_across_rebuild_matrix`
  crosses 2 selection sources with 5 rebuild shapes (10 cells).
- Focus phase gates: focused matrix `11 passed`; shell/capability/model suite `145 passed`;
  generated-worker suite `26 passed`; Ruff and mypy passed; `git diff --check` clean.
- Task 3 capability exception safety: a real `CockpitClient` drive proves a throwing registered
  capability emits bounded class-only framework copy, returns to Doctor, emits exactly one receipt,
  and leaks no raw exception sentinel through any serialized frame or receipt.
- Task 3 gates: capability/drive/shell/contract suite `137 passed`; Ruff, format and mypy passed;
  `git diff --check` clean.
- Task 4 pairing matrix crosses 7 pairing states with 2 display layouts (14 generated cells).
  Unique `Fix.probe_id` pairs to a unique `Probe.probe_id` before legacy identity/equality fallback;
  duplicate explicit IDs fail closed to an unattributed/unknown receipt.
- Task 4 callback safety uses the real in-process `CockpitDriver` because `serve_stdio` correctly
  forces agent mode and cannot execute opaque callbacks. Serialized models and the receipt contain
  bounded class-only failure copy and no raw callback sentinel.
- Task 4 gates: receipt/drive/shell suite `147 passed`; Ruff, format and mypy passed;
  `git diff --check` clean.
- Task 5 parity gates: exact doctor-drive/model/contract/screen-model suite `31 passed`; full-tree
  Ruff and format passed; mypy reported no issues in 67 source files; `git diff --check` clean.
- Task 6: posted the required runbook delta; rebased onto latest `origin/main`; rewrote the one
  offending commit message without changing its tree; verified the PR history contains no
  prohibited co-author/AI trailer; pushed the rewritten history with an exact lease.
- Known-failing tests: none.
