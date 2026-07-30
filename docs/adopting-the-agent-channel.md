# Adopting the agent channel — brownfield retrofit recipe

A worker scaffolded from `worker-template/` is born agent-navigable. This guide is for
**existing workers that predate the template** (xletter, xquill, and similar) and need
`--agent-stdio` added by hand. Follow the steps in order; each one names the exact
framework symbol it touches.

---

## Step 1 — Bump the cockpit pin

Pin `clonway-cockpit` to the current supported tag recorded in `docs/pin-sync.md`, not a
raw SHA or `main`:

```toml
# pyproject.toml
[tool.uv.sources]
clonway-cockpit = { git = "https://github.com/hearth-care/clonway-cockpit.git", rev = "v0.1.0" }
```

Then run `uv lock` and confirm the worker's own gate suite stays green. The pin in
`docs/pin-sync.md` is the single source of truth — never derive it from another worker's
`pyproject.toml` or a raw commit SHA.

---

## Step 2 — Add the CLI flags

Add `--agent-stdio` and `--allow-apply` to the root callback (the callback decorated
`@app.callback(invoke_without_command=True)` in `src/<worker>/cli/__init__.py`). The
pattern is the same in every worker; copy it exactly from
`worker-template/src/{{ package_name }}/cli/__init__.py.jinja`:

```python
@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    agent_stdio: bool = typer.Option(
        False, "--agent-stdio", help="Serve the cockpit to an agent over JSON stdin/stdout."
    ),
    allow_apply: bool = typer.Option(
        False, "--allow-apply", help="With --agent-stdio: opt into the guarded-apply handshake."
    ),
) -> None:
    if agent_stdio:
        serve_agent(allow_apply=allow_apply)
        raise typer.Exit()
    ...  # existing TTY / help path unchanged
```

Import `serve_agent` from your worker's `cli.cockpit` module (you will write it in Step 3).

---

## Step 3 — Wire `serve_agent_stdio`

Add `serve_agent` to `src/<worker>/cli/cockpit.py`. It calls `serve_agent_stdio` — the
framework-owned one-liner that forces `agent_mode=True` (dry-run) and wires the
guarded-apply handshake when `allow_apply`:

```python
import sys
from clonway_cockpit.agent import serve_agent_stdio

def serve_agent(*, stdin=sys.stdin, stdout=sys.stdout, allow_apply: bool = False) -> None:
    serve_agent_stdio(_host(agent_mode=True), stdin=stdin, stdout=stdout, allow_apply=allow_apply)
```

`_host(agent_mode=True)` is the worker's existing host factory called with the agent flag.
If `_host` already accepts `agent_mode=` as a kwarg (the template default), pass it directly.
If it does not, add it:

```python
def _host(*, agent_mode: bool = False) -> shell.Host:
    return shell.Host(
        ...
        agent_mode=agent_mode,
        ...
    )
```

### Reuse the active shell session in callbacks

This is the most common brownfield mistake: constructing another `Host` inside
`activate_pill` or `handle_extra_key`. The replacement loses the live `on_screen` observer,
guarded-apply authorization, audit sink, and agent prompt callbacks installed by
`serve_agent_stdio`. Preserving only `agent_mode` does not preserve the active session.

Use the session-aware hooks and route nested work through the supplied `ShellSession`:

```python
def activate_pill_with_session(pill, session: shell.ShellSession) -> None:
    session.open_capability("sync-status")

def handle_extra_key_with_session(
    state,
    selection,
    key,
    session: shell.ShellSession,
) -> bool:
    if key == "p":
        session.open_capability("payroll-status", focus="overdue")
        return True
    return False
```

Wire these as `Host(activate_pill_with_session=..., handle_extra_key_with_session=...)`.
The session also provides `activate_need`, `emit_model`, and `show_and_wait`. Each helper
reuses the exact active Host, screen, and key reader. The legacy callbacks remain supported
for pinned workers, but they must not reconstruct a Host; migrate a callback before it opens
nested work.

See `docs/agent-screen-model.md` → "Wiring a worker to the agent channel" for the complete
continuity contract.

### First-frame latency rule

The home screen **must emit a structured frame before any slow integration warm-up** — network
calls, credential resolution, API handshakes. An agent driving the cockpit starts a timer on
spawn; ~60 seconds of silence before the first frame is indistinguishable from a hang (this
was measured on xhr before the audit).

The rule: **defer network/credential work until after the home frame.** The home-screen
`capture_state()` must be fast and network-free; push any slow initialisation into the
walk steps or a background refresh, or emit a structured progress note (a `walk.progress`
frame) so the agent sees activity rather than silence.

If your worker calls a live API inside `capture_state()`, extract it:

```python
def capture_state() -> CockpitState:
    # fast path — return last-known state from a local cache or a stub
    return CockpitState(...)

def _on_open() -> None:
    # slow initialisation runs here, after the first home frame has been emitted
    refresh_state_from_api()
```

---

## Step 4 — Add the two contract tests

Create `tests/test_cockpit_contract.py` (or add to an existing contract test module).
Both checks are required; neither is sufficient alone.

```python
from clonway_cockpit import contract
from <worker>.cli import cockpit


def test_render_model_parity() -> None:
    """Every page-framing render_* in the worker's cockpit module has a model_* twin."""
    contract.assert_render_model_parity(cockpit)


def test_cockpit_drives_clean() -> None:
    """Driving real paths emits only structured frames — no unstructured reaches an agent."""
    host = cockpit._host(agent_mode=True)
    stream = contract.assert_drives_clean(host, ["a", "q"])  # opens shelf A, then quits
    assert stream[0].kind == "home"
```

