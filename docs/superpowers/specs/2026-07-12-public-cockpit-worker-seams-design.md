# Stable public cockpit worker seams — design

## 1. Problem and product boundary

The framework already owns the worker shell, walk machine, screen protocol and telemetry buffering,
but several operations a real worker must perform are available only as underscore names. A worker
therefore chooses between private coupling and copying framework-shaped adapters.

```text
Today
worker -> shell._open_capability / walk._emit / obs._RUN_BUFFERS
       -> private implementation detail changes break a pinned-rev bump

Target
worker -> public stable wrapper -> one existing private implementation
       -> framework can refactor internals; behavior and worker contract stay pinned
```

This PR exposes existing behavior plus one additive active-session hook seam. It does not change
default product behavior or the wire protocol and does not migrate a worker. Auto-Bookkeeper #1046
is the first real consumer and acceptance owner.

## 2. Why the fix belongs here

Putting aliases in xbook would merely create a local compatibility facade over private framework
names. The worker template itself emits `shell._home`, so every new worker inherits the defect. A
single framework API must serve xbook, current siblings and generated workers.

The two current framework plans are separate:

- #114 adds typed Doctor actions;
- #115 changes root/menu input and Home-action facts;
- this PR exposes stable entry/projection/buffer primitives without changing any of those behaviors.

All three can branch from `8694e302`; builders rebase and resolve only additive import/test adjacency.

## 3. API design principles

1. Public wrappers are thin and named for behavior, not current implementation.
2. Private owners remain the single implementation during migration.
3. No public function accepts a private type (`_NavStack`, ContextVar token).
4. `ScreenModel` and Rich remain two projections of the same path.
5. Compatibility is behavioral and failure-path based, not merely “the symbol imports”.
6. Public telemetry binding exposes scoped events/ownership, never the ContextVar.
7. Tests and worker templates dogfood public names; private-unit tests may still exercise internals.

## 4. Public shell contract

### 4.1 Callback-backed screen

```python
@dataclass(frozen=True, slots=True)
class CallbackScreen:
    update: Callable[[RenderableType], None]
```

`CallbackScreen(present)` is the supported adapter from a walk's `ctx.present` callable to
`shell.Screen`. It calls the callback exactly once per `update`, returns its result unchanged
(`None` by protocol), carries no observer, key or model state, and does not catch callback errors.
The caller separately threads `on_screen`; this prevents the adapter becoming a second agent path.

### 4.2 Active shell session

Worker Home hooks currently receive `screen/read_key` but not the active Host. Xbook's statutory
`p` and deferred Enter routes therefore rebuild `_host()`: they preserve ambient `agent_mode` but
lose the observer, authorization callback, audit sink and agent prompt functions installed by
`serve_stdio`. Public function names alone do not close that P1.

```python
@dataclass(frozen=True, slots=True)
class ShellSession:
    host: Host
    screen: Screen
    read_key: Callable[[], str]

    def open_capability(self, key: str, *, focus: str | None = None) -> None:
        open_capability(self.host, key, self.screen, self.read_key, focus=focus)

    def activate_need(self, item: object) -> None:
        activate_need(self.host, item, self.screen, self.read_key)

    def emit_model(self, model: ScreenModel) -> None:
        emit_model(self.host, model)

    def show_and_wait(self, renderable: RenderableType) -> None:
        show_and_wait(self.screen, renderable, self.read_key)
```

`Host` gains two default-`None` callbacks:

```python
activate_pill_with_session: Callable[[object, ShellSession], None] | None = None
handle_extra_key_with_session: Callable[
    [CockpitState, tuple[str, object] | None, str, ShellSession], bool
] | None = None
```

At the current pill and extra-key dispatch points, create one `ShellSession` from the exact active
`host/screen/read_key`. Prefer the session callback when non-`None`; otherwise call the legacy
`activate_pill`/`handle_extra_key` with the exact current arguments. Do not arity-inspect callbacks,
mutate/replace the Host, or use a global/current-host ContextVar. This keeps every existing worker
byte-compatible and makes observer/authorization continuity explicit for new consumers.

Preserve the existing ordering in `_activate`: `host.agent_mode` refuses a pulse pill and emits one
`Sync skipped` model before any activation callback. Only a non-agent pill can reach
`activate_pill_with_session`/legacy `activate_pill`. The session hook must not become a back door to
network/browser/credential effects; agent sync is a separate guarded-action problem.

### 4.3 Public wrapper mapping

