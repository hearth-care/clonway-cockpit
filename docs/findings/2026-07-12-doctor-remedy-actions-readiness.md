# Doctor remedy actions — Foundry implementation receipt

- **Repository:** `hearth-care/clonway-cockpit`
- **PR:** #114
- **Branch:** `Codex/doctor-remedy-actions-plan`
- **Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`
- **Mode:** implemented additive framework foundation
- **Verdict:** implementation complete; ready for independent QA

## Artifact set

- `docs/superpowers/work-orders/2026-07-12-doctor-remedy-actions.md`
- `docs/superpowers/specs/2026-07-12-doctor-remedy-actions-design.md`
- `docs/superpowers/plans/2026-07-12-doctor-remedy-actions.md`
- `docs/findings/2026-07-12-doctor-remedy-actions-readiness.md`

## Current-source receipt

Inspection of pinned/current framework proves:

- `Fix` has only opaque `run` callback or display-only behavior;
- `_doctor` selects only fixes where `run is not None`;
- all callbacks are skipped in agent mode, even when the intended action is safe navigation;
- the `doctor` special case discards `_open_capability` focus;
- report-build exceptions lose the exception and emit a worker's generic unconfigured renderable;
- that fallback is sent to agents as `unstructured`;
- post-fix rebuild has no stable before/after probe correlation or receipt; and
- `_open_capability` already provides the correct navigation, usage/audit, effect, model and
  guarded-write chokepoint to reuse.

Auto-Bookkeeper current production-shaped evidence shows why the seam matters: the same unmatched-
lines condition routes directly from Home to a focused Reconcile board, but Doctor can only display
a list command. No open clonway-cockpit PR currently owns Doctor capability remedies.

## Scope boundary

| Owner | Contract |
|---|---|
| this framework PR | typed action kinds/IDs, classifier callback, focus, capability routing, closure receipt, model parity |
| Auto-Bookkeeper #1008 | xbook failure taxonomy, probes, exact remedies, lock/feed/gap/auth behavior, obs emission |
| each nested capability | its domain read/review/write journey and guarded apply |
| consuming worker | exception redaction and receipt persistence/emission policy |

The framework does not know Xero, bank feeds, reconciliation, accounting health or worker commands.

## HR0-HR11 audit

| Rule | Result | Evidence |
|---|:---:|---|
| HR0 | PASS | author/build/QA/consumer-pin phases separate |
| HR1 | PASS | framework docs plus consumer runbook boundary explicit |
| HR2 | PASS | focused/full/static/pre-commit/diff/generated-worker gates |
| HR3 | PASS | current framework gaps map to public types/shell/render/tests |
| HR4 | PASS | build/classifier/key/callback/rebuild/receipt failures enumerated |
| HR5 | PASS | display/callback/capability, focus, agent, decline and closure boundaries exact |
| HR6 | PASS | one `_open_capability`, one gate, one Doctor loop, one receipt comparator |
| HR7 | PASS | generated-worker and CockpitClient production paths required |
| HR8 | PASS | exact classifier/router/rebuild/callback counts and zero command execution |
| HR9 | PASS | need focus -> Doctor -> nested capability -> re-probe -> receipt driven |
| HR10 | PASS | public enums/dataclasses/Host callbacks and compatibility named |
| HR11 | PASS | real consumer #1008 and pinned revision handoff explicit |

## Adversarial rejection checklist

- [x] A worker-local duplicate Doctor loop is rejected.
- [x] Executing the display `cmd` string is rejected.
- [x] Calling `CapabilitySpec.run` outside `_open_capability` is rejected.
- [x] Treating navigation as proof of closure is rejected.
- [x] Allowing arbitrary callbacks in agent mode is rejected.
- [x] Adding a Doctor-specific write gate is rejected.
- [x] Raw exception text in framework receipt/model is rejected.
- [x] Breaking positional worker constructors is rejected.
- [x] Classified failure emitted as `unstructured` is rejected.
- [x] Receipt callback failure changing product behavior is rejected.
- [x] Tests that never drive the real shell/agent channel are rejected.

## Baseline and publication gate

- Clean base `uv run pytest -q`: 1,122 passed in 40.61 seconds.
- Committed publication head `uv run pytest -q`: 1,122 passed in 35.58 seconds.
- No baseline skip, expected failure or warning was reported.
- Authoring changes are Markdown only.
- Final all-file pre-commit passed, including Ruff, Ruff format and mypy.

## Dispatch verdict

The package is narrow enough for one framework build but complete enough to prevent worker-local
workarounds. Its six-task plan fixes the type contract, interactive shell, agent behavior, closure
receipt and generated-worker compatibility as one coherent public seam. Auto-Bookkeeper #1008 can
then pin the merged revision and implement only domain diagnosis/remedies.

`RUNBOOK DELTA` posted on `hearth-care/auto-orchestrator#196`: Doctor remedies are now
numbered/selectable, focused selection follows stable remedy identity through rebuilds, capability
actions retain the guarded-write route, attempted actions re-probe and emit one receipt, and
operators must review a refreshed selection when the target disappears or identity is ambiguous.

## Implemented public contract

The public import surface is `clonway_cockpit.doctor`:

- `DoctorActionKind`, `DoctorActionResult`, `DoctorClosure`;
- frozen `Fix`, `Probe`, and `DoctorRemedyReceipt`;
- `action_kind(fix)` and `build_remedy_receipt(...)`.

`Fix` appends `remedy_id`, `probe_id`, `capability_key`, and `focus`; `Probe` appends
`probe_id` and `evidence_revision`. `shell.Host` appends optional
`doctor_classify_report_failure` and `doctor_on_receipt` callbacks. Existing positional
constructors and hosts without either callback remain supported.

Doctor capability remedies delegate to the existing `_open_capability` route and preserve its
usage, audit, effect, agent model, and guarded-write behavior. Callback remedies remain disabled
in agent mode. Report classifier and receipt observer failures are isolated and do not expose raw
exception text through framework-generated receipt copy.

ScreenModel fields are additive, so the wire protocol remains `schema_version = "1.0"`. Doctor
probe/remedy rows now carry stable identity/action fields; metadata carries requested/matched
focus. Human, in-process agent, `serve_stdio`, and true subprocess `CockpitClient` drives cover the
same route.

## Consumer pin handoff

After this PR is merged and included in a release tag, Auto-Bookkeeper #1008 (and later workers)
should:

1. update its `clonway-cockpit` `rev` to that release tag and run `uv lock`;
2. add stable probe/remedy IDs and evidence revisions;
3. express navigable remedies with an already registered `capability_key` and optional `focus`;
4. wire a redacting `doctor_classify_report_failure` and best-effort `doctor_on_receipt`;
5. run its render/model parity, clean-drive, focused Doctor route, and full local gates; and
6. avoid copying `_doctor`, executing `Fix.cmd`, calling `CapabilitySpec.run` directly, or adding
   another write gate while waiting for the release.

The exact merge commit and release tag do not exist before operator merge/release and must be
filled in by the release owner. No data migration or operator cutover step is introduced.

## Final local verification

- `uv run pytest -q`: 1,171 passed in 39.43 seconds.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 167 files already formatted.
- `uv run mypy src`: success, no issues in 67 source files.
- `uv run pre-commit run --all-files`: all eight hooks passed.
- `git diff --check`: clean.
- Generated-worker suite: 26 passed.
- True subprocess `CockpitClient` legacy/opt-in acceptance: 2 passed.
