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

- Current phase: Task 4 complete.
- Next concrete step: Task 5 projection-parity and real agent-drive tests, followed by ScreenModel
  and worker-facing protocol documentation.
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
- Current-main deviation: the plan named a generated-worker test file that is not present; the
  canonical worker-template subprocess suite is used instead.
- Known-failing tests: none.
- Base inspected: `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`.
- Initial baseline: 1,122 passed in 40.61 seconds; committed publication baseline: 1,122 passed in
  35.58 seconds.
- First consumer: Auto-Bookkeeper #1008; it is blocked on this PR and must pin the merged framework
  revision.
- No current framework PR exposes this seam; this package is the sole proposed owner.
- No code, worker state or external system was mutated during authoring.
- `RUNBOOK DELTA: none` — framework contract only; consuming workers document their operator copy.
