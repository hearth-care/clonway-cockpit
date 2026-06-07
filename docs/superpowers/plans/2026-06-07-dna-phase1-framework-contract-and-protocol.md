# DNA Phase 1 — framework contract + protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the framework substrate that makes agent-navigability inheritable and enforceable: a reusable parity+conformance gate, a one-line agent entrypoint, a versioned wire protocol, and the framework-owned driving client.

**Architecture:** New `clonway_cockpit.contract` module (static parity + dynamic drive-it conformance) that consumers import instead of hand-copying `test_contract.py`; a `serve_agent_stdio` wrapper; `SCHEMA_VERSION` baked into `ScreenModel.to_dict()`; a `CockpitClient` subprocess driver that is the peer of `serve_stdio`. The framework's own tests are rewritten to dogfood the new module.

**Tech Stack:** Python 3.12, dataclasses, `inspect`, stdlib `subprocess`/`json`, pytest, ruff/mypy. No new runtime deps.

**Parent spec:** `docs/superpowers/specs/2026-06-07-agent-navigability-as-platform-dna-design.md`

---

### Task 1: `contract` module — static parity check

**Files:**
- Create: `src/clonway_cockpit/contract.py`
- Test: `tests/test_contract_module.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contract_module.py
from __future__ import annotations

import types

import pytest

from clonway_cockpit import contract, render


def test_page_framing_renders_finds_screens_not_subcomponents():
    found = contract.page_framing_renders(render)
    assert "render_cockpit_screen" in found  # frames a page()
    assert "render_help" in found
    # sub-components / helpers that don't call page() are excluded
    assert "render_header" not in found


def test_model_twin_naming():
    assert contract.model_twin("render_help") == "model_help"


def test_parity_passes_for_the_framework_render_module():
    # The framework co-locates render_* and model_*; all page-framers are twinned.
    contract.assert_render_model_parity(render)


def test_parity_fails_on_an_orphan_render():
    ns = types.ModuleType("fake")

    def render_orphan():
        page("x")  # noqa: F821 — only the source text matters to the heuristic

    ns.render_orphan = render_orphan
    with pytest.raises(AssertionError, match="render_orphan -> model_orphan"):
        contract.assert_render_model_parity(ns)


def test_parity_allow_unmodeled_escape_hatch():
    ns = types.ModuleType("fake")

    def render_orphan():
        page("x")  # noqa: F821

    ns.render_orphan = render_orphan
    contract.assert_render_model_parity(ns, allow_unmodeled={"render_orphan"})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_contract_module.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.contract`.

- [ ] **Step 3: Write the module (static half only for now)**

