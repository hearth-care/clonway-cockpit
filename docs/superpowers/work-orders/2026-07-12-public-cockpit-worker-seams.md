# Work order — Give workers stable public cockpit seams

> **For the Fleet Foundry builder:** implement this package on this branch. The framework PR is
> dependency-free. Keep every public wrapper behavior-compatible with the existing private owner,
> update `HANDOFF NOTES` after each task, and hand the exact head to independent framework and real
> Auto-Bookkeeper consumer QA.

**Job / priority:** stop worker rev bumps depending on private framework internals; P1 platform trust

**Upstream dependencies:** none

**Parallel plans:** clonway-cockpit #114 owns typed Doctor remedy actions; #115 owns menu/backspace
and Home-action parity. They are orthogonal. This PR exposes current behavior; it does not absorb
either feature.

**Downstream consumer:** Auto-Bookkeeper #1046 pins the merged SHA, migrates xbook and proves the
real nested Home/reconcile/admissions journeys.

## Operator/fleet outcome

**Trigger:** a worker bumps its pinned `clonway-cockpit` revision, opens a nested capability, emits a
model, waits on a screen, extends Home help, or owns a custom telemetry session.

**Closure:** the worker imports public, named framework contracts only. Human and agent projections,
focus/context, gates, audit, usage, crash containment, telemetry buffering and navigation remain
byte/shape compatible. New generated workers are born on the public API. Framework private helpers
may refactor without silently breaking workers.

**Durable proof:** public API behavior tests, nested event-buffer tests, generated-worker source
guard, current framework gates, and Auto-Bookkeeper #1046 exact-SHA consumer acceptance.

## Current evidence

- Framework `origin/main@8694e302` is the exact Auto-Bookkeeper pin.
- `shell.Screen`, `Host`, `run_cockpit`, `selectables` and progress functions are public, but worker
  entry/nested primitives remain private.
- Auto-Bookkeeper reaches into `shell._home`, `_activate`, `_activate_need`, `_doctor`,
  `_open_capability`, `_show`, `_safe_emit`, `_PROGRESS_TICK`; `walk._present`, `_await`, `_emit`,
  `_first_blocked_remedy`, `_PROGRESS_TICK`; `render_panels._DEFAULT_HELP_LINES`; and
  `obs._telemetry._RUN_BUFFERS`.
- xbook already carries a cross-revision try/except for `_RUN_BUFFERS`, proving the upgrade tax.
- `worker-template/.../cli/cockpit.py.jinja` still generates `shell._home` calls and wires the
  legacy `handle_extra_key(screen, read_key)` hook; its docstring tells a worker with nested
  callbacks to rebuild `_host()` with ambient agent mode. The scaffold therefore reproduces the
  exact live-session loss this package is meant to remove.
- xbook duplicates a minimal Screen adapter because no public callback-backed Screen exists.
- xbook walk-to-walk reconcile/occupancy routes now thread `ctx.on_screen`, but Home statutory and
  deferred extra-key hooks still rebuild Host and lose the live stdio observer/authorization/
  audit/prompt callbacks; session-aware hooks close that residual P1.
- Focused framework baseline: 172 passed in 0.36 seconds.

## Binding public API

### `clonway_cockpit.shell`

Add these behavior-preserving public names:

```python
PROGRESS_TICK: float

@dataclass(frozen=True, slots=True)
class CallbackScreen:
    update: Callable[[RenderableType], None]

@dataclass(frozen=True, slots=True)
class ShellSession:
    host: Host
    screen: Screen
    read_key: Callable[[], str]

    def open_capability(self, key: str, *, focus: str | None = None) -> None: ...
    def activate_need(self, item: object) -> None: ...
    def emit_model(self, model: ScreenModel) -> None: ...
    def show_and_wait(self, renderable: RenderableType) -> None: ...

def emit_model(host: Host, model: ScreenModel) -> None: ...
def show_and_wait(screen: Screen, renderable: RenderableType, read_key: Callable[[], str]) -> None: ...
def activate_need(host: Host, item: object, screen: Screen, read_key: Callable[[], str]) -> None: ...
def run_home(host: Host, screen: Screen, read_key: Callable[[], str]) -> None: ...
def activate_item(host: Host, item: tuple[str, object], state: CockpitState,
                  screen: Screen, read_key: Callable[[], str]) -> None: ...
def open_capability(host: Host, key: str, screen: Screen, read_key: Callable[[], str],
                    *, focus: str | None = None) -> None: ...
def run_doctor(host: Host, screen: Screen, read_key: Callable[[], str]) -> None: ...
```

