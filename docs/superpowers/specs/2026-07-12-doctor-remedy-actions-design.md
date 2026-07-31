# Doctor remedy actions — framework design

**Status:** binding design for the shared cockpit framework
**Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`
**First consumer:** Auto-Bookkeeper #1008
**Compatibility:** additive wire/model fields; existing worker constructors remain valid

## 1. Problem

Doctor is the fleet's common diagnostic surface, but its action vocabulary is narrower than the
rest of the cockpit. A `Fix` can run an opaque callback or display a command. It cannot route the
operator into an already registered capability, even though Home needs, shelf menus and filter
results already use a single `_open_capability` chokepoint with navigation, effect classification,
agent emission and guarded writes.

The report-build failure path is similarly opaque. `_doctor` catches every exception and calls a
zero-argument `doctor_unconfigured_renderable`. The exception and its class are lost; a worker
cannot distinguish missing setup, expired auth, malformed state, unavailable source or a code bug.
The fallback is emitted as `unstructured`, so an agent is blind exactly when diagnosis matters.

After a callback runs, Doctor rebuilds the report but does not correlate the action with its
original probe. There is no stable remedy identity or structured fact saying whether the failure
resolved, stayed present, changed or became unreadable.

## 2. Goals

1. Let workers declare a registered-capability remedy without duplicating navigation.
2. Let a worker classify a report-build exception into a normal modeled probe/remedy.
3. Preserve optional focus from Home/signal routes into Doctor selection.
4. Re-probe once after an attempted remedy and emit one typed closure receipt.
5. Preserve every legacy worker and positional constructor.
6. Keep callback execution and all nested writes behind existing human/agent safety rules.

## 3. Non-goals

- No worker-specific probes, commands, error classifiers or policy live in this repository.
- No automatic diagnosis from exception strings.
- No framework-owned persistence, retry scheduler or monitoring database.
- No alternative capability router or approval gate.
- No autonomous execution of callback/local-maintenance fixes in agent mode.
- No claim that opening a capability means its domain problem was resolved; the post-action probe
  decides closure.

## 4. Compatibility strategy

`Fix` and `Probe` are imported by multiple workers and frequently constructed positionally. New
fields are appended with defaults. Existing fields keep order and meaning:

```python
@dataclass(frozen=True)
class Fix:
    title: str
    cmd: str
    note: str = ""
    run: Callable[[], str] | None = None
    confirm: bool = False
    remedy_id: str = ""
    probe_id: str = ""
    capability_key: str | None = None
    focus: str | None = None

@dataclass(frozen=True)
class Probe:
    name: str
    level: str
    detail: str
    fix: Fix | None
    probe_id: str = ""
    evidence_revision: str = ""
```

Legacy empty IDs are normalized within the Doctor snapshot to stable session-local IDs derived
from probe/fix index. They support existing display and tests, but closure verification is
`unknown` unless a worker supplies a stable `probe_id`. New worker code must use stable namespaced
IDs such as `bank.lloyds.transactions`.

`Fix.__post_init__` validates only the additive contract:

- `run` and `capability_key` are mutually exclusive;
- `focus` requires `capability_key`;
- `confirm` applies only to callback fixes;
- non-empty identity fields are trimmed and contain no whitespace/control characters; and
- a new capability fix may leave `cmd` as the human equivalent command, but `cmd` is never executed
  by the framework.

Existing display-only and callback fixes remain valid.

## 5. Action classification

```python
class DoctorActionKind(StrEnum):
    DISPLAY_ONLY = "display_only"
    CALLBACK = "callback"
    OPEN_CAPABILITY = "open_capability"

def action_kind(fix: Fix) -> DoctorActionKind:
    if fix.capability_key is not None:
        return DoctorActionKind.OPEN_CAPABILITY
    if fix.run is not None:
        return DoctorActionKind.CALLBACK
    return DoctorActionKind.DISPLAY_ONLY
```

The interactive selection includes callback and capability remedies. Display-only rows remain
visible but nonselectable. Number keys count selectable remedies in rendered order.

## 6. Host extensions

Append optional fields to `shell.Host` so all existing keyword constructors remain valid:

```python
doctor_classify_report_failure: Callable[[Exception], Probe] | None = None
doctor_on_receipt: Callable[[DoctorRemedyReceipt], None] | None = None
```

The worker classifier receives the original exception and returns one safe probe. It owns error
typing, redaction, wording and remedy. The framework never substring-matches. If the callback is
absent, the legacy `doctor_unconfigured_renderable` behavior remains for backward compatibility.

Receipt callback is best effort. The framework wraps it in `try/except`, logs safely and never
changes the Doctor screen/action outcome because observability failed.

## 7. Typed report-failure path

Add one helper used on initial build and every post-action rebuild:

```python
@dataclass(frozen=True)
class DoctorBuild:
    report: object | None
    failure_probe: Probe | None