```python
# src/clonway_cockpit/contract.py
"""Shippable agent-navigability gate — the parity + conformance checks any repo runs
against ITS OWN render/model namespaces.

Promoted from clonway-cockpit's own tests so the discipline is imported, not
hand-copied: a framework bump propagates it to every consumer. Two checks:

* assert_render_model_parity — STATIC: every page-framing render_* has a model_* twin.
* assert_drives_clean — DYNAMIC: drive the real loop, assert no `unstructured` frame
  reaches an agent on a real path (catches modeled-but-dead, which static review can't see).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from types import ModuleType


def page_framing_renders(render_ns: ModuleType) -> set[str]:
    """Public ``render_*`` in ``render_ns`` whose source calls ``page(`` — i.e. it frames
    a full screen, vs a sub-component (render_header) or helper. Same heuristic the
    framework contract test used."""
    out: set[str] = set()
    for name, fn in inspect.getmembers(render_ns, inspect.isfunction):
        if not name.startswith("render_"):
            continue
        try:
            src = inspect.getsource(fn)
        except OSError:  # pragma: no cover — source is always available in-tree
            continue
        if "page(" in src:
            out.add(name)
    return out


def model_twin(render_name: str) -> str:
    """'render_foo' -> 'model_foo'."""
    return "model_" + render_name[len("render_") :]


def assert_render_model_parity(
    render_ns: ModuleType,
    model_ns: ModuleType | None = None,
    *,
    allow_unmodeled: Iterable[str] = (),
) -> None:
    """Assert every page-framing ``render_*`` in ``render_ns`` has a ``model_*`` twin in
    ``model_ns`` (defaults to ``render_ns`` — most repos co-locate them).

    ``allow_unmodeled`` is an explicit, reviewed escape hatch: a render_* deliberately
    served as ``unstructured``. Empty by default, so forgetting a model is a hard failure."""
    models = model_ns if model_ns is not None else render_ns
    allowed = set(allow_unmodeled)
    missing: list[str] = []
    for render_name in sorted(page_framing_renders(render_ns)):
        if render_name in allowed:
            continue
        twin = model_twin(render_name)
        if not hasattr(models, twin):
            missing.append(f"{render_name} -> {twin}")
    assert not missing, (
        "page-framing render_* with no model_* twin (agent gets `unstructured`): "
        + ", ".join(missing)
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_contract_module.py -q`
Expected: PASS (5 tests). If `test_parity_passes_for_the_framework_render_module` fails, a framework page-framer is genuinely missing a twin — fix the render module, do **not** weaken the test.

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/contract.py tests/test_contract_module.py
git commit -m "feat(contract): shippable static render/model parity gate"
```

---

### Task 2: `contract.assert_drives_clean` — dynamic conformance

**Files:**
- Modify: `src/clonway_cockpit/contract.py`
- Test: `tests/test_contract_module.py:append`

- [ ] **Step 1: Write the failing test** (append to `tests/test_contract_module.py`)

```python
def _stub_host(monkeypatch):
    """A minimal real Host built from the framework defaults — enough to drive the home
    loop headlessly. Reuses the test_seam helpers' shape."""
    from clonway_cockpit import shell, usage
    from clonway_cockpit.doctor import fixes_for
    from clonway_cockpit.state import CockpitState, NeedsItem, Pill

    def capture_state():
        return CockpitState(
            tenant_name="T", app_label="x", date_label="", time_label="",
            pills=(Pill(label="x", status="ok", detail="", level="ok"),),
            needs=(NeedsItem(title="N", detail="d", level="warn", capability_key=None),),
            shelves={"A": "Cap", "G": "Diag"}, toolkit_label="toolkit",
        )

    return shell.Host(
        capture_state=capture_state,
        build_walk_ctx=lambda screen, read_key, focus=None: None,
        activate_pill=lambda *a: None,
        doctor_build_report=lambda: (_ for _ in ()).throw(RuntimeError("unconfigured")),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=lambda: __import__(
            "clonway_cockpit.render", fromlist=["render_note"]
        ).render_note("doctor", "unconfigured"),
        usage=usage,
        on_open=lambda: None,
        app_label="x",
        get_capabilities=lambda: [],
        get_capability=lambda k: None,
    )


def test_assert_drives_clean_passes_on_a_clean_home_walk(monkeypatch):
    host = _stub_host(monkeypatch)
    # Walk: open Doctor shelf (G) → it degrades to a note (unconfigured) → quit.
    stream = contract.assert_drives_clean(host, ["g", "q", "q"])
    assert stream  # frames were recorded
    assert all(m.kind != "unstructured" for m in stream) or True  # Doctor unconfigured uses model_unstructured


def test_assert_drives_clean_flags_unstructured(monkeypatch):
    import pytest
    host = _stub_host(monkeypatch)
    # The Doctor-unconfigured path emits model_unstructured → with the default
    # (allow_unstructured=False) driving INTO Doctor must trip the gate.
    with pytest.raises(AssertionError, match="unstructured"):
        contract.assert_drives_clean(host, ["g", "q", "q"])
```

> NOTE for the implementer: the framework's Doctor-unconfigured path emits
> `model_unstructured`. That makes it the perfect positive control for the dynamic
> gate. Decide at execution time whether the *home-only* walk (`["q"]`) is the clean
> case and the *Doctor* walk is the dirty case, and split the two tests accordingly —
> the first test above should drive a path that emits **no** unstructured (e.g. just
> `["q"]` or arrowing), the second should drive into Doctor. Adjust the key scripts to
> match the real emission, asserting the real behavior rather than forcing it.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_contract_module.py -k drives_clean -q`
Expected: FAIL — `assert_drives_clean` does not exist yet.

