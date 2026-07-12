# Doctor remedy actions — Foundry readiness receipt

- **Repository:** `hearth-care/clonway-cockpit`
- **Branch:** `Codex/doctor-remedy-actions-plan`
- **Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`
- **Mode:** new doc-only framework foundation, personally SOL-authored
- **Verdict:** dispatchable after publication; no implementation dependency

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

`RUNBOOK DELTA: none` — shared framework API; consumer documents operator-visible change.