def _build_doctor(host: Host) -> DoctorBuild:
    try:
        return DoctorBuild(host.doctor_build_report(), None)
    except Exception as exc:
        if host.doctor_classify_report_failure is None:
            raise
        return DoctorBuild(None, host.doctor_classify_report_failure(exc))
```

When classified, Doctor renders a normal `doctor` frame containing the failure probe and remedy.
It does not emit `unstructured`. A capability/callback remedy may be attempted; post-action rebuild
uses the same helper. If classification itself raises or returns an invalid probe, the framework
emits a modeled internal Doctor failure with no runnable action and safe exception class—not a
canned auth/setup instruction.

Legacy hosts without a classifier retain the current fallback so the change is additive. The
worker template demonstrates the classifier callback and modeled failure path as an opt-in example;
it remains unwired until the worker replaces the scaffold placeholder, preserving the generated
worker's documented unconfigured setup hint.

## 8. Focus threading

`_open_capability` already accepts `focus`. Its `doctor` special case currently discards it. Change:

```python
if key == "doctor":
    _doctor(host, screen, read_key, focus=focus)
```

`_doctor` selects the first actionable fix whose `probe_id == focus`, then one whose
`remedy_id == focus`; otherwise selection stays zero. Unknown focus is harmless and does not hide
other probes. Model metadata includes `focus_requested` and `focus_matched` so agents/tests can
prove routing.

**As built (QA round 5):** resolution and *actionability* turned out to be two questions, and a
two-valued matched/not-found signal answers only one — a probe rendered in the table whose only
remedy is display-only was reported as "not found" while the cursor sat on an unrelated
state-changing remedy. The decision is therefore four-valued: `matched`, `present` (rendered,
uniquely resolved, no runnable remedy — pre-selects nothing), `ambiguous` (fails closed to the
visible first row) and `unknown`. It is reported through an additive `focus_state` alongside
`focus_requested`/`focus_matched`, in both projections. See `docs/agent-screen-model.md`.

This lets a worker create a Home need with `capability_key="doctor"` and
`focus="producer:<key>"` without inventing a new capability per failure.

## 9. Capability remedy execution

Capability remedies call the one existing router:

```python
_open_capability(
    host,
    fix.capability_key,
    screen,
    read_key,
    focus=fix.focus,
    _nav=nav,
)
```

The Doctor loop receives/threads the current navigation stack just like shelf/filter opens. The
route performs the existing registry lookup, usage/audit open record, effect checks, `ScreenModel`
emission, walk gates and guarded-apply handshake. Doctor does not call `CapabilitySpec.run`
directly and does not duplicate the gate.

Unknown/unregistered keys do not fall back to `cmd` or callback. They produce an action result
`failed` with code `doctor.capability_missing`, then rebuild/re-probe.

### Agent mode

- `OPEN_CAPABILITY` is allowed. It is navigation, not approval; nested writes remain default-denied
  by the existing agent-mode gate.
- `CALLBACK` remains disabled because the callback is opaque to framework effect policy. Emit
  `skipped_agent_mode` and do not call it.
- `DISPLAY_ONLY` is not selectable.

This corrects the current over-broad “all Doctor fixes disabled in agent mode” rule without
weakening write safety.

## 10. Action result and closure receipt

```python
class DoctorActionResult(StrEnum):
    OPENED = "opened"
    RAN = "ran"
    DECLINED = "declined"
    SKIPPED_AGENT_MODE = "skipped_agent_mode"
    FAILED = "failed"

class DoctorClosure(StrEnum):
    RESOLVED = "resolved"
    STILL_PRESENT = "still_present"
    CHANGED = "changed"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class DoctorRemedyReceipt:
    schema_version: Literal[1]
    remedy_id: str
    probe_id: str
    action_kind: DoctorActionKind
    action_result: DoctorActionResult
    capability_key: str | None
    focus: str | None
    before_level: str
    before_revision: str
    after_level: str | None
    after_revision: str | None
    closure: DoctorClosure
    safe_message: str