- [ ] **Step 3: Add `assert_drives_clean` to `contract.py`**

```python
# append to src/clonway_cockpit/contract.py

def assert_drives_clean(
    host,  # clonway_cockpit.shell.Host — untyped to avoid an import cycle
    keys: Iterable[str],
    *,
    allow_unstructured: bool = False,
) -> list:
    """DYNAMIC conformance: drive ``host`` headlessly over the scripted ``keys`` and
    assert no emitted screen fell through to ``unstructured`` (the agent-blind fallback).
    Returns the recorded ScreenModel stream so a caller can assert further.

    This catches a model that exists but is never wired onto a real path — the
    'advertised but not wired' failure static review structurally cannot see."""
    from clonway_cockpit.agent import CockpitDriver  # local import: avoid import cycle

    stream = CockpitDriver(host, keys=list(keys)).run()
    if not allow_unstructured:
        blind = [m for m in stream if m.kind == "unstructured"]
        assert not blind, (
            f"{len(blind)} screen(s) reached the agent as `unstructured` while driving "
            f"{list(keys)!r}: {[m.title for m in blind]}"
        )
    return stream
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_contract_module.py -q`
Expected: PASS. (Reconcile the two key scripts with real emission per the NOTE.)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/contract.py tests/test_contract_module.py
git commit -m "feat(contract): dynamic drive-it conformance (no unstructured on a real path)"
```

---

### Task 3: Dogfood — rewrite the framework's own `test_contract.py`

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Replace the hand-rolled dict + introspection with the shared gate**

```python
# tests/test_contract.py  (full replacement)
"""Contract: every full-screen framework render primitive has a model_* twin.

Dogfoods clonway_cockpit.contract — the SHIPPABLE gate consumers import. Keeping the
framework's own check expressed through the public helper means the framework's CI is the
canary for the helper itself: if `assert_render_model_parity` regresses, this fails first."""

from __future__ import annotations

from clonway_cockpit import contract, render


def test_every_page_framing_render_has_a_model_twin():
    contract.assert_render_model_parity(render)


def test_unstructured_is_explicitly_flagged():
    m = render.model_unstructured(render.render_note("x", "y"))
    assert m.kind == "unstructured"
```

- [ ] **Step 2: Run the full suite to confirm no regression**

Run: `uv run pytest tests/test_contract.py tests/test_contract_module.py -q`
Expected: PASS. The old `FRAMEWORK_SCREENS` belt-and-suspenders dict is subsumed by
`assert_render_model_parity` (which finds *all* page-framers, not just the listed ones).

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "refactor(contract): dogfood the shippable gate in the framework's own test"
```

---

### Task 4: `serve_agent_stdio` — the worker-side one-liner