Each calls the existing private implementation. Do not copy logic, expose `_NavStack`, weaken
exception suppression, or alter input/navigation. Existing private functions remain during the
pinned-revision migration window.

Add two optional, additive `Host` callbacks:

```python
activate_pill_with_session: Callable[[object, ShellSession], None] | None = None
handle_extra_key_with_session: Callable[
    [CockpitState, tuple[str, object] | None, str, ShellSession], bool
] | None = None
```

The shell constructs `ShellSession(host, screen, read_key)` from the active host. It prefers the
session callback when present and otherwise calls the existing legacy callback byte-for-byte. This
is the supported way a worker hook opens a nested capability without reconstructing a Host and
losing its live agent observer, dry-run/authorization, audit or agent prompt functions.

The current agent-mode pill refusal remains before either pill callback: `agent_mode=True` invokes
neither legacy nor session-aware activation and emits the existing one `Sync skipped` model. The
session pill callback is non-agent compatibility plumbing only. Agent-drivable sync needs a separate
guarded-action design and is not authorised here.

### `clonway_cockpit.walk`

Add public `PROGRESS_TICK`, `present`, `emit`, `await_key` and `first_blocked_remedy` wrappers over
the current private owners. Preserve console-vs-screen selection, best-effort agent emission,
one-key semantics, remedy ordering and all gate behavior. Private aliases remain compatible.

### `clonway_cockpit.render_panels`

Export public immutable `DEFAULT_HELP_LINES` as the canonical current tuple. Keep the private alias
for old pins; generated/new consumers use the public name.

### `clonway_cockpit.obs`

Export:

```python
@dataclass(frozen=True, slots=True)
class EventBufferScope:
    events: list[dict]
    owner: bool

@contextmanager
def event_buffer(worker_id: str) -> Iterator[EventBufferScope]: ...

@contextmanager
def isolated_event_buffers() -> Iterator[None]: ...
```

`event_buffer` binds a fresh per-worker list only when that worker has no active buffer. Nested same
worker scopes return the same list with `owner=False`; different workers share the mapping without
clobbering. The owner scope resets the ContextVar on normal return, `Exception`, `BaseException` and
cancellation. `isolated_event_buffers` temporarily binds `None` and always restores the caller's
mapping; it is the supported test-isolation seam. No caller receives the ContextVar or token.

## Compatibility matrix

| Concern | Required invariant |
|---|---|
| human screen | identical renderable sequence and blocking key behavior |
| agent screen | same `ScreenModel` sequence; observer failures stay suppressed |
| nested open | focus, capability identity, dry-run/apply authorization, audit and usage preserved |
| Home hook nested open | active Host/session observer is reused; legacy hooks remain unchanged |
| agent pulse pill | neither activation callback runs; existing one `Sync skipped` frame remains |
| crash/ShellOut | crash frame remains contained; `ShellOut` still propagates |
| Home/Doctor | selection/navigation/fixes unchanged |
| telemetry | record shape/order, reentrancy and per-worker isolation unchanged |
| generated worker | public `run_home` plus session-aware Home hook; zero named framework-private consumption |
| pinned old worker | existing private names still resolve during migration |

## Safety and effects

- API exposure only: no new provider, browser, subprocess, credential, local or external effect.
- No protocol/schema version bump: no `ScreenModel` wire field changes.
- No gate/approval/idempotency change and no new visible navigation/action; session callbacks are
  additive and inactive unless a worker opts in.
