# Doctor remedy actions — Fleet Foundry implementation plan

> **Builder instruction:** execute in order on this PR branch. Every task starts with the named RED
> test and ends with focused GREEN plus a commit. Preserve all existing positional constructors and
> do not add worker/domain imports to the framework.

**Goal:** let Doctor classify report failures, open existing capabilities with focus and verify the
same probe after a remedy, identically for human and agent drivers.

**Architecture:** extend the framework's existing `Probe`/`Fix`/`Host` contracts additively;
capability remedies delegate to `_open_capability`; callback safety remains; one pure comparison
builds a typed receipt delivered through an optional worker callback.

**Binding design:**
`docs/superpowers/specs/2026-07-12-doctor-remedy-actions-design.md`

**Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`

## Execution rules

- Keep `Fix` first five and `Probe` first four positional fields unchanged.
- Do not infer worker failure class or redact worker exceptions in framework code.
- Do not execute `Fix.cmd`; it remains presentation/equivalent CLI.
- Do not add a second capability router, navigation stack, effect policy or approval gate.
- Capability remedies must call `_open_capability` exactly once.
- Agent mode may navigate capability remedies; arbitrary callbacks remain disabled.
- Use deterministic injected models; no clock, filesystem or network in receipt comparison.
- Every new page-framing render has a `model_*` twin and a real-path drive.
- Update `HANDOFF NOTES` in the work order with each commit/gate.

---

## Task 1 — add backward-compatible action and receipt contracts

**Files:**

- Modify: `src/clonway_cockpit/doctor.py`
- Modify: `src/clonway_cockpit/__init__.py` only for intentional exports
- Modify: `tests/test_doctor.py`
- Create: `tests/test_doctor_receipt.py`

### Step 1.1 — RED: legacy and new constructor matrix

Write tests proving:

- `Fix("title", "cmd")`, all existing five-position forms and
  `Probe("name", "ok", "detail", None)` retain equal field values;
- legacy display/callback fixes classify as `DISPLAY_ONLY`/`CALLBACK`;
- a capability fix classifies as `OPEN_CAPABILITY`;
- `run` plus `capability_key` rejects;
- `focus` without capability rejects;
- `confirm` on capability/display-only rejects for newly identified fixes while legacy behavior is
  documented/kept where required by existing tests;
- whitespace/control-only IDs/keys reject;
- frozen models cannot mutate; and
- enum serialized values exactly match the design.

Run:

```bash
uv run pytest -q tests/test_doctor.py tests/test_doctor_receipt.py
```

Expected RED: additive fields/types do not exist.

### Step 1.2 — GREEN: implement additive models

Append fields after existing ones. Add:

- `DoctorActionKind`;
- `DoctorActionResult`;
- `DoctorClosure`;
- `DoctorRemedyReceipt`;
- `action_kind(fix)`; and
- normalization/validation helpers.

Do not change shell/render code yet. `fixes_for()` and `verdict()` remain byte-for-byte behaviorally
compatible.

### Step 1.3 — RED/GREEN: pure closure comparison

In `tests/test_doctor_receipt.py`, build probes with stable IDs/revisions and assert:

- absent after probe -> resolved;
- same ID/level/revision -> still present;
- same ID with different level or revision -> changed;
- empty/legacy ID -> unknown;
- rebuild unavailable -> unknown;
- receipt includes exact action kind/result/capability/focus/before/after; and
- `safe_message` is bounded and never accepts raw exception text.

Implement a pure `build_remedy_receipt(...)`. No datetime or I/O.

### Step 1.4 — gates and commit

```bash
uv run pytest -q tests/test_doctor.py tests/test_doctor_receipt.py
uv run ruff check src/clonway_cockpit/doctor.py tests/test_doctor.py tests/test_doctor_receipt.py
uv run mypy src/clonway_cockpit/doctor.py
```

Commit:

```text
feat(doctor): define typed remedy actions and receipts
```

---

## Task 2 — classify report-build failures and thread Doctor focus

**Files:**

- Modify: `src/clonway_cockpit/shell.py`
- Modify: `src/clonway_cockpit/doctor.py`
- Modify: `src/clonway_cockpit/render_models.py`
- Modify: `src/clonway_cockpit/render_panels.py`
- Modify: `tests/test_shell.py`
- Modify: `tests/test_model.py`
- Modify: `tests/test_screen_models_rest.py` if the shape pin lives there
- Modify: `worker-template/{{project_slug}}/...` Host wiring only where required
- Modify: generated-worker snapshot tests as required

### Step 2.1 — RED: typed failure path

Add shell tests where `doctor_build_report` raises a worker-defined exception and
`doctor_classify_report_failure` returns a probe with stable ID/remedy. Assert:

- classifier receives the same exception object once;
- Doctor emits a `doctor` model, never `unstructured`;
- human/model contain the same probe/remedy/action fields;
- the worker remedy, not generic unconfigured copy, is visible;
- classifier missing retains legacy fallback unchanged;
- classifier raising/returning invalid data yields one modeled internal Doctor failure with no
  runnable remedy; and
- the same behavior applies on initial build and post-action rebuild.

Run:

```bash
uv run pytest -q tests/test_shell.py -k 'doctor and (failure or unconfigured)'
```

Expected RED: Host has no classifier and exceptions become unstructured fallback.

### Step 2.2 — GREEN: optional Host callback and build helper

Append optional callbacks to `Host` with defaults so existing workers compile unchanged. Add one
private `_build_doctor` helper used by initial/rebuild paths. Do not duplicate try/except branches.

Classified failures become an ordinary one-probe Doctor snapshot. Legacy fallback exists only when
the callback is absent. Sanitize framework-internal classifier-failure copy to exception class.

### Step 2.3 — RED: focus from capability open

Write tests:

- `_open_capability(..., key="doctor", focus="probe.b")` passes focus to `_doctor`;
- matching `probe_id` selects its actionable remedy;
- remedy-ID fallback matches when probe ID does not;
- unknown focus selects first runnable without hiding rows;
- model metadata contains requested/matched values; and
- Home Need activation with `capability_key="doctor"`/focus drives this same path.

Expected RED: current special case discards focus.

### Step 2.4 — GREEN: thread/select focus

Add optional `focus` to `_doctor`, preserve through rebuilds and selection. Reuse the current
selection IDs; expose stable identity in fields/meta. Do not add another entry point.

### Step 2.5 — gates and commit

```bash
uv run pytest -q tests/test_shell.py tests/test_model.py tests/test_screen_models_rest.py
uv run pytest -q tests/test_worker_template.py tests/test_generated_worker.py
```

Use actual generated-worker test filenames found in the repo; record the mapping if names differ.

Commit:

```text
feat(doctor): classify build failures and honor focus
```

---

## Task 3 — route capability remedies through the existing chokepoint

**Files:**

- Modify: `src/clonway_cockpit/shell.py`
- Modify: `src/clonway_cockpit/render_models.py`
- Modify: `src/clonway_cockpit/render_panels.py`
- Modify: `tests/test_shell.py`
- Modify: `tests/test_contract.py`
- Create: `tests/test_doctor_capability_action.py`

### Step 3.1 — RED: selection/action kinds

Build a Doctor fixture with display-only, callback and capability fixes. Assert:

- display-only is visible/nonselectable;
- callback and capability remedies are selectable in probe order;
- arrow/number selection aligns with rendered rows;
- model remedy fields include action kind, remedy/probe IDs, capability/focus and confirm; and
- invalid/unknown capability cannot run `cmd` or a fallback callback.

Expected RED: only `run is not None` is selectable.

### Step 3.2 — RED: exact capability route

Register a pure test capability with focus-aware walk handler. Enter the Doctor capability remedy
and assert:

- `_open_capability` path records one normal open usage/audit event;
- handler receives exact focus;
- nested Rich/model frames emit;
- returning re-enters Doctor;
- no callback/command execution occurred; and
- unknown key yields a safe modeled result.

Spy at public seams, not by checking implementation line calls only.

### Step 3.3 — GREEN: implement capability action

Refactor `_run_doctor_fix` into an action executor that can return a typed result. For
`OPEN_CAPABILITY`, call `_open_capability` with the existing host/screen/read-key/navigation stack.
Do not call `spec.run` directly. Keep the current callback confirmation/progress/result behavior.

### Step 3.4 — RED/GREEN: agent-mode safety

Using `CockpitClient`/`serve_stdio`, prove:

- capability remedy opens in agent mode and emits structured nested frames;
- a nested reversible read route succeeds;
- a nested write route reaches the existing `walk.gate` and defaults to decline;
- a callback remedy emits `skipped_agent_mode` and callback call count remains zero; and
- no `unstructured` frame appears.

Do not create a Doctor-specific apply handshake.

### Step 3.5 — gates and commit

```bash
uv run pytest -q tests/test_doctor_capability_action.py tests/test_shell.py tests/test_contract.py
uv run ruff check src/clonway_cockpit/shell.py src/clonway_cockpit/doctor.py tests/test_doctor_capability_action.py
uv run mypy src/clonway_cockpit/shell.py src/clonway_cockpit/doctor.py
```

Commit:

```text
feat(doctor): open capability remedies through the shell
```

---

## Task 4 — verify the probe and emit exactly one receipt

**Files:**

- Modify: `src/clonway_cockpit/shell.py`
- Modify: `src/clonway_cockpit/doctor.py`
- Modify: `tests/test_doctor_receipt.py`
- Modify: `tests/test_shell.py`
- Create: `tests/test_doctor_receipt_integration.py`

### Step 4.1 — RED: before/action/after matrix

Parameterize public-path tests across:

- callback ran and probe resolved;
- capability opened and probe resolved;
- capability opened and same probe/revision remains;
- same probe changes level/revision;
- confirmation declined;
- callback skipped in agent mode;
- callback failed;
- capability missing;
- rebuild fails/classification succeeds;
- rebuild/classification itself fails; and
- legacy empty IDs.

Assert exact action result, closure, before/after fields, capability/focus and one callback call.
Assert rebuild count: once after attempted action, zero only for a documented zero-effect decline
where existing facts are reused.

Expected RED: no receipt/correlation callback.

### Step 4.2 — GREEN: orchestration and callback

Carry the selected fix and originating probe together; do not recover the relationship by string
or list index after execution. Execute, rebuild, compare and call `doctor_on_receipt` exactly once.

Wrap receipt callback failure. Log only receipt IDs/result/closure and exception class; never raw
worker probe detail.

### Step 4.3 — RED/GREEN: race and repeat

Prove:

- a changed probe revision is `CHANGED`, not resolved;
- a second user attempt emits a second receipt tied to the new before revision;
- one action cannot emit two receipts because nested capability emits frames;
- selection remains valid if the remedy disappears after rebuild; and
- report rebuild happens after nested capability returns, not before.

### Step 4.4 — gates and commit

```bash
uv run pytest -q tests/test_doctor_receipt.py tests/test_doctor_receipt_integration.py tests/test_shell.py
```

Commit:

```text
feat(doctor): verify remedies and emit closure receipts
```

---

## Task 5 — prove one Rich/ScreenModel/agent contract

**Files:**

- Modify: `src/clonway_cockpit/render_models.py`
- Modify: `src/clonway_cockpit/render_panels.py`
- Modify: `tests/test_model.py`
- Modify: `tests/test_contract.py`
- Modify: `tests/test_screen_models_rest.py`
- Create: `tests/test_doctor_drive.py`
- Modify: `docs/agent-screen-model.md`

### Step 5.1 — RED: projection parity

Create one mixed Doctor snapshot and assert Rich/model semantic parity for:

- every probe and remedy in order;
- selected remedy;
- action kind and stable IDs;
- capability/focus;
- confirmation/display-only state;
- warning/error verdict; and
- requested/matched Doctor focus.

If the contract helper compares semantic fields rather than text, extend the smallest shared seam.
Do not add string-scraping tests.

### Step 5.2 — RED: real agent drive

Drive:

```text
Home need focused on probe X
  -> Doctor frame selected on X capability remedy
  -> Enter
  -> nested capability model(s)
  -> Back/return
  -> refreshed Doctor
  -> receipt callback observed once
