# M2 (framework) — `agent.serve_stdio` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `agent.serve_stdio(host)` — a line-delimited JSON pump over stdin/stdout that lets a separate agent process launch and drive the real cockpit, recording `ScreenModel` snapshots — with the framework hard-enforcing dry-run (the write gate never posts in agent mode).

**Architecture:** `serve_stdio` is a thin wrapper over the existing `shell.run_cockpit(host, read_key=…, screen=…)` core — no new loop. It binds an `on_screen` observer that writes `ScreenModel.to_dict()` as JSON to stdout, a `read_key` that blocks on stdin and parses one JSON message per call (`{"key":…}` / `{"cmd":"snapshot"|"quit"}`), and the existing `_NullScreen`. A new `Host.agent_mode` flag is threaded into each walk's `WizardContext.dry_run` at the open-capability chokepoint; `walk.confirm_apply` honours `dry_run` by always declining. Under piped (non-tty) stdin `keys.raw_mode()`/`keys.pending()` are no-ops, so the loop emits one frame per draw before each blocking read — a clean request/response cadence.

**Tech Stack:** Python ≥3.12, stdlib `json`/`sys`/`io`, frozen dataclasses, Rich (unaffected). Gates: `make check` = `ruff check .` + `ruff format --check .` + `mypy src` + `pytest -q`.

**Repo gotchas (carry forward):**
- A **ruff autofix-on-save hook strips unused imports** — add an import only in the same edit that uses it (write the using-code in the same Edit). `agent.py` needs new `import json` + `import sys`; add them together with `serve_stdio`'s body.
- `mypy src` is enforced; keep new fields/params annotated. New dataclass fields must be defaulted (frozen dataclasses, backward-compat).
- Don't modify `tests/test_walk.py` / `tests/test_shell.py` / `tests/test_render_primitives.py` / `tests/test_screen_models*.py` (byte-identical / golden guards). New tests go in new files.
- In `serve_stdio`, read with `stdin.readline()` in a `while` loop (NOT `for line in stdin`) — `readline()` doesn't read-ahead-buffer, so it stays correct for an interactive pipe; `""` means EOF.

---

## File Structure

- **Modify `src/clonway_cockpit/registry.py`** — add `WizardContext.dry_run: bool = False`.
- **Modify `src/clonway_cockpit/shell.py`** — add `Host.agent_mode: bool = False`; thread `dry_run=host.agent_mode` into the walk ctx in `_open_capability`.
- **Modify `src/clonway_cockpit/walk.py`** — `confirm_apply` honours `ctx.dry_run`.
- **Modify `src/clonway_cockpit/agent.py`** — add `serve_stdio(host, *, stdin=sys.stdin, stdout=sys.stdout)` (+ `import json`, `import sys`).
- **Create `tests/test_agent_dry_run.py`** — dry-run gate unit + plumbing-via-CockpitDriver tests.
- **Create `tests/test_serve_stdio.py`** — round-trip, snapshot/quit, protocol errors, EOF, and the gate-safety integration test.
- **Modify `docs/agent-screen-model.md`** — document the stdio protocol + dry-run.

---

## Task 1: Dry-run plumbing (Host.agent_mode → WizardContext.dry_run → confirm_apply)

**Files:**
- Modify: `src/clonway_cockpit/registry.py` (WizardContext)
- Modify: `src/clonway_cockpit/shell.py` (Host, `_open_capability`)
- Modify: `src/clonway_cockpit/walk.py` (`confirm_apply`)
- Test: `tests/test_agent_dry_run.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/test_agent_dry_run.py`:

```python
"""The framework-enforced agent dry-run write gate (M2).

In agent mode, walk.confirm_apply must ALWAYS decline — an agent can press the apply
key and see it refused, but no walk ever posts. The flag rides WizardContext.dry_run,
threaded from Host.agent_mode at the shell's open-capability chokepoint.
"""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import walk
from clonway_cockpit.registry import WizardContext


def _ctx(*, dry_run: bool, key: str) -> WizardContext:
    return WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        read_key=lambda: key,
        dry_run=dry_run,
    )


def test_confirm_apply_declines_in_dry_run_even_on_apply_key():
    for key in ("a", "A", "enter"):
        assert walk.confirm_apply(_ctx(dry_run=True, key=key), equivalent_cli="x") is False


def test_confirm_apply_applies_normally_when_not_dry_run():
    assert walk.confirm_apply(_ctx(dry_run=False, key="a"), equivalent_cli="x") is True
    assert walk.confirm_apply(_ctx(dry_run=False, key="n"), equivalent_cli="x") is False
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_agent_dry_run.py -q`
Expected: FAIL — `TypeError: WizardContext.__init__() got an unexpected keyword argument 'dry_run'`