```

No timestamp is generated in the pure receipt builder; a worker's observation callback may add its
injected clock. `safe_message` is framework-generated bounded status, never raw exception text.

### Closure algorithm

After any selected remedy returns/skips/declines/fails:

1. rebuild exactly once unless the action could not begin because the capability key is missing;
2. rebuild probes from the new report/failure;
3. find the same non-empty stable `probe_id`;
4. if absent -> `RESOLVED`;
5. if present with same level and revision -> `STILL_PRESENT`;
6. if present but level or revision differs -> `CHANGED`;
7. if identity is legacy/empty or rebuild/classification fails -> `UNKNOWN`;
8. invoke `doctor_on_receipt` once, best effort; and
9. render the rebuilt Doctor frame (or modeled failure), preserving normal interaction.

Opening a capability and returning is `OPENED`; it does not claim success. Closure derives only
from the new probe facts. A declined confirmation records `DECLINED` and may skip rebuild because
no effect occurred; closure is `STILL_PRESENT` when stable evidence is unchanged.

## 11. Rendering and ScreenModel

The existing Doctor table remains visually compact. Add machine fields to probe/fix rows:

### Probe row

- `probe_id`
- `evidence_revision`
- `level`
- `fix_id`

### Remedy row

- `remedy_id`
- `probe_id`
- `action_kind`
- `capability_key`
- `focus`
- `confirm`
- `cmd` as display/reference only

Human copy shows a capability remedy as “Open {title}” with its equivalent CLI in muted text. It
does not imply that Enter runs the CLI. Selection IDs remain `fix:<index>` for wire compatibility;
stable remedy identity is a field. Additive fields do not require a schema-version bump, but the
shape tests explicitly pin that decision.

Confirmation and result frames remain modeled. A capability remedy uses the nested capability's
native models; no intermediate unstructured frame is allowed.

## 12. Navigation and receipts sequence

```text
Doctor probe (stable ID, revision)
  -> operator/agent selects capability remedy
      -> _open_capability (existing route + effect policy)
          -> nested read/review/gate/result frames
      -> return to Doctor
      -> rebuild report/probes once
      -> compare same probe ID/revision
      -> emit DoctorRemedyReceipt
      -> render refreshed Doctor
```

Callback path replaces `_open_capability` with the existing confirmation/progress/callback result,
then follows the same rebuild/receipt sequence.

## 13. Error matrix

| Failure | Framework behavior | Receipt |
|---|---|---|
| report exception + worker classifier | render classified modeled probe | none until remedy attempt |
| report exception + no classifier | legacy fallback | none |
| classifier raises/invalid probe | modeled internal Doctor error, no action | none |
| capability key missing | no command/callback; safe result | failed/unknown |
| capability open returns normally | rebuild and compare | opened + derived closure |
| nested capability write reaches gate | existing gate decides; Doctor adds no authority | opened + derived closure |
| callback confirm cancelled | zero callback | declined/still-present |
| callback in agent mode | zero callback | skipped-agent-mode/still-present or unknown |
| callback raises | safe modeled result; rebuild | failed + derived closure |
| rebuild/classifier fails after action | modeled failure | action result + unknown |
| receipt callback raises | log and continue | receipt object was constructed once |

## 14. Security and privacy

- The worker classifier is responsible for redacting exception detail before creating a probe.
- Framework receipts contain stable IDs/classes and bounded framework messages, not raw exceptions.
- Capability remedies cannot invoke unknown commands or arbitrary imports.
- `cmd` remains presentation/equivalent CLI only; the framework never shells it.
- Callback remedies keep current agent-mode denial and confirmation semantics.
- Capability remedies inherit capability effects and the one guarded write token.
- No receipt is persisted by default; workers decide whether to emit into their existing
  observability channel.

## 15. Test strategy

### Unit

- constructor compatibility and validation;
- action-kind classification;
- focus matching;
- closure comparison and receipt shape;
- callback isolation.

### Shell integration

- typed initial/rebuild failure;
- capability route with exact focus/usage/audit;
- missing capability;
- callback confirm/run/failure/agent skip;
- receipt callback exact-once and failure isolation.

### Render/model

- same IDs/action metadata in human/model;
- selected capability remedy;
- no `unstructured` on classified failure/nested route;
- schema version remains compatible.

### Cross-worker/template

- old Host construction still imports/runs;
- generated worker accepts optional callbacks;
- a minimal worker drives Home need -> focused Doctor -> nested read-only capability -> Doctor
  receipt over `CockpitClient`.

## 16. Rollout

1. Merge framework PR after independent QA.
2. Workers opt in by bumping the pinned revision and supplying typed callbacks/IDs.
3. Auto-Bookkeeper #1008 is first; its integration fixture proves unmatched gap -> Reconcile board
   and build failure -> exact remedy.
4. Other workers remain unchanged until their next pin bump.

Rollback is a worker pin reversion. Because the API change is additive and no data migration or
framework state exists, rollback leaves no artifact to clean up.

## 17. Definition of done

Done means a worker can express “this exact probe failed; open that existing capability; after it
returns, tell me whether the probe actually cleared” through the shared human/agent code path,
without a duplicate router, unguarded write or canned failure lie.