```

Assert `kind`, stable row IDs/fields/meta and gate status. Reject any `unstructured` frame.

### Step 5.3 — GREEN: render/model/docs

Add compact human copy and additive model fields. Document:

- worker construction of stable IDs/revisions;
- display vs callback vs capability remedies;
- focus routing;
- agent-mode behavior; and
- receipt callback responsibility/redaction.

Do not document Auto-Bookkeeper-specific examples as framework requirements; one clearly labelled
example may use generic `reconcile` names.

### Step 5.4 — gates and commit

```bash
uv run pytest -q tests/test_doctor_drive.py tests/test_model.py tests/test_contract.py tests/test_screen_models_rest.py
```

Commit:

```text
test(doctor): prove human and agent remedy parity
```

---

## Task 6 — template compatibility, full gates and release handoff

**Files:**

- Modify: worker-template Host wiring/tests only if optional fields require explicit examples
- Modify: `docs/onboarding-a-worker.md` if Doctor callbacks are part of worker adoption
- Modify: `docs/superpowers/work-orders/2026-07-12-doctor-remedy-actions.md`
- Modify: `docs/findings/2026-07-12-doctor-remedy-actions-readiness.md`

### Step 6.1 — generated-worker compatibility

Regenerate the worker fixture using the repo's canonical command/test. Prove:

- existing template without optional callbacks starts and drives unchanged;
- opt-in classifier/receipt callback type-checks;
- protocol version remains unchanged because fields are additive; and
- every generated Doctor failure page has a model twin.

Do not hand-edit generated golden output without running the generator.

### Step 6.2 — full verification

From a clean worktree run:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pre-commit run --all-files
git diff --check
```

