# Generated Worker Acceptance Evidence

A newly generated worker is **born agent-navigable**, but the scaffold proves only a
baseline: it drives home and quits. The baseline is deliberately minimal so it stays
green out of the box — it becomes load-bearing only as the worker grows real screens.

This document defines the **minimum acceptance evidence** a worker author pastes into
their first "real" PR (the one that adds a genuine capability beyond the scaffold).
No PR that adds a bespoke screen, shelf, or write walk ships without this evidence.

---

## The five evidence items

### 1. Home frame renders

**What**: launch the worker in agent-stdio mode and confirm the first frame is a
well-formed `home` screen at the current schema version.

**Command**:

```bash
uv run <worker> --agent-stdio <<'EOF'
{"cmd":"snapshot"}
{"cmd":"quit"}
EOF
```

Or, drive it programmatically in a test:

```python
from clonway_cockpit.agent import CockpitDriver
from <package>.cli import cockpit

host = cockpit._host(agent_mode=True)
stream = CockpitDriver(host, keys=["q"]).run()
home = stream[0]
assert home.kind == "home"
assert home.to_dict()["schema_version"] == "1.0"
```

**Expected output**: paste the raw first JSON line from the subprocess invocation,
or print `home.to_dict()` in the test. The reviewer must be able to confirm:

- `"kind": "home"` is present.
- `"schema_version": "1.0"` (or the current `clonway_cockpit.model.SCHEMA_VERSION`)
  is present at the top level.

Any deviation from the current schema version must be explained.

---

### 2. At least one capability walk

**What**: drive the cockpit through at least one real capability (a shelf + at least
one screen beyond home) and record every distinct `kind` in the emitted stream.

**Command** (in-process driver):

```python
from clonway_cockpit.agent import CockpitDriver
from <package>.cli import cockpit

host = cockpit._host(agent_mode=True)
# Example: open shelf C (key "c"), step through preflight ("enter"), then cancel ("q")
stream = CockpitDriver(host, keys=["c", "enter", "q"]).run()
kinds = [s.kind for s in stream]
print(kinds)
# Paste output: e.g. ["home", "shelf_menu", "walk.preflight", "home"]
```

**Expected output**: paste the `kinds` list. It must include at least one screen
beyond `home` (typically `shelf_menu` and a walk or card screen from the real
capability). The reviewer confirms the walk reaches the capability's domain screens
by `kind`.

Extend this script as the worker adds more shelves and screens — each new capability
must appear in the drive script by the time its PR ships.

---

### 3. No `unstructured` frames

**What**: run `assert_drives_clean` over the extended capability-walk script and
confirm every frame emitted on that path is modeled (not `unstructured`).

**Test snippet** (add to or replace `test_cockpit_drives_clean` in
`tests/test_cockpit_contract.py`):

```python
from clonway_cockpit import contract
from <package>.cli import cockpit


def test_cockpit_drives_clean() -> None:
    host = cockpit._host(agent_mode=True)
    # Extend this key script as you add shelves — "q" is only the scaffold placeholder.
    stream = contract.assert_drives_clean(host, ["c", "enter", "q"])
    kinds = {s.kind for s in stream}
    assert "home" in kinds
    assert "unstructured" not in kinds  # redundant: assert_drives_clean already fails on it
```

**Expected output**: `pytest -q tests/test_cockpit_contract.py` passes. Paste the
terminal output showing the test name and `.` (or `PASSED`).

**Exception rule**: if a screen legitimately emits `unstructured` (e.g. an
intentionally unconfigured Doctor probe whose setup hint is prose), call
`assert_drives_clean(host, keys, allow_unstructured=True)` and add a comment at the
call site naming the screen and explaining why it is exempted. The exemption must be
reviewed; a silent `allow_unstructured=True` with no justification is a review
failure.

---

### 4. Dry-run decline path

**What**: drive a write-bearing capability (one with a `walk.review` → `walk.gate`
path) to its gate in agent mode and confirm the gate declines with zero side effects.