**The key script must reach beyond the home screen.** The template's default `["q"]` is
vacuous for a worker with bespoke screens: it only proves the home screen is modelled.
Every shelf the worker exposes should appear in at least one drive script. To see what a
given run actually covered: `{m.kind for m in stream}` — inspect it and widen the key
script until every real path is reached.

Point `assert_render_model_parity` at every module that defines page-framing `render_*`
functions, not just `cli.cockpit`. If a worker has a `render.py` or a
`cli/<sub>_render.py`, pass them all:

```python
from <worker>.cli import cockpit, reports_render

def test_render_model_parity() -> None:
    contract.assert_render_model_parity([cockpit, reports_render])
```

---

## Step 5 — Add the subprocess smoke test

The contract tests above run in-process. Also add a cross-process smoke test using
`CockpitClient.spawn` — this proves the stdio channel survives a real process boundary,
which neither static check can verify:

```python
from clonway_cockpit.agent import CockpitClient


def test_agent_stdio_subprocess_smoke() -> None:
    with CockpitClient.spawn(["uv", "run", "<worker>", "--agent-stdio"], timeout=10) as c:
        home = c.read_home()
        extra = c.drain()
    # context manager calls quit() → sends {"cmd":"quit"} and waits for clean process exit

    frames = [home, *extra]
    screen_frames = [frame for frame in frames if "kind" in frame]
    assert home["kind"] == "home"
    assert home.get("schema_version") == "1.0"
    assert screen_frames, frames
    assert not any(frame["kind"] == "unstructured" for frame in screen_frames)
```

This test is the end-to-end companion: it proves the full loop (spawn → first frame →
clean exit) runs correctly, including CLI flag wiring, host construction, and the stdio
pump — things that are invisible to in-process tests. Never call `press("q")` for
shutdown: `press()` blocks waiting for the next screen frame, but a quit keypress emits
none, so it times out and raises `CockpitClosed`. Use the context manager (`__exit__`
calls `quit()`) or an explicit `c.quit()` instead. See `tests/test_worker_template.py`
for a fuller example (including preflight/result/drain assertions).

---

## Step 6 — First-frame latency: verify before shipping

Run `<worker> --agent-stdio` manually in a terminal and pipe in a quit command:

```sh
echo '{"cmd":"quit"}' | uv run <worker> --agent-stdio
```

The home frame must appear **before** the quit message arrives. If the process takes more
than a second to emit the first frame, the first-frame latency rule (Step 3) is violated —
find the slow call in `capture_state()` or `_on_open()` and defer it.

---

## Step 7 — Update the conformance tracker

After the worker's PR passes CI, update its row in the fleet conformance tracker (the
"known exceptions" column if any `allow_unstructured` paths are needed — see the next
section). The playbook's final step is always "update your row in the tracker".

---

## `unstructured` semantics — what each gate actually proves

### Static parity: the exhaustive guarantee

`assert_render_model_parity(render_ns)` is the **exhaustive** check. It walks every
`render_*` function in the given namespace(s) and, for each one whose body calls `page(...)`,
asserts a `model_*` twin exists in the same (or a separately-passed) namespace. Nothing
agent-blind can ship past it.

This is the guarantee: **if `assert_render_model_parity` is green, every page-framing screen
the worker defines has a model.**

### Drive-clean: the complementary, path-specific check

`assert_drives_clean(host, keys, *, allow_unstructured=False)` is **not exhaustive**. It
drives the cockpit headlessly through the scripted key sequence and asserts that none of the
screens it actually visits emitted as `unstructured`. It proves "the modelled screens on
this path actually emit on a real path" — the "advertised but not wired" failure that static
review structurally cannot see.

It does **not** prove every screen emits. A screen whose `model_*` twin is defined but never
wired onto any reachable path will pass `assert_drives_clean` unless the key script visits
it. Widen the key script or inspect `{m.kind for m in stream}` to widen coverage.

**Do not read a green `assert_drives_clean` as "every screen is agent-readable."** Parity is
what proves that. `assert_drives_clean` is the complementary proof that the screens it
visits actually run.

### When `allow_unstructured=True` is acceptable

`allow_unstructured=True` is a deliberate, reviewed escape hatch — not a shortcut. It
opts a specific drive path out of the unstructured assertion:

```python
# the Doctor screen when unconfigured emits an unstructured setup hint — this is
# intentional and documented: we drive through it to confirm the rest of the path
# is clean, but do not assert the Doctor hint is structured.
stream = contract.assert_drives_clean(host, ["g", "q"], allow_unstructured=True)
```

The rule: **every `allow_unstructured=True` path must be named and justified at the call
site**, and the same justification must appear in the worker repo's conformance-tracker row
("known exceptions" column). Blanket opt-outs (`allow_unstructured=True` on the main drive
path with no justification) fail the review gate.

`assert_render_model_parity`'s `allow_unmodeled` parameter is the analogous static escape
hatch:

```python
contract.assert_render_model_parity(
    cockpit,
    allow_unmodeled={"render_setup_hint"},  # intentionally unstructured; see tracker
)
```

Both escape hatches are empty by default so forgetting a model or a wiring is a hard
failure, not a silent pass.

### Current fleet adoption status

The conformance tracker records per-worker status and is the authoritative running record. Do not
copy its per-worker cells here; refresh [fleet-conformance.md](fleet-conformance.md) instead.

As of the 2026-07-03 tracker refresh, all eight fleet workers pin release tags, expose
`--agent-stdio`, and run the framework contract gate. `auto-bookkeeper` is on the accepted newer
`v0.3.0` tag; the other seven workers are on `v0.1.0`.