Record exact counts/duration. Then run a subprocess `CockpitClient` acceptance drive for both:

- legacy worker fallback; and
- opt-in focused capability remedy + receipt.

### Step 6.3 — consumer handoff

In the PR body/readiness receipt record:

- final public imports/fields;
- merge commit/release revision once merged;
- compatibility decision and protocol version;
- exact worker pin-bump steps;
- Auto-Bookkeeper #1008 as first consumer; and
- no worker may copy `_doctor` or bypass `_open_capability` while waiting.

### Step 6.4 — independent QA

QA rejects if:

- legacy worker construction breaks;
- classified report failure becomes `unstructured`;
- a capability remedy calls `spec.run` directly;
- agent mode runs an arbitrary callback;
- nested writes bypass the existing gate;
- opening a capability is claimed resolved without re-probe;
- raw exception text enters a receipt/model; or
- receipt callback failure crashes/changes Doctor.

Commit:

```text
docs(doctor): record framework remedy handoff
```

---

## Final completion checklist

- [x] Existing `Fix`/`Probe` positional calls remain green.
- [x] Action-kind validation is strict and additive.
- [x] Worker classifier renders modeled report failures.
- [x] Legacy unconfigured fallback remains when classifier absent.
- [x] Doctor focus threads from a normal capability open.
- [x] Capability remedies use `_open_capability` once with exact focus.
- [x] Display-only fixes stay nonselectable.
- [x] Callbacks preserve confirmation/progress and agent denial.
- [x] Nested write routes preserve the one guarded-apply gate.
- [x] Stable before/after probe comparison produces one typed receipt.
- [x] Receipt callback failure is isolated.
- [x] Rich/model/agent projections share action/identity metadata.
- [x] No real path emits `unstructured` for classified failure/remedy navigation.
- [x] Generated workers and old Host constructions remain compatible.
- [x] Protocol version decision is explicitly tested/documented.
- [x] Full pytest/static/pre-commit/diff gates pass.
- [x] Consumer pin-bump/public contract handoff is recorded.