Agent mode is `dry_run=True` by default (`serve_stdio` sets `agent_mode=True` which
threads `dry_run=True` into every `WizardContext`). Driving to the gate must produce
a `walk.gate` frame with `status == "declined"` and `reason == "dry_run"` — proof
the posture held.

**Test snippet**:

```python
from clonway_cockpit.agent import CockpitDriver
from <package>.cli import cockpit


def test_write_gate_declines_in_dry_run() -> None:
    host = cockpit._host(agent_mode=True)
    # Drive to the write gate — replace keys with the real walk's preflight → review path.
    stream = CockpitDriver(host, keys=["c", "enter", "enter", "q"]).run()
    gate_frames = [s for s in stream if s.kind == "walk.gate"]
    assert gate_frames, "expected a walk.gate frame — did the drive reach the write path?"
    gate = gate_frames[0].to_dict()
    assert gate["meta"]["status"] == "declined"
    assert gate["meta"]["reason"] == "dry_run"
```

**Expected output**: `pytest -q` on this test passes. Paste the output.

If the walk's external client would error during a dry run (e.g. it calls a live API
before the gate), inject a mock or stub at the client boundary — the dry-run
guarantee is that the **gate** declines, not that no I/O occurs before the gate. The
mock/stub approach must be noted in the PR.

---

### 5. Guarded apply against a mock

**What**: with `allow_apply=True` and a mocked external client, drive to the
`awaiting_apply` gate frame, send a token-matched apply, and confirm the apply hits
only the mock — never a live credential or external system.

**This item forbids live credentials and external systems in acceptance evidence.**
Mocks or fakes only. If the real client makes network calls or writes to a live
service, inject a fake/stub that records calls but does nothing real. The PR
description must name the mock/stub and confirm no live credential is in scope.

**Test snippet** (in-process driver with an injected fake client):

```python
from dataclasses import replace
from unittest.mock import MagicMock

from clonway_cockpit.agent import CockpitDriver
from <package>.cli import cockpit


def test_guarded_apply_hits_mock_only() -> None:
    fake_client = MagicMock()

    host = cockpit._host(agent_mode=True)

    # Wrap build_walk_ctx to inject the fake client in-process.
    # unittest.mock.patch cannot intercept calls inside a spawned subprocess, so the
    # fake must be wired here — at the WizardContext construction point — where it
    # runs in the same interpreter as the assert.
    _orig_build = host.build_walk_ctx

    def _build_with_fake(screen, read_key, *, focus=None):
        ctx = _orig_build(screen, read_key, focus=focus)
        return replace(ctx, client=fake_client)

    # Wire an always-approve gate authorizer: simulates a human sign-off in-process.
    # serve_stdio wires this via a stdin handshake; CockpitDriver bypasses stdio,
    # so inject authorize_apply directly on the host instead.
    host = replace(
        host,
        build_walk_ctx=_build_with_fake,
        authorize_apply=lambda _proposal: True,
    )

    # Drive to the write gate — replace these keys with the real walk's path.
    stream = CockpitDriver(host, keys=["c", "enter", "enter"]).run()

    gate_frames = [s for s in stream if s.kind == "walk.gate"]
    applied = next(
        (g for g in gate_frames if g.to_dict().get("meta", {}).get("status") == "applied"),
        None,
    )
    assert applied is not None, "expected walk.gate{applied} after authorize"

    # The fake_client assertion is the evidence no live system was touched.
    assert fake_client.post.called, "expected fake_client.post to be called"
    assert fake_client.post.call_count == 1
```

**Why in-process, not subprocess**: `unittest.mock.patch` rebinds a name in the
*parent* process's import namespace. `CockpitClient.spawn` is `subprocess.Popen` —
a separate Python interpreter that imports its own un-patched copy of the client.
`mock_post.called` in the parent is therefore structurally always `False`, and the
walk executes the real `post` in the child — exactly what this item forbids.
`CockpitDriver` runs the walk in the same interpreter, so the injected
`fake_client` genuinely intercepts every call.

**Expected output**: `pytest -q` on this test passes. Paste the output including
the `fake_client.post.called` assertion line — that line is the evidence no live
system was touched.