| Public symbol | Current owner | Binding behavior |
|---|---|---|
| `PROGRESS_TICK` | `_PROGRESS_TICK` | same float identity/value |
| `emit_model` | `_safe_emit` | best-effort `host.on_screen`; suppress observer failure |
| `show_and_wait` | `_show` | update once, then read one key |
| `activate_need` | `_activate_need` | same capability/focus dispatch and no-op rows |
| `run_home` | `_home` | same redraw/navigation/input loop |
| `activate_item` | `_activate` | same selected item dispatch |
| `open_capability` | `_open_capability` | same usage/audit/ctx/gate/focus/crash/ShellOut path |
| `run_doctor` | `_doctor` | same report/fix/confirm/rebuild loop |

Wrappers have explicit signatures and docstrings. They call private owners at runtime rather than
assigning a one-time alias, so a test monkeypatch or future internal replacement remains observable.
`open_capability` deliberately omits `_nav`: programmatic worker/nested opens do not own the shell's
private back-stack. Shell internals continue calling `_open_capability(..., _nav=...)`.

### 4.4 Mutation proof

Public tests must fail if a wrapper:

- constructs its own Host/context;
- drops `focus`, `on_screen`, `agent_mode`, `authorize_apply`, audit or usage;
- catches `ShellOut`;
- reconstructs/replaces the Host inside a `ShellSession` method;
- calls a legacy hook when the corresponding session hook exists, or vice versa;
- invokes either pill callback under `agent_mode=True` or changes the one refusal frame;
- lets a crashing observer escape;
- skips the human key wait; or
- bypasses the current private owner.

At least `open_capability`, `emit_model` and `show_and_wait` get direct behavioral tests rather than
only monkeypatch-delegation tests because they define the human/agent/safety boundary.

## 5. Public walk contract

Expose:

```python
PROGRESS_TICK = _PROGRESS_TICK

def present(ctx: WizardContext, renderable: RenderableType) -> None:
    return _present(ctx, renderable)

def emit(ctx: WizardContext, model: ScreenModel) -> None:
    return _emit(ctx, model)

def await_key(ctx: WizardContext) -> None:
    return _await(ctx)

def first_blocked_remedy(preconditions: list[Precondition]) -> Remedy | None:
    return _first_blocked_remedy(preconditions)
```

Use the exact current accepted types after Task 1 inspects definitions; the signatures above are
semantic, not permission to widen/narrow existing inputs. The wrappers preserve:

- `present`: `ctx.present`/screen first, console fallback;
- `emit`: no-op without observer and best-effort observer failure containment;
- `await_key`: no read when `read_key is None`, one read otherwise;
- remedy selection: current first actionable blocked precondition ordering; and
- progress constant: unchanged animation cadence.

`confirm_apply`, `animate_*`, public walk data classes and model protocol are untouched.

## 6. Public help-line constant

`DEFAULT_HELP_LINES` is the same immutable tuple object/value used by framework render/model code.
Keep `_DEFAULT_HELP_LINES` as compatibility alias. Worker extension is tuple concatenation:

```python
HELP_LINES = DEFAULT_HELP_LINES + (("z", "defer selected Needs ..."),)
```

No consumer imports `_FilterRow` or other render internals under this contract.

## 7. Scoped telemetry buffer contract

### 7.1 Shape

```python
@dataclass(frozen=True, slots=True)
class EventBufferScope:
    events: list[dict]
    owner: bool
```

The list is intentionally mutable: `make_obs().event` appends to the exact per-worker list. The
scope object cannot be rebound/mutated, and exposes no ContextVar/token/mapping.

### 7.2 `event_buffer(worker_id)` state machine

```text
no mapping / worker absent
    -> copy current mapping
    -> bind worker -> fresh []
    -> yield owner=True, events=fresh list
    -> always reset token on exit

same worker already active
    -> yield owner=False, same events object
    -> do not bind/reset

different worker active
    -> preserve existing entry and bind fresh list for requested worker
    -> owner=True only for requested worker
    -> reset restores exact prior mapping
```

Reject blank/non-string `worker_id` with `ValueError` before binding. Reset happens for normal exit,
`Exception`, `KeyboardInterrupt`, `SystemExit` and cancellation because the owner uses `finally`.
The context does not emit lifecycle records or flush; the worker's session policy still does that.

### 7.3 `isolated_event_buffers()`

Bind `_RUN_BUFFERS=None`, yield, reset the token in `finally`. This is a supported test isolation
seam only; it does not clear another context or mutate the underlying mapping. Nested isolation
restores each prior value exactly.

### 7.4 Obs export contract

`clonway_cockpit.obs.__all__` gains exactly `EventBufferScope`, `event_buffer` and
`isolated_event_buffers`. `_RUN_BUFFERS` remains private and absent. Existing exports remain.