- [ ] **Step 3: Add `WizardContext.dry_run`**

In `src/clonway_cockpit/registry.py`, append a field to `WizardContext` after `on_screen` (keep it last, defaulted):

```python
    # Optional observer the cockpit threads in so a walk's screens are emitted as
    # ScreenModels (for the agent driver). None = not emitting (console/test callers).
    on_screen: Callable[[ScreenModel], None] | None = None
    # Agent dry-run: when True, the write gate (walk.confirm_apply) ALWAYS declines,
    # so an agent driving over stdio (Host.agent_mode) can walk any flow end-to-end
    # and see the review/blast-radius but never posts. Default False = unchanged.
    dry_run: bool = False
```

- [ ] **Step 4: Honour `dry_run` in `confirm_apply`**

In `src/clonway_cockpit/walk.py`, change `confirm_apply` to read the key (cadence preserved) then decline in dry-run:

```python
def confirm_apply(ctx: WizardContext, *, prompt: str = "", equivalent_cli: str) -> bool:
    """The single write gate. The chip is drawn inside the review screen, so this
    only reads the gate key. The ONLY place a walk may post to Xero.

    ``equivalent_cli`` is kept in the signature for API stability even though the
    review screen renders it. In agent mode (``ctx.dry_run``) the gate reads the key
    so the stdio cadence stays one-message-per-screen, then ALWAYS declines — an
    agent can drive any walk end-to-end but never posts."""
    if ctx.read_key is not None:
        k = ctx.read_key()
        if ctx.dry_run:
            return False
        return k in (keys.ENTER, "a", "A")
    return ctx.confirm_fn(prompt)
```

- [ ] **Step 5: Run the unit test green**

Run: `uv run pytest tests/test_agent_dry_run.py -q`
Expected: PASS (2 tests)

- [ ] **Step 6: Add `Host.agent_mode` and thread it into the walk ctx**

In `src/clonway_cockpit/shell.py`, add a field to the `Host` dataclass immediately after `on_screen` (the last field):

```python
    on_screen: Callable[[ScreenModel], None] = field(default=lambda model: None)
    # When True (set by agent.serve_stdio), the shell threads dry_run=True into every
    # walk's WizardContext so confirm_apply declines — an agent driving the real
    # cockpit can never post. Default False = the live human cockpit is unchanged.
    agent_mode: bool = False
```

Then in `_open_capability`, extend the existing ctx replace:

```python
        ctx = host.build_walk_ctx(screen, read_key, focus=focus)
        ctx = replace(ctx, on_screen=host.on_screen, dry_run=host.agent_mode)
```

- [ ] **Step 7: Write the failing plumbing test (driven via CockpitDriver)**

Append to `tests/test_agent_dry_run.py` (function-local imports dodge the ruff import-strip):

```python
def test_agent_mode_threads_dry_run_into_a_driven_walk():
    from clonway_cockpit import render, shell, usage
    from clonway_cockpit.agent import CockpitDriver
    from clonway_cockpit.registry import (
        BlastRadius,
        CapabilitySpec,
        clear_capabilities,
        register_capability,
    )
    from clonway_cockpit.state import CockpitState
    from clonway_cockpit.walk import confirm_apply

    posted: list[bool] = []

    def handler(ctx) -> None:  # a walk that "posts" only if the gate confirms
        if confirm_apply(ctx, equivalent_cli="xbook bills"):
            posted.append(True)

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="xbook bills",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
        )
    )
    state = CockpitState(tenant_name="Clonway")

    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    host = shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=build_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
        agent_mode=True,  # <-- the dry-run switch
    )
    # Open shelf C (single spec → opens directly into the handler); the handler hits
    # the gate, presses "a", but dry_run declines → never posts. "q" quits.
    CockpitDriver(host, keys=["c", "a", "q"]).run()
    clear_capabilities()
    assert posted == [], "agent-mode walk posted despite dry-run"
```

- [ ] **Step 8: Run it green**

Run: `uv run pytest tests/test_agent_dry_run.py -q`
Expected: PASS (3 tests). If it errors building the Host (missing `agent_mode`), the Step 6 field wasn't added.

- [ ] **Step 9: Commit**

```bash
git add src/clonway_cockpit/registry.py src/clonway_cockpit/walk.py src/clonway_cockpit/shell.py tests/test_agent_dry_run.py
git commit -m "feat(agent): framework-enforced dry-run gate — Host.agent_mode → ctx.dry_run → confirm_apply declines"
```