Completion is the public-path agent/human drive and receipt proof, not merely new dataclass fields.

## HANDOFF NOTES

- Current phase: QA FAIL round 6 (all three findings) is fixed; the full local gate sequence is
  green at the code head.
- Next concrete step: repeat the complete gate sequence at the documentation head, post the
  runbook delta, verify a clean synchronized worktree, then execute the finish protocol.
- Decisions: focus resolves probe identity against the full probe snapshot, where exactly one
  matching probe may own one or many remedies; the first matching runnable remedy is selected.
  Duplicate probe IDs and duplicate remedy IDs remain fail-closed.
- QA focus matrix:
  `tests/test_doctor_capability_action.py::test_doctor_preserves_selected_remedy_identity_across_rebuild_matrix`
  crosses selection source (`focused`, `manual`) with rebuild shape (`unchanged`,
  `predecessor_removed`, `predecessor_inserted`, `reordered`, `target_removed`) for 10 cells.
- Task 2 verification: focused matrix `11 passed`; shell/capability/model suite `145 passed`;
  canonical generated-worker suite `26 passed`; Ruff passed; mypy passed; `git diff --check` clean.
- Task 3 verification: real `CockpitClient` throwing-capability drive passed; complete
  capability/drive/shell/contract suite `137 passed`; Ruff and format passed; mypy passed;
  `git diff --check` clean. Framework-owned crash copy is capability title plus exception class;
  raw worker/provider exception text is absent from Rich, model frames, and receipts.