## 8. Worker-template contract

The template must dogfood both halves of the public contract. Replace both generated
`shell._home(host, ...)` calls with `shell.run_home(host, ...)`, and replace the generated legacy
Home hook with:

```python
from clonway_cockpit.shell import ShellSession

def handle_extra_key_with_session(
    state: CockpitState,
    selection: tuple[str, object] | None,
    key: str,
    session: ShellSession,
) -> bool:
    """Return True only when this worker handled key for an owned row."""
    return False
```

Wire it as `Host(handle_extra_key_with_session=home_hooks.handle_extra_key_with_session)`. Do not
also generate or wire `handle_extra_key`; the Host's existing legacy default preserves framework
compatibility, while a newly scaffolded worker has one unambiguous safe extension path. Update the
template module/host guidance to tell implementers to use `session.open_capability`,
`session.activate_need`, `session.emit_model` and `session.show_and_wait` for nested work. Delete the
current advice to call `_host()` with ambient agent mode: reconstructing a Host is forbidden because
it drops the exact active observer, apply authorization, audit sink and agent prompt callbacks.

Rendered-template tests must import the hook, assert its four-argument session signature, prove
`cockpit._host().handle_extra_key_with_session is home_hooks.handle_extra_key_with_session`, prove
the legacy `handle_extra_key` field stays at its framework default, and drive a sentinel session
through the generated no-op without rebuilding a Host. The generated README names the
session-aware hook and its safe nested helpers.

Add a template source test that renders/scans production files and rejects:

```text
shell._home/_activate/_activate_need/_doctor/_open_capability/_show/_safe_emit/_PROGRESS_TICK
walk._present/_await/_emit/_first_blocked_remedy/_PROGRESS_TICK
render_panels._DEFAULT_HELP_LINES
obs._telemetry._RUN_BUFFERS
```

The guard is not a blanket underscore ban: worker domain modules and legitimate test-only private
seams are outside. It catches framework-private consumption in generated production Python/Jinja.
It also rejects `_host()` calls or ambient-agent-mode guidance inside generated Home hooks, so the
public symbol migration cannot leave the session-continuity bug in the scaffold.

## 9. Cross-repo consumption contract

After this framework PR merges, Auto-Bookkeeper #1046:

- pins the exact merge SHA in `pyproject.toml`/`uv.lock` in one commit;
- imports shell/walk/help/obs public contracts only;
- replaces both copied `_PresentScreenAdapter` classes with `CallbackScreen`;
- keeps current explicit `ctx.on_screen` forwarding for every nested walk;
- switches Home extra-key nested routes to session-aware Host callbacks, proving the active stdio
  observer/authorization/audit/prompt functions survive; non-agent connect-pill code may adopt the
  session callback, while agent pills retain the pre-callback refusal;
- revalidates already-fixed nested agent visibility and batch stale-abort truth; and
- adds an AST/import guard so the private dependency cannot regrow.

#1041/#1042 then revalidate their final public `walk.show`/nested context result contracts against
the merged #1046 pin. They do not own or copy the framework change.

## 10. Failure, effect and compatibility boundaries

- No provider/config/state/accounting effect.
- No protocol version change or serialization change.
- No new visible navigation, action, key, gate or receipt; session callbacks are opt-in plumbing.
- Observer failure remains fail-open for human TUI; callback-screen render failure is not swallowed.
- Telemetry buffer reset never flushes/drops itself; owner worker decides flush after scope exit.
- Existing private symbols remain for older pinned workers and framework internal tests.
- `make_obs` behavior/wire output remains byte-identical.
- The framework PR cannot claim user value until xbook pins and drives the real consumer.

## 11. Verification topology

Focused framework baseline:

```bash
uv run pytest -q \
  tests/test_shell.py tests/test_walk.py tests/test_obs.py tests/test_obs_package.py \
  tests/test_render_facade.py tests/test_contract.py tests/test_agent_driver.py \
  tests/test_agent_dry_run.py tests/test_agent_hardening.py
```

Authoring result: 172 passed in 0.36 seconds.

Implementation adds public API, event-buffer and template guard tests, then runs full framework
pytest/ruff/format/mypy/pre-commit/diff. Consumer acceptance runs from #1046 after an exact SHA pin;
never use an editable local framework path as merge proof.

## 12. Non-goals

- removing all framework-private implementation/tests;
- redesigning xbook's custom lifecycle policy;
- merging #114/#115;
- changing callbacks from synchronous to async;
- exposing navigation stack or raw ContextVar operations; and
- using public aliases as license for another worker-local framework copy.