---

## Task 2: `serve_stdio` core — keys in, models out, EOF→quit

**Files:**
- Modify: `src/clonway_cockpit/agent.py`
- Test: `tests/test_serve_stdio.py`

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/test_serve_stdio.py`:

```python
"""The subprocess stdio JSON protocol (M2): agent.serve_stdio drives the real cockpit
over line-delimited JSON. Tested in-process with io pipes (serve_stdio takes a Python
host; an OS subprocess spawn is a consumer concern)."""

from __future__ import annotations

import io
import json

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.registry import (
    CapabilitySpec,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, Pill


def _host(state: CockpitState, **over) -> shell.Host:
    base = dict(
        capture_state=lambda: state,
        build_walk_ctx=lambda *a, **k: None,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )
    base.update(over)
    return shell.Host(**base)


def _drive(host: shell.Host, messages: list[dict]) -> list[dict]:
    """Feed JSON messages on stdin, return the parsed JSON frames written to stdout."""
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_serve_stdio_emits_home_then_quits():
    state = CockpitState(tenant_name="Clonway", pills=(Pill("Xero", "synced", "06:45", "ok", "xero"),))
    frames = _drive(_host(state), [{"key": "q"}])
    assert frames, "no frames emitted"
    assert frames[0]["kind"] == "home"


def test_serve_stdio_drives_into_a_shelf_menu():
    clear_capabilities()
    register_capability(
        CapabilitySpec(key="a1", shelf="C", title="Cap one", summary="s", equivalent_cli="x")
    )
    register_capability(
        CapabilitySpec(key="a2", shelf="C", title="Cap two", summary="s", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    # Shelf C has two specs → a shelf_menu; open C, then quit out.
    frames = _drive(_host(state), [{"key": "c"}, {"key": "q"}, {"key": "q"}])
    clear_capabilities()
    kinds = [f["kind"] for f in frames]
    assert "home" in kinds and "shelf_menu" in kinds, kinds
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_serve_stdio.py -q`
Expected: FAIL — `ImportError: cannot import name 'serve_stdio' from 'clonway_cockpit.agent'`

- [ ] **Step 3: Implement `serve_stdio` core**

In `src/clonway_cockpit/agent.py`, add the imports (in the same edit as the body, so ruff keeps them) and the function. Change the import block top:

```python
from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import replace
```

Then append at the end of the file:

```python
def serve_stdio(host: shell.Host, *, stdin=sys.stdin, stdout=sys.stdout) -> None:  # noqa: ANN001
    """Drive the real cockpit over line-delimited JSON on stdin/stdout — the
    subprocess transport an external agent process uses to launch + drive the
    cockpit. A thin pump over ``shell.run_cockpit``: each draw writes the screen's
    ``ScreenModel.to_dict()`` as a JSON line to stdout; each loop ``read_key`` blocks
    reading one JSON message from stdin. Runs in agent mode (``Host.agent_mode``), so
    every walk's write gate is dry-run — the agent can drive any flow but never posts.

    Protocol (one JSON object per line):
      agent -> app : {"key": "<k>"} | {"cmd": "snapshot"} | {"cmd": "quit"}
      app -> agent : <ScreenModel.to_dict()>  |  {"error": "<reason>"}
    Stdin EOF unwinds the cockpit (treated as quit)."""
    last: list[ScreenModel | None] = [None]

    def _write(obj: dict) -> None:
        stdout.write(json.dumps(obj) + "\n")
        stdout.flush()

    def on_screen(model: ScreenModel) -> None:
        last[0] = model
        _write(model.to_dict())

    def read_key() -> str:
        while True:
            raw = stdin.readline()
            if raw == "":  # EOF → unwind the cockpit
                return "q"
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except (ValueError, TypeError):
                _write({"error": "invalid json"})
                continue
            if not isinstance(msg, dict):
                _write({"error": "expected a JSON object"})
                continue
            if "key" in msg:
                return str(msg["key"])
            cmd = msg.get("cmd")
            if cmd == "snapshot":
                if last[0] is not None:
                    _write(last[0].to_dict())
                continue
            if cmd == "quit":
                return "q"
            _write({"error": f"unknown message: {msg}"})

    agent_host = replace(host, on_screen=on_screen, agent_mode=True)
    shell.run_cockpit(agent_host, read_key=read_key, screen=_NullScreen())
```

- [ ] **Step 4: Run the round-trip test green**

Run: `uv run pytest tests/test_serve_stdio.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/agent.py tests/test_serve_stdio.py
git commit -m "feat(agent): serve_stdio — stdio JSON pump over run_cockpit (keys in, ScreenModels out)"
```

---

## Task 3: `snapshot` + `quit` commands

The core already handles `snapshot`/`quit` (Task 2 Step 3). This task adds the tests that pin that behaviour.

**Files:**
- Test: `tests/test_serve_stdio.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_serve_stdio.py`:

```python
def test_snapshot_re_emits_current_screen_without_advancing():
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state), [{"cmd": "snapshot"}, {"key": "q"}])
    # home is drawn first; snapshot re-emits an identical home; then quit.
    homes = [f for f in frames if f["kind"] == "home"]
    assert len(homes) >= 2, [f["kind"] for f in frames]
    assert homes[0] == homes[1]


def test_quit_command_unwinds_like_q():
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state), [{"cmd": "quit"}])
    assert frames and frames[0]["kind"] == "home"  # drew home, then quit cleanly