- Task 4 pairing matrix:
  `tests/test_doctor_receipt_integration.py::test_doctor_remedy_pairing_state_matrix` crosses pairing
  (`same_object`, `equal_clone`, `stable_id_clone`, `shared_equal_values`, `unpaired`,
  `reordered_subset`, `ambiguous_duplicate_id`) with display layout (`absent`, `interleaved`) for
  14 cells. Unique explicit probe ID wins; duplicate explicit IDs fail closed; legacy
  identity/equality is consume-on-match fallback.
- Task 4 verification: pairing matrix `14 passed`; callback/capability redaction focused set
  `15 passed`; receipt/drive/shell suite `147 passed`; Ruff and format passed; mypy passed;
  `git diff --check` clean. A real `CockpitDriver` serialization proves raw callback exception text
  is absent while `serve_stdio` remains unable to execute opaque callbacks by design.
- Task 5 verification: exact doctor-drive/model/contract/screen-model suite `31 passed`; full-tree
  Ruff passed; Ruff format reported `167 files already formatted`; mypy reported no issues in
  67 source files; `git diff --check` clean.
- Task 6 change management: posted the required `RUNBOOK DELTA` on
  `hearth-care/auto-orchestrator#196` with Doctor selection/action/focus/re-probe behavior, safety
  boundaries, and the disappeared/ambiguous-target recovery step.
- Task 6 history: rebased onto latest `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`,
  removed the prohibited co-author trailer while preserving the commit tree, verified no
  `Co-Authored-By`/AI trailer remains, and force-pushed with an exact lease.
- Task 6 final gates: full suite `1,213 passed in 26.27s`; Ruff passed; Ruff format reported
  `167 files already formatted`; mypy reported no issues in 67 source files; all eight pre-commit
  hooks passed; `git diff --check` clean; generated-worker suite `26 passed`; subprocess
  legacy/opt-in acceptance `2 passed, 4 deselected in 10.47s`.
- Known-failing tests: none.
- Current-main deviation: the plan named `tests/test_generated_worker.py`, which does not exist;
  `tests/test_worker_template.py` remains the canonical generated-worker suite.
- Pending QA findings: none; exact-receipt-head gate repeat and finish protocol remain.
- QA FAIL round 3 focus matrix:
  `tests/test_doctor_capability_action.py::test_doctor_preserves_selected_remedy_identity_across_rebuild_matrix`
  crosses selection source (`focused`, `manual`), focus identity (`unique_probe_id`,
  `duplicate_probe_id`, `unique_remedy_id`, `duplicate_remedy_id`, `unknown`) and rebuild shape
  (`unchanged`, `predecessor_removed`, `predecessor_inserted`, `reordered`, `target_removed`) for
  50 generated cells. A shared `_unique_match` now governs all Doctor stable-identity resolvers;
  ambiguous focus claims fail closed to `focus_matched=None` and the visible first-row fallback.
- QA FAIL round 3 Task 2 verification: focus matrix `50 passed`; Ruff passed; mypy reported no
  issues in `shell.py`; `git diff --check` clean.
- QA FAIL round 3 receipt matrix:
  `tests/test_doctor_receipt_integration.py::test_doctor_remedy_pairing_state_matrix` crosses
  before pairing (`same_object`, `equal_clone`, `stable_id_clone`, `shared_equal_values`,
  `unpaired`, `reordered_subset`, `ambiguous_duplicate_id`), after identity (`unique`, `absent`,
  `duplicate_id`, `duplicate_id_reversed`) and display layout (`absent`, `interleaved`) for 56
  generated cells. Duplicate after IDs always produce `unknown` with empty after fields regardless
  of order; absent unique IDs remain `resolved`; legacy consume-on-match pairing remains supported.
- QA FAIL round 3 Task 4 verification: receipt matrix `56 passed`; Ruff passed; mypy reported no
  issues in `shell.py`; `git diff --check` clean.
- QA FAIL round 3 Task 5 parity: the Rich projection now renders either
  `focus ✓ <stable-id> matched` or `focus ⚠ <stable-id> not found — review selection`, matching the
  model's `focus_requested`/`focus_matched` decision. The existing mixed-snapshot test crosses
  matched/unmatched focus for 2 generated cells.
- QA FAIL round 3 Task 5 verification: Doctor drive/model/contract/screen-model suite `32 passed`;
  Ruff passed; mypy reported no issues in `render_panels.py`; `git diff --check` clean.