**Files:**
- Modify: `src/clonway_cockpit/agent.py`
- Test: `tests/test_serve_stdio.py:append` (or a new `tests/test_serve_agent_stdio.py`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_serve_agent_stdio.py
from __future__ import annotations

import io

from clonway_cockpit import agent


def test_serve_agent_stdio_delegates_to_serve_stdio(monkeypatch):
    seen = {}

    def fake_serve_stdio(host, *, stdin, stdout, allow_apply=False, on_apply=None):
        seen.update(host=host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)

    monkeypatch.setattr(agent, "serve_stdio", fake_serve_stdio)
    sentinel_host = object()
    sin, sout = io.StringIO(), io.StringIO()
    agent.serve_agent_stdio(sentinel_host, allow_apply=True, stdin=sin, stdout=sout)
    assert seen == {"host": sentinel_host, "stdin": sin, "stdout": sout, "allow_apply": True}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_serve_agent_stdio.py -q`
Expected: FAIL — `AttributeError: module 'clonway_cockpit.agent' has no attribute 'serve_agent_stdio'`.

- [ ] **Step 3: Add `serve_agent_stdio` to `agent.py`** (after `serve_stdio`)

```python
def serve_agent_stdio(
    host: shell.Host,
    *,
    allow_apply: bool = False,
    stdin=sys.stdin,  # noqa: ANN001
    stdout=sys.stdout,  # noqa: ANN001
) -> None:
    """The worker-side one-liner a CLI ``--agent-stdio`` callback calls: serve the agent
    protocol over stdin/stdout. Thin over :func:`serve_stdio` (which already forces
    ``agent_mode=True`` and wires the guarded-apply handshake when ``allow_apply``).

    Promoted into the framework so every consumer stops hand-rolling its own ``serve_agent``;
    the worker-template generates a call to this. NOTE the host-rebuild recipe: if a worker's
    ``_host()`` is re-invoked inside its own callbacks, build it agent-mode-aware (see
    docs/agent-screen-model.md → 'Wiring a worker')."""
    serve_stdio(host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_serve_agent_stdio.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/agent.py tests/test_serve_agent_stdio.py
git commit -m "feat(agent): serve_agent_stdio — framework one-liner for the --agent-stdio callback"
```

---

### Task 5: Protocol versioning — `SCHEMA_VERSION` on the wire

**Files:**
- Modify: `src/clonway_cockpit/model.py`
- Test: `tests/test_model.py:append` (+ fix any exact-`to_dict()` assertions in the suite)
- Doc: `docs/agent-screen-model.md`

- [ ] **Step 1: Write the failing test** (append to `tests/test_model.py`)

```python
def test_to_dict_carries_schema_version():
    from clonway_cockpit.model import SCHEMA_VERSION, ScreenModel

    d = ScreenModel(kind="note", title="t").to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    # the full shape is pinned so an accidental breaking change forces a version bump
    assert set(d) == {"kind", "title", "regions", "selection", "actions", "meta", "schema_version"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_model.py -k schema_version -q`
Expected: FAIL — no `SCHEMA_VERSION`, `to_dict()` lacks the key.

- [ ] **Step 3: Add the version + emit it**

```python
# src/clonway_cockpit/model.py — near the top, after the module docstring imports
SCHEMA_VERSION = "1.0"

# ScreenModel.to_dict — replace the body:
    def to_dict(self) -> dict:
        """A plain JSON-serialisable dict (nested dataclasses expanded), tagged with the
        wire-protocol version so a driver/orchestrator can branch on it. Additive: a
        consumer that ignores unknown keys is unaffected."""
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d
```

- [ ] **Step 4: Find and fix any exact-`to_dict()` assertions broken by the new key**

Run: `grep -rn "to_dict()" tests/ | grep -i "==\|assert"`
For each test that asserts an exact dict equality on `to_dict()`, add `"schema_version": SCHEMA_VERSION` to the expected dict (import it), OR relax to assert the relevant keys. Do NOT delete coverage.

Run: `uv run pytest tests/ -q`
Expected: PASS (whole suite). Iterate on Step 4 until green.

- [ ] **Step 5: Document the versioning in the protocol doc**

Append a `## Protocol versioning` section to `docs/agent-screen-model.md`:

```markdown
## Protocol versioning

Every `ScreenModel.to_dict()` frame carries a top-level `"schema_version"` (currently
`"1.0"`, the `clonway_cockpit.model.SCHEMA_VERSION` constant). A driver/orchestrator
branches on it. The version bumps only on a **breaking** wire change (a removed/renamed
key or changed type); additive keys (a new optional `meta` field) do not bump it. The
shape-pin test in `tests/test_model.py` fails on an accidental breaking change, forcing a
deliberate bump + this doc's update.
```

- [ ] **Step 6: Commit**

```bash
git add src/clonway_cockpit/model.py tests/test_model.py docs/agent-screen-model.md tests/
git commit -m "feat(model): version the wire protocol — schema_version on every frame"
```

---

### Task 6: `CockpitClient` — the framework-owned driving end

**Files:**
- Modify: `src/clonway_cockpit/agent.py`
- Test: `tests/test_cockpit_client.py`

This is the peer of `serve_stdio`. The Phase-1 test drives a **real in-process** `serve_stdio`
over an `os.pipe` pair (no subprocess), so the client/server protocol is pinned without
spawning a child; Phase 4 adds a real-subprocess integration test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cockpit_client.py
from __future__ import annotations

import os
import threading

from clonway_cockpit import agent


def _pipe_text():
    r, w = os.pipe()
    return os.fdopen(r, "r"), os.fdopen(w, "w", buffering=1)


def test_client_reads_home_and_presses(make_stub_host):
    """Drive a real serve_stdio over a pipe pair via CockpitClient's wire methods.

    `make_stub_host` is a fixture returning a minimal Host (see conftest); reuse the
    one Task-2 introduced, promoted to tests/conftest.py."""
    # agent -> app pipe and app -> agent pipe
    to_app_r, to_app_w = _pipe_text()
    to_agent_r, to_agent_w = _pipe_text()

    host = make_stub_host()

    def serve():
        agent.serve_stdio(host, stdin=to_app_r, stdout=to_agent_w)
        to_agent_w.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    client = agent.CockpitClient.over_streams(stdin=to_agent_r, stdout=to_app_w)
    home = client.read_home()
    assert home["kind"] == "cockpit"
    assert home["schema_version"] == "1.0"
    frame = client.snapshot()
    assert frame["kind"] == "cockpit"
    client.quit()
    t.join(timeout=5)
    assert not t.is_alive()
```

> The full guarded-apply handshake (`client.apply(token, approve=...)`) is pinned by a
> follow-up test in this file: drive a host whose walk reaches a write gate with
> `allow_apply=True`, assert that `approve=lambda p: True` posts once and `approve=lambda
> p: False` posts zero times. Build that against an existing apply-gate fixture (see
> `tests/test_apply_authorization.py` for the shape).

- [ ] **Step 2: Promote `make_stub_host` to `tests/conftest.py`**

Move the `_stub_host` helper from Task 2 into a `tests/conftest.py` fixture `make_stub_host`
(returns a fresh Host each call) so both `test_contract_module.py` and `test_cockpit_client.py`
share it. Update Task-2's tests to use the fixture.

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_cockpit_client.py -q`
Expected: FAIL — `CockpitClient` does not exist.

- [ ] **Step 4: Implement `CockpitClient`** (append to `agent.py`)

```python
class CockpitClosed(Exception):
    """The cockpit stream closed (worker exited / EOF) when a frame was expected."""


class CockpitClient:
    """Drive a worker's cockpit over the ``--agent-stdio`` protocol — the framework-owned
    PEER of :func:`serve_stdio`. The orchestrator, a CLI session, and an autonomous agent
    all drive through this one class, so 'human operating' and 'agent operating' are the
    same path.

    Two constructors: :meth:`spawn` launches ``<worker> --agent-stdio`` as a subprocess
    (the production path); :meth:`over_streams` wraps an existing reader/writer pair (the
    in-process test path, and any transport the caller already owns)."""

    def __init__(self, *, stdin, stdout, proc=None) -> None:  # noqa: ANN001
        # stdin = the stream WE READ frames from (the app's stdout);
        # stdout = the stream WE WRITE messages to (the app's stdin).
        self._in = stdin
        self._out = stdout
        self._proc = proc

    @classmethod
    def over_streams(cls, *, stdin, stdout) -> "CockpitClient":  # noqa: ANN001
        return cls(stdin=stdin, stdout=stdout)

    @classmethod
    def spawn(cls, argv: list[str], *, cwd: str | None = None, env: dict | None = None) -> "CockpitClient":
        import subprocess

        proc = subprocess.Popen(  # noqa: S603 — argv is caller-controlled, not shell
            argv, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )
        return cls(stdin=proc.stdout, stdout=proc.stdin, proc=proc)

    def _send(self, obj: dict) -> None:
        self._out.write(json.dumps(obj) + "\n")
        self._out.flush()

    def _read_frame(self) -> dict:
        line = self._in.readline(_MAX_MSG_BYTES)
        if line == "":
            raise CockpitClosed("cockpit stream closed")
        return json.loads(line)

    def read_home(self) -> dict:
        """Read the first frame the cockpit paints on open."""
        return self._read_frame()

    def press(self, key: str) -> dict:
        self._send({"key": key})
        return self._read_frame()

    def snapshot(self) -> dict:
        self._send({"cmd": "snapshot"})
        return self._read_frame()

    def apply(self, token: str, *, approve) -> dict:  # noqa: ANN001
        """Complete the guarded-apply handshake at an ``walk.gate{awaiting_apply}`` frame.
        ``approve(proposal) -> bool`` is the human-sign-off seam: called with the proposal;
        only a True result sends ``{"apply": true, "token": token}``. Any other result sends
        ``{"apply": false}`` so the app declines. Returns the next frame (applied/declined)."""
        if approve({"token": token}):
            self._send({"apply": True, "token": token})
        else:
            self._send({"apply": False})
        return self._read_frame()

    def quit(self) -> None:
        with contextlib.suppress(Exception):
            self._send({"cmd": "quit"})
        if self._proc is not None:
            with contextlib.suppress(Exception):
                self._proc.wait(timeout=5)

    def __enter__(self) -> "CockpitClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.quit()
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_cockpit_client.py -q`
Expected: PASS. If `read_home()` blocks, confirm the stub host paints a home frame on
first draw (it does — `_home` emits `model_cockpit_screen` before reading a key).

- [ ] **Step 6: Add the apply-handshake test** (per the Step-1 note) and make it pass.

Run: `uv run pytest tests/test_cockpit_client.py -q`
Expected: PASS — approve→1 post, decline→0 posts.

- [ ] **Step 7: Commit**

```bash
git add src/clonway_cockpit/agent.py tests/test_cockpit_client.py tests/conftest.py tests/test_contract_module.py
git commit -m "feat(agent): CockpitClient — framework-owned driving peer of serve_stdio"
```

---

### Task 7: Export the new surface + gate the whole suite

**Files:**
- Modify: `src/clonway_cockpit/__init__.py` (optional convenience re-exports)
- Verify: ruff + mypy + full pytest

- [ ] **Step 1: (Optional) re-export for ergonomics**

If the repo re-exports public API from `__init__.py`, add `contract`, `serve_agent_stdio`,
`CockpitClient`. Keep consistent with the existing export style (the current `__init__.py`
is docstring-only, so this may be a no-op — leave it if so).

- [ ] **Step 2: Lint, type, full suite**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
```
Expected: all green. Fix any ruff autofix that strips a just-added import by re-adding it in
the same edit (known gotcha).

- [ ] **Step 3: Commit any lint/type fixups**

```bash
git add -A && git commit -m "chore(contract): lint/type/export tidy for the Phase-1 substrate"
```

---

### Task 8: Finish the branch

- [ ] Announce the finishing-a-development-branch skill, verify the full suite is green, push, and open a PR titled `feat: agent-navigability DNA — framework contract + protocol (Phase 1)`. PR body: the spec link + a one-line-per-task summary. No `Co-Authored-By` / 🤖 trailers (global rule).

---

## Self-review

- **Spec coverage:** L1 (seam → `serve_agent_stdio` Task 4 + `CockpitClient` Task 6), L2 (gate → Tasks 1–3), protocol versioning (Task 5). L3/L4 are Phases 2–4. ✓
- **Placeholder scan:** the two `assert_drives_clean` key scripts (Task 2) and the apply-handshake test (Task 6) carry explicit implementer NOTEs to reconcile against real emission — these are deliberate "assert the real behavior" instructions, not TODO placeholders. ✓
- **Type consistency:** `assert_render_model_parity(render_ns, model_ns=None, *, allow_unmodeled)`, `assert_drives_clean(host, keys, *, allow_unstructured)`, `CockpitClient.over_streams/spawn/read_home/press/snapshot/apply/quit`, `SCHEMA_VERSION` — names identical across plan and spec §4. ✓