```

- [ ] **Step 2: Run them green**

Run: `uv run pytest tests/test_serve_stdio.py -k "snapshot or quit" -q`
Expected: PASS (2 tests). The first home frame is emitted before the first `read_key`; `snapshot` re-emits the stored last model identically.

- [ ] **Step 3: Commit**

```bash
git add tests/test_serve_stdio.py
git commit -m "test(agent): serve_stdio snapshot re-emits current screen; quit unwinds"
```

---

## Task 4: Protocol error handling

The core already emits `{"error":…}` for bad input (Task 2 Step 3). This task pins it and the held-screen-then-recover behaviour.

**Files:**
- Test: `tests/test_serve_stdio.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_serve_stdio.py`. A raw non-JSON line can't go through `_drive` (which JSON-encodes), so feed the stdin string directly:

```python
def test_bad_json_yields_error_then_recovers():
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO('not json\n{"key": "q"}\n')  # garbage line, then a real quit
    out = io.StringIO()
    serve_stdio(_host(state), stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("error") == "invalid json" for f in frames)
    assert any(f.get("kind") == "home" for f in frames)  # screen held; loop recovered


def test_non_object_and_unknown_command_error():
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO('[1,2,3]\n{"cmd": "frob"}\n{"key": "q"}\n')
    out = io.StringIO()
    serve_stdio(_host(state), stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("error") == "expected a JSON object" for f in frames)
    assert any("unknown message" in str(f.get("error", "")) for f in frames)


def test_eof_unwinds_without_a_quit_message():
    state = CockpitState(tenant_name="Clonway")
    out = io.StringIO()
    serve_stdio(_host(state), stdin=io.StringIO(""), stdout=out)  # empty stdin = immediate EOF
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert frames and frames[0]["kind"] == "home"  # drew home, EOF → returned "q", clean exit
```

- [ ] **Step 2: Run them green**

Run: `uv run pytest tests/test_serve_stdio.py -k "error or eof or unknown" -q`
Expected: PASS (3 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_serve_stdio.py
git commit -m "test(agent): serve_stdio protocol errors (bad json / non-object / unknown cmd) + EOF unwind"
```

---

## Task 5: Gate-safety integration + docs + full gate

**Files:**
- Test: `tests/test_serve_stdio.py`
- Modify: `docs/agent-screen-model.md`

- [ ] **Step 1: Write the gate-safety integration test**

This is the safety test: a walk that would post via a mock client, driven over stdio, must NOT post even when the agent sends the apply key. Append to `tests/test_serve_stdio.py`:

```python
def test_gate_safety_no_post_over_stdio():
    from clonway_cockpit.registry import BlastRadius, WizardContext
    from clonway_cockpit.walk import confirm_apply

    class _MockXero:
        def __init__(self) -> None:
            self.posts = 0

        def post_batch(self) -> None:
            self.posts += 1

    client = _MockXero()

    def handler(ctx) -> None:
        if confirm_apply(ctx, equivalent_cli="xbook bills"):
            ctx.client.post_batch()  # only reached if the gate confirms

    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=client,
            console=render.Console() if hasattr(render, "Console") else None,  # see note
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="xbook bills",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
        )
    )
    state = CockpitState(tenant_name="Clonway")
    # Open shelf C (single spec → handler), press the apply key "a", then quit.
    _drive(_host(state, build_walk_ctx=build_ctx), [{"key": "c"}, {"key": "a"}, {"key": "q"}])
    clear_capabilities()
    assert client.posts == 0, "walk posted to Xero despite agent dry-run gate"
```