- QA FAIL round 3 Task 6 compatibility: generated workers leave the generic classifier example
  unwired, preserving the documented unconfigured setup hint until a worker deliberately adopts a
  typed/redacted taxonomy. The generated-worker helper now copies current worktree template bytes,
  so pre-commit RED/GREEN changes are exercised rather than silently generating from `HEAD`.
- QA FAIL round 3 Task 6 verification: generated-worker suite `27 passed`; focused classifier/setup
  drive `2 passed, 25 deselected`; `git diff --check` clean.
- QA FAIL round 3 final gates: rebased onto latest
  `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`; full suite `1,297 passed in
  21.74s`; Ruff passed; Ruff format reported `167 files already formatted`; mypy reported no issues
  in 67 source files; all eight pre-commit hooks passed; `git diff --check` clean;
  generated-worker suite `27 passed`; subprocess legacy/opt-in acceptance `2 passed, 5 deselected
  in 10.56s`; no prohibited commit trailers; remote divergence `0 0`.
- QA FAIL round 3 known-failing tests: none.
- QA FAIL round 4 Task 2 RED: adding `multiple_remedies_one_probe` to the focus matrix produced
  10 failures: focused entry executed row 1 instead of the focused probe, and focused/manual paths
  both reported `focus_matched=None`.
- QA FAIL round 4 Task 2 matrix:
  `tests/test_doctor_capability_action.py::test_doctor_preserves_selected_remedy_identity_across_rebuild_matrix`
  crosses selection source (`focused`, `manual`), focus identity (`unique_probe_id`,
  `multiple_remedies_one_probe`, `duplicate_probe_id`, `unique_remedy_id`,
  `duplicate_remedy_id`, `unknown`) and rebuild shape (`unchanged`, `predecessor_removed`,
  `predecessor_inserted`, `reordered`, `target_removed`) for 60 generated cells. The duplicate
  probe case now creates two actual probes with the same ID, rather than conflating that ambiguity
  with two remedies legitimately declaring one probe ID.
- QA FAIL round 4 Task 2 GREEN: `_focused_remedy` resolves a unique probe from the full probe
  snapshot, then takes that probe's first runnable remedy. Remedy-ID focus still requires one unique
  remedy. The Rich/ScreenModel projection matrix includes the one-probe/two-remedy matched case.
- QA FAIL round 4 Task 2 verification: focused matrix plus projection `63 passed`; full
  shell/model/screen-model/capability/drive phase `203 passed in 11.58s`; canonical generated-worker
  suite `27 passed in 9.52s`; Ruff passed; mypy reported no issues in `shell.py`;
  `git diff --check` clean.
- QA FAIL round 4 Task 4 RED:
  `tests/test_doctor_receipt_integration.py::test_doctor_remedy_cardinality_pairing_matrix`
  produced `38 failed, 70 passed`. Valid later remedies lost attribution, while an unresolved
  explicit ID could borrow an unrelated probe through legacy identity fallback.
- QA FAIL round 4 Task 4 matrix crosses probe cardinality (`missing`, `unique`, `duplicate`),
  remedy cardinality (`1`, `2`, `3`), selected row (`first`, `middle`, `last`), remedy order
  (`natural`, `reversed`) and display layout (`absent`, `interleaved`) for 108 generated cells.
- QA FAIL round 4 Task 4 GREEN: `_runnable_remedies` was rewritten into two cardinality modes.
  Explicit IDs resolve uniquely against the full probe snapshot without consumption, supporting
  1:N remedies; missing/duplicate IDs never use fallback. Only fixes without a declared probe ID
  use the shrinking legacy identity/equality pool.
- QA FAIL round 4 Task 4 verification: cardinality matrix `108 passed`; complete
  receipt/receipt-integration/shell/capability phase `359 passed in 0.52s`; Ruff passed; Ruff format
  reported 2 files already formatted; mypy reported no issues in `shell.py`; `git diff --check`
  clean.
- QA FAIL round 4 known-failing tests: none.
- QA FAIL round 4 rebase: fetched current `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`;
  the branch was already based on it, and the required force-with-lease push was a no-op.
- QA FAIL round 4 code-head full gates: `uv run pytest -q` -> `1416 passed in 22.65s`;
  `uv run ruff check .` -> all checks passed; `uv run ruff format --check .` -> 167 files already
  formatted; `uv run mypy src` -> no issues in 67 source files; all eight all-file pre-commit hooks
  passed; canonical generated-worker suite -> `27 passed in 7.68s`; subprocess legacy/opt-in
  acceptance -> `2 passed, 6 deselected in 10.56s`; `git diff --check` and
  `git status --porcelain` clean.