For an integration test that drives the worker as a real subprocess (e.g. to verify
the `--allow-apply` CLI flag end-to-end), point the worker at a fake endpoint via
an environment variable or config file that the child process loads at startup.
Do not use `unittest.mock.patch` across a `subprocess.Popen` boundary — it cannot
work. Integration-style subprocess tests must be noted in the PR and are not a
substitute for the in-process item above.

---

## Checklist

Each item is a required tick before the PR is approved. Paste the evidence — the
command and its verbatim output — in the PR body for each:

- [ ] **1. Home frame renders** — paste the first JSON line or `to_dict()` output.
- [ ] **2. Capability walk** — paste the `kinds` list covering at least one bespoke screen.
- [ ] **3. No `unstructured`** — paste `pytest -q tests/test_cockpit_contract.py` output.
  Any `allow_unstructured=True` exception is named and justified in the test.
- [ ] **4. Dry-run decline** — paste `pytest -q` output; `walk.gate{declined,dry_run}` frame
  visible.
- [ ] **5. Guarded apply / mock** — paste `pytest -q` output including the mock assertion.
  No live credential or external system is referenced.
- [ ] **Fleet conformance tracker** — once `docs/fleet-conformance.md` exists, add or update
  your worker's row there to record that this checklist was completed. (The tracker is planned
  separately; this step activates once it lands on `main`.)

---

## Growing the gate — extend the contract tests as the worker grows

The scaffold's `test_cockpit_drives_clean` drives only `["q"]`. That is a placeholder, not a
finished test. The docstring in the generated file says as much:

> *"Extend the key script as you add shelves; configure Doctor before driving into `'g'`"*

**This is a rule, not advice.** Every PR that adds a shelf, screen, or write walk **must**
extend the drive script in `tests/test_cockpit_contract.py` in the same change. A green
CI on a drive-only-home script does not prove the new screen is agent-readable — it proves
nothing about it at all.

### What to add when you add a screen

| When you add… | What to add to `test_cockpit_contract.py` |
|---|---|
| A new shelf | Drive into it: add the shelf key (e.g. `"c"`) and at least `"q"` to escape. Assert the shelf's `kind` appears in the stream. |
| A bespoke `render_*` + `model_*` twin | Point `assert_render_model_parity` at the module that defines it (the docstring shows you how). Also drive to the screen so `assert_drives_clean` verifies it emits on a real path. |
| A write walk (→ `walk.review` → gate) | Add a `test_write_gate_declines_in_dry_run`-style test driving to the gate and asserting `declined / dry_run`. |
| A capture step (typed input / confirm) | Drive through it using `CockpitDriver`'s key list or `CockpitClient.answer_input` / `answer_confirm`. The framework handles capture steps in agent mode — test that the drive completes without hanging. |

### Pointing `assert_render_model_parity` at worker modules

By default the scaffold points the static check only at `cockpit` (the generated module). As
the worker grows bespoke render modules, point it at each one explicitly — OR pass a list:

```python
from <package>.cli import cockpit, reports, walk_screens

def test_render_model_parity() -> None:
    contract.assert_render_model_parity([cockpit, reports, walk_screens])
```

Do not leave it pointing only at the scaffold module after adding bespoke screens elsewhere:
the parity check is only exhaustive over the namespaces it is given.

### Widen `{m.kind for m in stream}` to audit coverage

`assert_drives_clean` does not tell you what it *did not* drive. After extending the key
script, print the covered kinds to confirm the walk actually reached the new screen:

```python
stream = contract.assert_drives_clean(host, keys)
covered = {m.kind for m in stream}
assert "my_worker.new_screen" in covered  # confirm the drive reached it
```

This one-line assert turns "the test ran" into "the test reached and modeled this screen".

### The "advertised but not wired" trap

`assert_render_model_parity` passes as soon as `model_*` exists. But a `model_*` that is
never called on a real render path is silent dead code — an agent asking for that screen gets
`unstructured`. `assert_drives_clean` is the only check that proves the model is wired. Both
must be green; neither alone is sufficient.

See `docs/agent-screen-model.md` §"Coverage: what the gate actually proves" for the full
distinction.