Note: the `console` field needs a real `rich.console.Console`. Replace the `console=` line with an explicit import at the top of the test function: `from rich.console import Console` and `console=Console()`. (Written inline as a function-local import to avoid the ruff top-level strip.)

- [ ] **Step 2: Fix the console construction**

Edit the test so the ctx builder uses a real Console (remove the `hasattr` placeholder):

```python
    def build_ctx(screen, read_key, *, focus=None):
        from rich.console import Console

        return WizardContext(
            state={},
            client=client,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )
```

- [ ] **Step 3: Run the gate-safety test green**

Run: `uv run pytest tests/test_serve_stdio.py::test_gate_safety_no_post_over_stdio -q`
Expected: PASS — `client.posts == 0` (the apply key was read but `dry_run` declined).

- [ ] **Step 4: Document the protocol in `docs/agent-screen-model.md`**

Append a section:

```markdown
## Subprocess protocol — `agent.serve_stdio` (M2)

`agent.serve_stdio(host, *, stdin, stdout)` drives the real cockpit over line-delimited
JSON, so a separate agent process can launch and drive it. It is a thin pump over the
same `run_cockpit` core the in-process `CockpitDriver` uses.

| Direction | Message | Effect |
|-----------|---------|--------|
| agent → app | `{"key": "<k>"}` | the next keypress (`up`/`down`/`enter`/`esc`/letters/digits/…) |
| agent → app | `{"cmd": "snapshot"}` | re-emit the current `ScreenModel` (does not advance) |
| agent → app | `{"cmd": "quit"}` / stdin EOF | unwind the cockpit |
| app → agent | `ScreenModel.to_dict()` | emitted at every draw |
| app → agent | `{"error": "<reason>"}` | bad JSON / non-object / unknown message; screen held |

Cadence: under piped (non-tty) stdin the loop emits one frame per draw before each
blocking read — request/response. Inert keys may not redraw (use `snapshot` to re-poll);
animated `walk.progress` pushes frames unsolicited, so treat app→agent as a stream.

**Safety:** `serve_stdio` runs in `Host.agent_mode`, which threads `dry_run=True` into
every walk's `WizardContext`. `walk.confirm_apply` reads the gate key (keeping cadence)
then always declines — an agent can drive any walk end-to-end and see the review and
blast-radius, but **never posts**. The explicit apply-authorization handshake is M4.
```

- [ ] **Step 5: Run the full gate**

Run: `make check`
Expected: `ruff check` clean, `ruff format --check` clean (run `uv run ruff format .` + re-add if it reformats), `mypy src` clean, `pytest` all green (M1-rest baseline + the new dry-run + serve_stdio tests).

- [ ] **Step 6: Confirm the human cockpit + in-process driver are unchanged**

Run: `uv run pytest tests/test_shell.py tests/test_walk.py tests/test_agent_driver.py tests/test_screen_models.py -q`
Expected: PASS — `agent_mode`/`dry_run` default off, so existing behaviour is byte-identical; `CockpitDriver` (agent_mode=False) still applies normally.

- [ ] **Step 7: Commit**

```bash
git add tests/test_serve_stdio.py docs/agent-screen-model.md
git commit -m "test(agent): gate-safety — no post over stdio in dry-run; document the protocol"
```

- [ ] **Step 8: Ship**

Open the PR against `main` with the M2 summary + test plan (use the `ship-pr` flow / repo conventions; no `Co-Authored-By`/🤖 trailers).

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| `serve_stdio` pump over `run_cockpit` | 2 |
| Wire protocol (key / snapshot / quit / error / EOF) | 2, 3, 4 |
| Framework-enforced dry-run (Host.agent_mode → ctx.dry_run → confirm_apply) | 1 |
| Gate-safety test (zero writes) | 5 |
| Round-trip / snapshot / errors tests | 2, 3, 4 |
| Docs | 5 |
| Non-goals (no xbook/xops, no send(), no --agent-script) | honoured — none added |

**Placeholder scan:** the only soft spot was the Task 5 `console=` line; Step 2 replaces it with an explicit `Console()`. No TBD/TODO elsewhere; every code step has complete code; every run step has an exact command + expected outcome.

**Type/name consistency:** `WizardContext.dry_run`, `Host.agent_mode`, `serve_stdio(host, *, stdin, stdout)`, the `{"key"|"cmd"}` / `{"error"}` message shapes, and the `_drive` helper are used identically across tasks. `confirm_apply` keeps its signature; the new fields are defaulted (frozen dataclass, backward-compat). `serve_stdio` reuses `_NullScreen` + `replace` already imported in `agent.py`; only `json`/`sys` are new (added with their use in Task 2).
```