- QA FAIL round 4 history: no prohibited co-author/AI trailers; remote divergence `0 0`;
  `origin/main` is an ancestor of the code head.
- QA FAIL round 4 change management: no operator commands, provisioning, sign-offs or recurring
  operating steps changed; the existing runbook delta already covers focused selection and
  re-probe behavior, so no additional runbook comment is required.
- QA FAIL round 5 finding 1 RED: a new
  `tests/test_doctor_capability_action.py::test_doctor_focus_verdict_matrix` crossing focus target
  (11 shapes) x target position (`first`, `last`) x entry (`direct`, `capability_open`) for 44
  generated cells produced `44 failed` — every cell, because the verdict had no state to assert
  and three shapes reported a rendered probe as "not found".
- QA FAIL round 5 finding 1 GREEN: the focus decision is four-valued
  (`clonway_cockpit.doctor.DoctorFocusState`: `matched` / `present` / `ambiguous` / `unknown`).
  `_focused_remedy` now searches the full probe snapshot AND the full fix list — display-only
  fixes are rendered as `fix:display:<i>` and are therefore addressable — and returns a
  `_FocusDecision`. `present` (uniquely resolved, rendered, no runnable remedy) pre-selects NO
  row: the first arrow/Enter reveals the fallback cursor without running it, so a single Enter can
  never run an unrelated state-changing remedy. `ambiguous` keeps the documented visible first-row
  fallback but no longer borrows the "not found" copy. The verdict reaches both projections
  through the new additive `meta.focus_state` and the Rich `focus` line; `focus_matched` stays
  strictly "the selection is what you asked for", so it is non-null exactly when the state is
  `matched`. Protocol `schema_version` is unchanged (purely additive).
- QA FAIL round 5 deviation from the suggested regression test: QA proposed a
  `focus_target_runnability` axis inside the existing 60-cell rebuild matrix. Crossing runnability
  with `focus_identity` generates contradictory cells (`duplicate_probe_id` x `no_fix`), so the
  verdict lives in its own 44-cell matrix instead, and the existing rebuild matrix gained a
  `focus_state` assertion plus the previously-skipped `target_removed` selection assertion.
  Verdict-after-rebuild is covered separately by
  `test_focus_verdict_stays_honest_across_a_rebuild` (after shape x selection source, 8 cells).
- QA FAIL round 5 nits, all four closed: falsy focus (`""`) normalises to "no focus" at the
  `_doctor` entry instead of matching every legacy probe's empty `probe_id`; a failed
  post-rebuild identity resolve falls back to row 1 rather than the stale numeric index (and the
  `target_removed` cell now asserts it); the mis-named
  `test_unknown_focus_keeps_first_remedy_selected_after_rebuild` is now
  `test_unknown_focus_starts_on_first_remedy_then_follows_its_identity`; and
  `test_doctor_remedy_cardinality_pairing_matrix` gained the after-side identity axis
  (`changed`, `same`, `absent`, `duplicate_id`), taking it from 108 to 432 cells.
- QA FAIL round 5 known-failing tests: none.
- QA FAIL round 5 rebase: `origin/main` had moved from `8694e30` to `00b6641` (PR #116, the stable
  public shell/walk seams). Rebased all 28 commits onto it. One content conflict, in the `Host`
  dataclass: both PRs append optional fields. Resolved by keeping #116's session callbacks in
  place and appending the two Doctor callbacks after them — appending rather than inserting is
  what preserves a pinned worker's positional `Host(...)` binding, so #116's
  `test_session_callbacks_are_appended_to_preserve_host_positional_order` was widened from "these
  two are last" to "this is the tail order, and nothing was inserted ahead of `audit_worker`".
  #116's public `open_capability`/`run_doctor` seams delegate to the private
  `_open_capability`/`_doctor` this PR changed, so the focus verdict reaches the public seam with
  no second code path.
- QA FAIL round 6 diagnosis: all three findings were one class —
  `doctor-remedy-state-coherence`. Doctor derived "which remedy is armed", "where did the focus
  resolve" and "which probe owns this remedy" in more than one place, so a frame could claim one
  thing while ⏎ did another. Fixed as one rewrite of the derivation, not three patches.
