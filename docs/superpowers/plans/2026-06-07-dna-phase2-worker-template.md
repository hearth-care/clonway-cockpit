# DNA Phase 2 — worker-template grows the agent channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every newly-scaffolded worker is born agent-navigable: it ships a `--agent-stdio` channel, an agent-mode-aware host, and the parity + drive-it conformance gate wired to its own render namespace — and its generated CI keeps it that way.

**Architecture:** Extend the existing `worker-template/` copier template (which already generates a working cockpit, signals, CI, and the C6 smoke test) with the agent entrypoint + gate. Extend `tests/test_worker_template.py` with new C6 acceptance criteria that prove the *generated* worker is agent-drivable and drives clean.

**Tech Stack:** copier (Jinja templates), Python 3.12, Typer, pytest. Depends on **Phase 1 merged to `main`** (the template's default `clonway_rev=main` must resolve `clonway_cockpit.contract` + `serve_agent_stdio`).

**Parent spec:** `docs/superpowers/specs/2026-06-07-agent-navigability-as-platform-dna-design.md`

---

### Task 1: Generate the agent-mode-aware host + `serve_agent`

**Files:**
- Modify: `worker-template/src/{{ package_name }}/cli/cockpit.py.jinja`

- [ ] **Step 1: Make `_host` agent-mode-aware**

Replace the template's `_host()` (currently `def _host() -> shell.Host:` with no agent mode):

```python
def _host(*, agent_mode: bool = False) -> shell.Host:
    """Build {{ worker_id }}'s cockpit Host. ``agent_mode`` (set by ``serve_agent``)
    threads the dry-run + guarded-apply posture through every walk so an agent driving
    the real cockpit can navigate any flow but never posts off the explicit gate.

    This worker does not rebuild its host mid-loop, so a parameter is enough — no ambient
    flag needed. A worker that re-invokes ``_host()`` inside its own callbacks should read
    an ambient ``_AGENT_MODE`` here instead (see docs/agent-screen-model.md → 'Wiring a worker')."""
    return shell.Host(
        capture_state=capture_state,
        build_walk_ctx=build_walk_ctx,
        activate_pill=activate_pill,
        doctor_build_report=doctor_build_report,
        doctor_build_probes=doctor_build_probes,
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=doctor_unconfigured_renderable,
        usage=usage,
        on_open=_on_open,
        app_label=_APP_LABEL,
        agent_mode=agent_mode,
    )
```

- [ ] **Step 2: Add `serve_agent`** (after `run_cockpit` in the same file)

```python
def serve_agent(*, stdin=sys.stdin, stdout=sys.stdout, allow_apply: bool = False) -> None:
    """Serve {{ worker_id }}'s cockpit to an agent over line-delimited JSON on stdin/stdout
    — the SAME cockpit a human drives, in agent mode (dry-run; ``allow_apply`` opts into the
    guarded-apply token handshake). Reached via ``{{ worker_id }} --agent-stdio``."""
    from clonway_cockpit.agent import serve_agent_stdio

    serve_agent_stdio(_host(agent_mode=True), stdin=stdin, stdout=stdout, allow_apply=allow_apply)
```

(`sys` is already imported in the template.)

- [ ] **Step 3: Verify the template still generates** (smoke)

Run: `uv run pytest tests/test_worker_template.py -q`
Expected: PASS (existing ACs unaffected — `serve_agent` is additive).

- [ ] **Step 4: Commit**

```bash
git add worker-template/src/'{{ package_name }}'/cli/cockpit.py.jinja
git commit -m "feat(template): agent-mode-aware host + serve_agent in the generated cockpit"
```

---

### Task 2: Generate the `--agent-stdio` CLI callback

**Files:**
- Modify: `worker-template/src/{{ package_name }}/cli/__init__.py.jinja`

- [ ] **Step 1: Add the global flags to `_root` and route to `serve_agent`**

Replace the template's `_root` callback with:

```python
from {{ package_name }}.cli.cockpit import run_cockpit, serve_agent  # add serve_agent to the import


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
    """Bare ``{{ worker_id }}``: open the cockpit on a real TTY; ``--agent-stdio`` serves the
    same cockpit to an agent; else print help so pipes and scheduled jobs keep working."""
    if agent_stdio:
        serve_agent(allow_apply=allow_apply)
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        run_cockpit()
    else:
        typer.echo(ctx.get_help())
```

- [ ] **Step 2: Verify generation**

Run: `uv run pytest tests/test_worker_template.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add worker-template/src/'{{ package_name }}'/cli/__init__.py.jinja
git commit -m "feat(template): --agent-stdio / --allow-apply on the generated CLI"
```

---

### Task 3: Generate the contract + conformance test

**Files:**
- Create: `worker-template/tests/test_cockpit_contract.py.jinja`

- [ ] **Step 1: Write the generated test**

```python
"""Agent-navigability gate for {{ worker_id }} — inherited from clonway-cockpit.

This is the DNA check: every page-framing ``render_*`` this worker adds MUST ship a
``model_*`` twin, and driving the cockpit must never hand an agent an ``unstructured``
screen. Both are enforced here in CI. As you add bespoke screens, keep them twinned and
extend the drive script — do not weaken these asserts."""

from __future__ import annotations

from clonway_cockpit import contract

from {{ package_name }}.cli import cockpit


def test_render_model_parity() -> None:
    """Every page-framing render_* in the worker's cockpit module has a model_* twin.
    Vacuously true for the scaffold (it uses framework screens); becomes load-bearing the
    moment you add a bespoke render_* here or in a worker render submodule (point this at
    that module)."""
    contract.assert_render_model_parity(cockpit)


def test_cockpit_drives_clean() -> None:
    """Driving the home screen emits structured frames only — no `unstructured` reaches an
    agent. Extend the key script as you add shelves; configure Doctor before driving into
    'g' (the scaffold's Doctor is unconfigured and emits an unstructured setup hint)."""
    host = cockpit._host(agent_mode=True)
    stream = contract.assert_drives_clean(host, ["q"])
    assert stream and stream[0]["kind"] if isinstance(stream[0], dict) else stream[0].kind == "cockpit"
```

> NOTE: `assert_drives_clean` returns `ScreenModel` objects (not dicts). Simplify the last
> line at execution to `assert stream[0].kind == "cockpit"` — written defensively above; pin
> it to the real return type when you run it.

- [ ] **Step 2: Add it to the generated-layout assertion**

In `tests/test_worker_template.py`, add `"tests/test_cockpit_contract.py"` to the `expected`
set in `test_template_generates_expected_layout`.

- [ ] **Step 3: Run the smoke test**

Run: `uv run pytest tests/test_worker_template.py::test_template_generates_expected_layout -q`
Expected: PASS — the new file is generated.

- [ ] **Step 4: Commit**

```bash
git add worker-template/tests/test_cockpit_contract.py.jinja tests/test_worker_template.py
git commit -m "feat(template): generate the render/model parity + drive-clean gate"
```

---

### Task 4: New C6 acceptance criteria — the generated worker is agent-drivable

**Files:**
- Modify: `tests/test_worker_template.py`

- [ ] **Step 1: Write the failing ACs** (append to `tests/test_worker_template.py`)

```python
# --- AC-C6-4 — the generated worker is born agent-navigable -----------------


def test_ac_c6_4_generated_worker_serves_agent_and_drives_clean(tmp_path) -> None:
    from clonway_cockpit import contract

    dst = _generate(tmp_path, worker_id="xgenagent")
    with _importable(dst, "xgenagent"):
        cockpit = importlib.import_module("xgenagent.cli.cockpit")

        # serve_agent + agent-mode-aware host exist
        assert hasattr(cockpit, "serve_agent")
        host = cockpit._host(agent_mode=True)
        assert host.agent_mode is True

        # parity holds for the scaffold, and the home screen drives clean (no unstructured)
        contract.assert_render_model_parity(cockpit)
        stream = contract.assert_drives_clean(host, ["q"])
        assert stream[0].kind == "cockpit"


def test_ac_c6_4_cli_registers_agent_flags(tmp_path) -> None:
    dst = _generate(tmp_path, worker_id="xgenflags")
    with _importable(dst, "xgenflags"):
        cli = importlib.import_module("xgenflags.cli")
        # The Typer callback declares --agent-stdio / --allow-apply.
        params = {p.name for p in cli._root.__click_params__} if hasattr(cli._root, "__click_params__") else set()
        # Fallback: introspect the source if Typer hasn't attached click params yet.
        import inspect as _inspect

        src = _inspect.getsource(cli._root)
        assert "--agent-stdio" in src and "--allow-apply" in src
```

> NOTE: the click-param introspection is brittle across Typer versions; the source-text
> assertion is the reliable check. Keep the source assertion; drop the param-set probe if it
> doesn't hold for the installed Typer.

- [ ] **Step 2: Run to verify** (if Phase 1 is merged to `main`, these should pass against the new template)

Run: `uv run pytest tests/test_worker_template.py -k c6_4 -q`
Expected: PASS. If `assert_render_model_parity`/`assert_drives_clean` import fails, the
template's pinned `clonway_rev` predates Phase 1 — confirm Phase 1 is on `main`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_worker_template.py
git commit -m "test(template): AC-C6-4 — generated worker serves agent + drives clean"
```

---

### Task 5: Update the scaffold's after-copy message + onboarding doc

**Files:**
- Modify: `copier.yml` (`_message_after_copy`)
- Modify: `docs/onboarding-a-worker.md`

- [ ] **Step 1: Mention the agent channel in `_message_after_copy`**

Add a line to the `Next:` block:

```
    6. {{ worker_id }} --agent-stdio   # drive the SAME cockpit as an agent (JSON stdin/stdout)
```

- [ ] **Step 2: Add a 'Wiring a worker to the agent channel' section to `docs/onboarding-a-worker.md`**

Document: the generated `serve_agent` + `--agent-stdio`; the agent-mode-aware `_host` recipe
(and the ambient `_AGENT_MODE` variant for a worker that rebuilds its host); that the
contract test is the enforcement; how to drive it locally:
`echo '{"cmd":"snapshot"}' | {{ worker }} --agent-stdio` and via `CockpitClient.spawn([...])`.

- [ ] **Step 3: Commit**

```bash
git add copier.yml docs/onboarding-a-worker.md
git commit -m "docs(template): document the inherited agent channel + drive recipe"
```

---

### Task 6: Gate + finish

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q` → green.
- [ ] (If available offline) `make template-smoke` to prove a generated worker passes its own `uv run pytest` / `ruff` including the new gate.
- [ ] Finishing-a-development-branch: push + PR `feat: agent-navigability DNA — worker template (Phase 2)`. No `Co-Authored-By` / 🤖 trailers.

---

## Self-review

- **Spec coverage:** L3 scaffold — agent channel (Tasks 1–2), inherited gate (Task 3), born-compliant ACs (Task 4), docs (Task 5). ✓
- **Placeholder scan:** the two implementer NOTEs (Task 3 return-type, Task 4 Typer introspection) are "assert the real behavior" instructions, not TODOs. ✓
- **Dependency:** explicitly gated on Phase 1 being on `main` (Tasks 4 intro + Step 2). ✓
- **Type consistency:** `_host(*, agent_mode=False)`, `serve_agent(*, stdin, stdout, allow_apply)` match Phase 1's `serve_agent_stdio` signature and the spec §4.2 recipe. ✓