- `emit_model` remains best-effort and never lets a broken observer crash the human TUI.
- `event_buffer` owns context binding only; callers still own lifecycle event policy and flushing.
- Do not expose `_RUN_BUFFERS`, ContextVar tokens or mutable global navigation state.

## Acceptance

- [x] Public shell functions execute the same current implementation and pass behavior/mutation tests.
- [x] `CallbackScreen` forwards each renderable once and holds no additional state.
- [x] `ShellSession` uses the active Host; session-aware extra-key hooks preserve every agent field,
  legacy callbacks remain byte-identical when absent, and agent pills invoke neither callback.
- [x] Public walk functions match current private semantics; gates and animation remain unchanged.
- [x] Public help tuple is immutable/equal to the current default.
- [x] Event buffer owner/nested/cross-worker/BaseException/context-isolation matrix passes.
- [x] Obs package `__all__` pins the new public names and no private buffer.
- [x] Worker template uses `run_home` and generates/wires only
  `handle_extra_key_with_session(..., session: ShellSession)` for Home extensions. Its guidance
  directs nested work through `session.open_capability`/`activate_need`/`emit_model`/
  `show_and_wait`, never `_host()` reconstruction; rendered-worker tests prove the active Host is
  retained and a dynamic source guard rejects named framework-private consumption.
- [x] #114/#115 diffs rebase without ownership conflict.
- [ ] Auto-Bookkeeper #1046 pins the merged SHA and its full public-consumer guard passes.
- [x] Framework full pytest, ruff, format, mypy, pre-commit and diff gates pass.

Auto-Bookkeeper #1046 is explicitly deferred: it must pin this PR's eventual merge SHA and run its
real consumer acceptance after #116 passes independent QA and merges. This branch made no xbook edit.

## Out of scope

- changing shell behavior, navigation, menu tokens, Doctor actions or Home actions;
- redesigning the walk gate/model protocol;
- migrating xbook on this framework branch;
- removing private aliases before all pinned workers migrate;
- generic removal of every underscore inside framework implementation/tests; and
- domain writes, live provider acceptance or deployment.

## HANDOFF NOTES

- Phase: framework implementation Tasks 0–7 complete; independent QA is next.
- Base: `origin/main@8694e302`; branch is zero behind.
- Baseline: 172 focused framework tests passed in 0.54 seconds.
- Parallel state: #114 and #115 remain open code-bearing, orthogonal PRs; no planned public seam
  has landed independently.
- Inventory: the generated template retains the two expected `shell._home` calls; #1046 remains a
  draft at `0580b8593` and still owns the downstream public-API migration.
- RED/GREEN proof: public import RED `c81a392`; shell GREEN `8aea291`; walk/help GREEN `963a3e3`;
  telemetry GREEN `75d7dc2`; template guard RED `6225ac0`; template GREEN `a2b6527`;
  compatibility/rehearsal `25bb002`.
- Final base/gates: `origin/main@8694e302`, zero behind; focused 172 passed in 0.42s; full 1169
  passed in 21.42s; ruff, format, mypy, all-file pre-commit and diff checks passed.
- Downstream rehearsal: a non-editable wheel from framework `a2b6527` imported every public seam
  and instantiated the callback/buffer types from a clean xbook #1046 checkout at `0580b8593`.
  This is not downstream acceptance; exact merge-SHA pinning remains deferred to #1046.
- Package: 856 artifact lines and 82 explicit implementation/acceptance gates; 1,122 current tests,
  all-file pre-commit and diff checks pass.
- Independent plan QA: two read-only reviewers approved after the generated Home hook/session
  continuity and agent-pill refusal boundaries were made explicit.
- Downstream: Auto-Bookkeeper #1046; root pins the final merged SHA there.
- Value state: blueprint only until framework build/QA/merge and real worker pin/acceptance.