- QA FAIL round 6 finding 1 GREEN: `selection_visible` was computed only inside the
  `focus_pending` branch, so it went stale on rebuild. It is now DERIVED every frame from the
  current focus decision (`explicit_selection or decision.row is not None or
  decision.fallback_selection`). `explicit_selection` is the one override and is cleared at every
  rebuild — an operator's choice is authoritative only under the snapshot it was made in, so a
  remedy that turns its own probe present-but-not-actionable re-hides the cursor instead of
  leaving an unrelated state-changing remedy one ⏎ away. A digit key now also moves `sel`, so the
  numbered choice and the cursor never disagree.
- QA FAIL round 6 finding 2 GREEN: resolution and selection are separated with ONE derivation.
  `_FocusDecision` carries the resolution (`state`, `row`); `_FocusDecision.matched_identity(sel)`
  is the projected `focus_matched` and returns the identity only when the cursor is on the
  resolved row. A new additive `meta.focus_row` publishes where the focus resolved, so
  "matched but the cursor moved" is navigable rather than merely reported. The Rich line paints
  the same fact: `✓ <id> matched` on the row, `⚠ <id> matched — cursor on row N` off it.
  `docs/agent-screen-model.md` now documents `focus_state` as the RESOLUTION verdict and
  `focus_matched` as the selection-match fact, and states that only `focus_matched` licenses ⏎.
- QA FAIL round 6 finding 3 GREEN: `model_doctor` kept a second, object-identity-only probe→remedy
  relation. Both projections and the dispatch list now read one `doctor.pair_remedies` result,
  which returns an ordered `DoctorRemedyRow(fix, probe, probe_index, row_id, kind, run_index)` for
  EVERY rendered fix (display-only included, so probes carrying one keep their link).
  `doctor.probe_fix_links` resolves a probe's `fix_id` by object identity first, then through that
  pairing — which is what keeps the link alive for a stable-ID clone — and omits the link entirely
  when the identity is claimed by more than one probe.
- QA FAIL round 6 recurrence matrix:
  `tests/test_doctor_capability_action.py::test_doctor_remedy_state_coherence_matrix` crosses
  focus shape (`matched_runnable`, `present_display_only`, `present_no_fix`, `ambiguous`,
  `unknown`) x cursor action (`none`, `up`, `down`, `digit`) x remedy pairing (`same_object`,
  `stable_id_clone`, `unpaired_global`) for 60 generated cells. Every cell asserts the Rich ❯
  cursor, `selection`, `focus_state`, `focus_row`, `focus_matched`, the probe `fix_id` links and
  which callback ran, on the same frame. The focus target is deliberately never row 1, so "the
  focus selected this" cannot be confused with the fail-closed first-row fallback.
- QA FAIL round 6 targeted matrices: `test_moving_the_cursor_off_a_focused_remedy_stops_claiming_a_match`
  crosses focus identity (`unique_probe_id`, `one_probe_many_remedies`, `unique_remedy_id`) x
  movement (`up`, `down`) for 6 no-action cells; `test_modeled_probe_fix_link_uses_the_dispatch_pairing`
  crosses pairing (`same_object`, `equal_clone`, `stable_id_clone`, `shared_equal_values`,
  `unpaired`, `ambiguous_duplicate_id`) x display layout (`absent`, `interleaved`) for 12 cells;
  `test_focus_verdict_stays_honest_across_a_rebuild` crosses after-shape (`recovered_no_fix`,
  `display_only`, `absent`, `duplicated`, `still_runnable`) x selection provenance
  (`focused_enter`, `manual_arrow`, `manual_digit`) for 15 cells, each driving one extra ⏎ after
  the rebuild and asserting zero further callbacks in the `present` cells.
- QA FAIL round 6 corrected false-green expectations: the 60-cell rebuild matrix's 15
  manual-selection cells asserted `focus_matched` while `selection` named another remedy — they
  now assert `focus_state`/`focus_row` survive and `focus_matched` is `None`. The 8-cell rebuild
  verdict test asserted a selected row for its `present` cells; it is now 15 cells and asserts no
  cursor and no callback there.
- QA FAIL round 6 mutation proof (the matrices are adversarial, not merely green): reverting the
  visibility derivation reddens 24 of the 60 coherence cells and 6 rebuild cells; a cursor-blind
  `focus_matched` reddens 9 coherence cells and all 6 cursor cells; an object-identity-only probe
  link reddens 20 coherence cells and 6 pairing cells.
- QA FAIL round 6 known-failing tests: none.
