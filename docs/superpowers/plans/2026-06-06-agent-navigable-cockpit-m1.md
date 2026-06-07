# Agent-navigable cockpit — M1 core (foundation + nav/walk path) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the cockpit a typed, JSON-serializable `ScreenModel` for the navigation + walk-path screens (home, shelf menu, walk preflight, walk result), emit it through a framework seam, and add an in-process `CockpitDriver` — so an agent can drive a walk headlessly and assert against structured snapshots instead of scraping rendered ANSI text.

**Architecture:** Add `model.py` (the `ScreenModel`/`Field`/`Row`/`Region` dataclasses). For each migrated screen add a `model_*()` builder in `render.py` *alongside* the existing untouched `render_*()`, and add a parity test proving the model agrees with the rendered text (no-drift without rewriting mature visuals). A single `on_screen(model)` observer on `Host` (and threaded into walks via `WizardContext`) emits the model wherever the shell/walk draws. `CockpitDriver` installs that observer, feeds scripted keys, and records the `ScreenModel` stream.

**Tech Stack:** Python ≥3.12, Rich, pytest, ruff, mypy. Run: `make test` (`uv run pytest -q`), `make lint` (`uv run ruff check .`), `make typecheck` (`uv run mypy src`), `make check` (all). Work in the existing worktree `/.claude/worktrees/agent-cockpit-spec` on branch `claude/agent-navigable-cockpit-spec`.

**Scope note:** This plan is M1-*core* — the foundation plus the four screens on the "navigate to and run a walk" path. The remaining framework primitives (progress, doctor, filter, note, capability card, the two confirm screens, help) are a follow-on plan (M1-rest) using the identical model+parity pattern. The walk *review/apply* screen is built inside each worker walk (not a framework primitive), so it belongs to M3, not here.

**Conventions for every code block below:** files live under `src/clonway_cockpit/` and `tests/`. All commands run from the worktree root `/Users/olliepage/Developer/clonway-cockpit/.claude/worktrees/agent-cockpit-spec`. Do NOT add `Co-Authored-By`/footers to commits (repo rule).

---

## File structure

| File | Responsibility | New / modified |
|------|----------------|----------------|
| `src/clonway_cockpit/model.py` | `Field`/`Row`/`Region`/`ScreenModel` dataclasses + `to_dict()` | **new** |
| `src/clonway_cockpit/render.py` | add `model_cockpit_screen`/`model_menu`/`model_preflight`/`model_walk_result` + `_selection_id`/`_home_actions` helpers (existing `render_*` untouched) | modified |
| `src/clonway_cockpit/registry.py` | add `WizardContext.on_screen` field | modified |
| `src/clonway_cockpit/shell.py` | add `Host.on_screen`; emit home model in `_home`; emit menu model in `_shelf`; inject `on_screen` into walk ctx in `_open_capability` | modified |
| `src/clonway_cockpit/walk.py` | emit preflight + result models via `ctx.on_screen` | modified |
| `src/clonway_cockpit/agent.py` | `CockpitDriver` (in-process, scripted keys → recorded `ScreenModel` stream) | **new** |
| `tests/test_model.py` | `ScreenModel` unit + `to_dict` | **new** |
| `tests/test_screen_models.py` | parity tests (model agrees with render) for the 4 screens | **new** |
| `tests/test_seam.py` | `Host`/`WizardContext` defaults + walk-ctx injection | **new** |
| `tests/test_agent_driver.py` | `CockpitDriver` integration (home → shelf → walk preflight) | **new** |
| `docs/agent-screen-model.md` | the `Row.id` semi-public contract + model overview | **new** |

---

## Task 1: The `ScreenModel` contract

**Files:**
- Create: `src/clonway_cockpit/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model.py
from __future__ import annotations

from clonway_cockpit.model import Field, Region, Row, ScreenModel


def test_screenmodel_to_dict_is_json_shaped():
    m = ScreenModel(
        kind="home",
        title="xbook",
        regions=[
            Region(
                role="toolkit",
                title="toolkit",
                rows=[Row(id="shelf:C", label="Money out", selected=True)],
            )
        ],
        selection="shelf:C",
        actions=["up", "down", "enter"],
        meta={"app_label": "xbook"},
    )
    d = m.to_dict()
    assert d["kind"] == "home"
    assert d["selection"] == "shelf:C"
    assert d["regions"][0]["rows"][0]["id"] == "shelf:C"
    assert d["regions"][0]["rows"][0]["selected"] is True
    assert d["regions"][0]["rows"][0]["fields"] == []  # default empty list, not missing
    assert d["meta"] == {"app_label": "xbook"}


def test_field_defaults_to_text_role():
    assert Field(label="amount", value="£10").role == "text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'clonway_cockpit.model'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clonway_cockpit/model.py
"""Semantic screen model — the agent-facing contract for "what is on this screen".

A ScreenModel is a structured, JSON-serialisable description of one cockpit screen,
built in the framework from the same inputs the ``render_*`` functions consume. The
human cockpit renders Rich renderables exactly as before; an agent reads the
ScreenModel (via ``Host.on_screen`` / the ``CockpitDriver``) and asserts against its
structure instead of scraping rendered ANSI text.

``Row.id`` values are a SEMI-PUBLIC CONTRACT — agents assert on them; keep them
stable. The ids minted in M1:
  ``pill:<i>``  ``need:<i>``  ``shelf:<LETTER>``  ``option:<key>``  ``back``
  ``change:<i>``  ``precond:<i>``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Field:
    """One labelled datum within a row (e.g. a pill's status, a bill's amount)."""

    label: str
    value: str
    role: str = "text"  # text | number | currency | status | date | …


@dataclass(frozen=True)
class Row:
    """One navigable/selectable line. ``id`` is the stable semantic key agents key on."""

    id: str
    label: str
    fields: list[Field] = field(default_factory=list)
    selected: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class Region:
    """A titled group of rows (or a prose block via ``text``)."""

    role: str
    title: str = ""
    rows: list[Row] = field(default_factory=list)
    text: str | None = None


@dataclass(frozen=True)
class ScreenModel:
    """A structured description of one cockpit screen."""

    kind: str
    title: str = ""
    regions: list[Region] = field(default_factory=list)
    selection: str | None = None  # id of the currently-selected Row, if any
    actions: list[str] = field(default_factory=list)  # keys/verbs the screen honours
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """A plain JSON-serialisable dict (nested dataclasses expanded)."""
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check src/clonway_cockpit/model.py tests/test_model.py && uv run mypy src/clonway_cockpit/model.py`
Expected: no errors. (If ruff flags format, run `uv run ruff format src/clonway_cockpit/model.py tests/test_model.py`.)

- [ ] **Step 6: Commit**

```bash
git add src/clonway_cockpit/model.py tests/test_model.py
git commit -m "feat(model): ScreenModel/Field/Row/Region agent-facing screen contract"
```

---

## Task 2: The seam — `on_screen` observer + walk-ctx injection

Adds the observer field to `Host` and `WizardContext`, and makes the shell thread the
host observer into every walk's context. No screen emits a model yet, so behaviour is
unchanged (the default observer is a no-op).

**Files:**
- Modify: `src/clonway_cockpit/registry.py` (add `WizardContext.on_screen`)
- Modify: `src/clonway_cockpit/shell.py` (add `Host.on_screen`; inject into walk ctx in `_open_capability`)
- Test: `tests/test_seam.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seam.py
from __future__ import annotations

from dataclasses import replace

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState
from clonway_cockpit.walk import BlastRadius, Precondition, make_walk_handler


def test_host_on_screen_defaults_to_noop():
    captured: list[ScreenModel] = []
    host = shell.Host(
        capture_state=lambda: CockpitState(tenant_name="C"),
        build_walk_ctx=lambda *a, **k: None,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )
    # Default observer is callable and a no-op (does not raise).
    host.on_screen(ScreenModel(kind="home"))
    assert captured == []


def test_shell_injects_on_screen_into_walk_ctx():
    """The shell must thread host.on_screen into the WizardContext it runs a walk with,
    so walk screens reach the same observer as home screens."""
    clear_capabilities()
    seen_ctx: list[WizardContext] = []

    def build_walk_ctx(screen, read_key, *, focus=None):
        ctx = WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )
        seen_ctx.append(ctx)
        return ctx

    def _run(ctx: WizardContext) -> None:
        # Capture the ctx the shell actually passed to the handler.
        seen_ctx.append(ctx)

    register_capability(
        CapabilitySpec(key="demo", shelf="C", title="Demo", summary="s", equivalent_cli="x", run=_run)
    )
    captured: list[ScreenModel] = []
    state = CockpitState(tenant_name="C")
    host = shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=build_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
        on_screen=captured.append,
    )

    class _Screen:
        def update(self, r):  # noqa: ANN001
            pass

    def _keys(seq):
        buf = list(seq)
        return lambda: buf.pop(0) if buf else "q"

    # Open shelf C (single spec → opens directly), which runs the handler, then quit.
    shell.run_cockpit(host, read_key=_keys(["c", "q"]), screen=_Screen())
    # The handler-received ctx (last appended) carries the host observer.
    handler_ctx = seen_ctx[-1]
    assert handler_ctx.on_screen is captured.append
    clear_capabilities()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_seam.py -q`
Expected: FAIL — `TypeError: Host.__init__() got an unexpected keyword argument 'on_screen'` (and `WizardContext` has no `on_screen`).

- [ ] **Step 3a: Add `on_screen` to `WizardContext`**

In `src/clonway_cockpit/registry.py`, add the import and the field. At the top with the other imports:

```python
from clonway_cockpit.model import ScreenModel
```

Inside `@dataclass(frozen=True) class WizardContext`, after the existing `focus` field, add:

```python
    # Optional observer the cockpit threads in so a walk's screens are emitted as
    # ScreenModels (for the agent driver). None = not emitting (console/test callers).
    on_screen: Callable[[ScreenModel], None] | None = None
```

(`Callable` is already imported in `registry.py`.)

- [ ] **Step 3b: Add `on_screen` to `Host` and inject it into the walk ctx**

In `src/clonway_cockpit/shell.py`, add the imports near the top:

```python
from dataclasses import replace
from clonway_cockpit.model import ScreenModel
```

(`dataclass`/`field` are already imported; add `replace` to that line or as shown.)

In `@dataclass(frozen=True) class Host`, after the `handle_extra_key` field, add:

```python
    # Observer the shell calls with the ScreenModel for every screen it draws (home,
    # shelf menu) and threads into each walk's WizardContext so walk screens emit too.
    # Default no-op so existing Host constructions are byte-identical and the live
    # cockpit pays nothing.
    on_screen: Callable[[ScreenModel], None] = field(default=lambda model: None)
```

In `_open_capability`, change the walk-run branch so the ctx carries the observer:

```python
    if spec.run is not None:
        ctx = host.build_walk_ctx(screen, read_key, focus=focus)
        ctx = replace(ctx, on_screen=host.on_screen)
        try:
            spec.run(ctx)
        except shellout.ShellOut:
            raise
        except Exception as e:  # noqa: BLE001 — a walk crash must NOT kill the cockpit
            _show(
                screen,
                r.render_walk_result(
                    spec.title, ok=False, message=f"{spec.title} hit an error — {e}"
                ),
                read_key,
            )
        return
```

(Only the first two lines of the branch change — `ctx = host.build_walk_ctx(...)` then `ctx = replace(ctx, on_screen=host.on_screen)`, then `spec.run(ctx)`. The rest is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_seam.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite regression (nothing should have changed for existing behaviour)**

Run: `uv run pytest -q`
Expected: all existing tests still PASS.

- [ ] **Step 6: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy src`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/clonway_cockpit/registry.py src/clonway_cockpit/shell.py tests/test_seam.py
git commit -m "feat(shell): on_screen observer on Host + WizardContext, threaded into walks"
```

---

## Task 3: Home screen model + parity + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py` (add `_selection_id`, `_home_actions`, `model_cockpit_screen`)
- Modify: `src/clonway_cockpit/shell.py` (emit the home model in `_home`)
- Test: `tests/test_screen_models.py`

- [ ] **Step 1: Write the failing parity test**

```python
# tests/test_screen_models.py
from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render
from clonway_cockpit.registry import CapabilitySpec
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

_PILLS = (
    Pill("Xero", "synced", "06:45", "ok", "xero"),
    Pill("Lloyds", "synced", "06:45", "ok", "lloyds"),
)


def _text(frame) -> str:
    con = Console(record=True, width=120)
    con.print(frame)
    return con.export_text()


def _cursored_line_has(txt: str, label: str) -> bool:
    return any("❯" in line and label in line for line in txt.splitlines())


def test_home_model_parity_and_selection():
    state = CockpitState(
        tenant_name="Clonway",
        app_label="xbook",
        pills=_PILLS,
        needs=(NeedsItem("Bills overdue", "2 bills", "warn", "schedule-bills"),),
    )
    specs = [
        CapabilitySpec(
            key="sb", shelf="C", title="Schedule bills", summary="plan", equivalent_cli="xbook bills"
        )
    ]
    selection = ("shelf", "C")
    m = render.model_cockpit_screen(state, specs, selection=selection, extra_regions=None)
    txt = _text(render.render_cockpit_screen(state, specs, selection=selection))

    assert m.kind == "home"
    # Every row label the model claims is actually on the rendered screen (no drift).
    for region in m.regions:
        for row in region.rows:
            assert row.label in txt, f"model row {row.label!r} not in render"
    # The selection id maps to a real row, and that row is the cursored one on screen.
    assert m.selection == "shelf:C"
    sel_label = next(r.label for reg in m.regions for r in reg.rows if r.id == m.selection)
    assert _cursored_line_has(txt, sel_label)
    # The pills and needs are present as semantic rows.
    pill_ids = {r.id for reg in m.regions if reg.role == "pulse" for r in reg.rows}
    assert pill_ids == {"pill:0", "pill:1"}
    need_ids = {r.id for reg in m.regions if reg.role == "needs" for r in reg.rows}
    assert need_ids == {"need:0"}
    assert m.meta["app_label"] == "xbook"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_screen_models.py::test_home_model_parity_and_selection -q`
Expected: FAIL — `AttributeError: module 'clonway_cockpit.render' has no attribute 'model_cockpit_screen'`

- [ ] **Step 3: Implement the builder + helpers in `render.py`**

Add the `ScreenModel` imports near the top of `render.py`:

```python
from clonway_cockpit.model import Field as MField
from clonway_cockpit.model import Region as MRegion
from clonway_cockpit.model import Row as MRow
from clonway_cockpit.model import ScreenModel
```

(Aliased to `M*` so they don't clash with Rich's `Text`/`Table` style names already in scope.)

Add these functions at the end of `render.py`:

```python
def _selection_id(selection: tuple[str, object] | None) -> str | None:
    """Map the shell's ``(kind, ref)`` selection tuple to a stable Row id."""
    if not selection:
        return None
    kind, ref = selection
    return f"{kind}:{ref}"


def _home_actions(state: CockpitState) -> list[str]:
    """The keys the home loop honours — a deterministic, stable hint list."""
    letters = list(state.shelves) if state.shelves is not None else list(SHELVES)
    acts = ["up", "down", "left", "right", "enter", "/", "?", "r", "q", "backspace"]
    acts += [letter.lower() for letter in letters]
    acts += [str(i + 1) for i in range(min(9, len(state.needs)))]
    return acts


def model_cockpit_screen(
    state: CockpitState,
    specs: list[CapabilitySpec],
    *,
    selection: tuple[str, object] | None = None,
    extra_regions: list[RenderableType] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_cockpit_screen`. Same inputs; structured out.

    Worker ``extra_regions`` are arbitrary Rich renderables (worker-owned), so they
    are not semanticised here — their count is recorded in ``meta`` and they become
    structured when the worker adopts the model (M3)."""
    present = {s.shelf for s in specs}
    shelf_map = state.shelves or SHELVES
    sel_id = _selection_id(selection)
    pulse_rows = [
        MRow(
            id=f"pill:{i}",
            label=p.label,
            fields=[
                MField("status", p.status, "status"),
                MField("detail", p.detail),
                MField("level", p.level, "status"),
            ],
            selected=sel_id == f"pill:{i}",
        )
        for i, p in enumerate(state.pills)
    ]
    needs_rows = [
        MRow(
            id=f"need:{i}",
            label=n.title,
            fields=[MField("detail", n.detail), MField("level", n.level, "status")],
            selected=sel_id == f"need:{i}",
        )
        for i, n in enumerate(state.needs)
    ]
    toolkit_rows = [
        MRow(
            id=f"shelf:{letter}",
            label=shelf_map[letter],
            enabled=letter in present,
            selected=sel_id == f"shelf:{letter}",
        )
        for letter in shelf_map
    ]
    meta: dict = {
        "app_label": state.app_label,
        "tenant_name": state.tenant_name,
        "date_label": state.date_label,
        "time_label": state.time_label,
        "extra_regions": len(extra_regions or []),
    }
    if state.breadcrumb:
        meta["breadcrumb"] = list(state.breadcrumb)
    return ScreenModel(
        kind="home",
        title=state.app_label,
        regions=[
            MRegion("pulse", "pulse", rows=pulse_rows),
            MRegion("needs", "needs you", rows=needs_rows),
            MRegion("toolkit", state.toolkit_label, rows=toolkit_rows),
        ],
        selection=sel_id,
        actions=_home_actions(state),
        meta=meta,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_screen_models.py::test_home_model_parity_and_selection -q`
Expected: PASS

- [ ] **Step 5: Emit the home model from the shell**

In `src/clonway_cockpit/shell.py`, in `_home`, replace the render block inside the
`if dirty and not keys.pending():` guard with:

```python
        if dirty and not keys.pending():
            caps = host.get_capabilities()
            extra = host.extra_regions(state)
            screen.update(
                r.render_cockpit_screen(
                    state,
                    caps,
                    selection=items[sel],
                    extra_regions=extra,
                )
            )
            host.on_screen(
                r.model_cockpit_screen(
                    state, caps, selection=items[sel], extra_regions=extra
                )
            )
            dirty = False
```

(Previously `host.get_capabilities()` / `host.extra_regions(state)` were inlined in the
`render_cockpit_screen` call; hoisting them to locals avoids calling them twice and
keeps the render byte-identical.)

- [ ] **Step 6: Add a shell-emit test (home model reaches the observer)**

Append to `tests/test_screen_models.py`:

```python
def test_home_model_emitted_via_run_cockpit():
    from clonway_cockpit import shell, usage
    from clonway_cockpit.model import ScreenModel

    captured: list[ScreenModel] = []
    state = CockpitState(tenant_name="Clonway", pills=_PILLS)
    host = shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=lambda *a, **k: None,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
        on_screen=captured.append,
    )

    class _Screen:
        def update(self, frame):  # noqa: ANN001
            pass

    def _keys(seq):
        buf = list(seq)
        return lambda: buf.pop(0) if buf else "q"

    shell.run_cockpit(host, read_key=_keys(["q"]), screen=_Screen())
    assert captured, "no home model emitted"
    assert captured[0].kind == "home"
```

- [ ] **Step 7: Run the new test + full suite**

Run: `uv run pytest tests/test_screen_models.py -q && uv run pytest -q`
Expected: new tests PASS; full suite PASS (render byte-identical, no regression).

- [ ] **Step 8: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy src`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models.py
git commit -m "feat(render): model_cockpit_screen + emit home ScreenModel from the shell"
```

---

## Task 4: Shelf-menu model + parity + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py` (add `model_menu`)
- Modify: `src/clonway_cockpit/shell.py` (emit the menu model in `_shelf`)
- Test: `tests/test_screen_models.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models.py`:

```python
def test_menu_model_parity():
    title = "Compliance & reports"
    options = [("1", "Loans", "term loans"), ("2", "Insurance", "policies")]
    m = render.model_menu(title, options, selected=1)
    txt = _text(render.render_menu(title, options, selected=1))

    assert m.kind == "shelf_menu"
    assert m.title == title
    rows = m.regions[0].rows
    # Two option rows + a trailing Back row.
    assert [row.id for row in rows] == ["option:1", "option:2", "back"]
    for row in rows:
        assert row.label in txt
    # selected=1 → the second option is the cursored row.
    assert m.selection == "option:2"
    assert _cursored_line_has(txt, "Insurance")


def test_menu_model_back_selected():
    options = [("1", "Loans", "term loans")]
    m = render.model_menu("X", options, selected=1)  # index == len(options) → Back
    assert m.selection == "back"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_screen_models.py::test_menu_model_parity -q`
Expected: FAIL — `AttributeError: ... has no attribute 'model_menu'`

- [ ] **Step 3: Implement `model_menu` in `render.py`**

Add at the end of `render.py`:

```python
def model_menu(
    title: str,
    options: list[tuple[str, str, str]],
    *,
    label: str = "browse",
    selected: int | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_menu`. ``options`` is ``(key, title, summary)``;
    a trailing ``back`` row mirrors the rendered Back option. ``selected`` indexes the
    options, or ``len(options)`` for the Back row (matching the render)."""
    rows = [
        MRow(
            id=f"option:{key}",
            label=otitle,
            fields=[MField("summary", summary)],
            selected=selected == i,
        )
        for i, (key, otitle, summary) in enumerate(options)
    ]
    rows.append(MRow(id="back", label="Back", selected=selected == len(options)))
    sel_id: str | None = None
    if selected is not None:
        sel_id = "back" if selected == len(options) else f"option:{options[selected][0]}"
    return ScreenModel(
        kind="shelf_menu",
        title=title,
        regions=[MRegion("menu", label, rows=rows)],
        selection=sel_id,
        actions=["up", "down", "enter", "q"] + [key for key, _, _ in options],
        meta={"label": label},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_screen_models.py::test_menu_model_parity tests/test_screen_models.py::test_menu_model_back_selected -q`
Expected: PASS

- [ ] **Step 5: Emit the menu model from `_shelf`**

In `src/clonway_cockpit/shell.py`, inside the `_shelf` while-loop, immediately after the
existing `screen.update(r.render_menu(...))` line, add the emit:

```python
        screen.update(r.render_menu(menu_title, options, selected=sel, opens=opens, peak=peak))
        host.on_screen(r.model_menu(menu_title, options, selected=sel))
```

(`render_menu`'s `opens`/`peak` are the usage-notch decoration — not semantic — so the
model omits them. `label` defaults to "browse" in both, matching the rendered header.)

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS (render unchanged).

- [ ] **Step 7: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy src`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models.py
git commit -m "feat(render): model_menu + emit shelf-menu ScreenModel"
```

---

## Task 5: Walk preflight model + parity + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py` (add `model_preflight`)
- Modify: `src/clonway_cockpit/walk.py` (emit the preflight model)
- Test: `tests/test_screen_models.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models.py`:

```python
def test_preflight_model_parity():
    from clonway_cockpit.registry import BlastRadius
    from clonway_cockpit.walk import Precondition

    br = BlastRadius(
        summary="Posts a bill payment batch",
        details=("Creates 3 spend-money transactions", "Does NOT email anyone"),
        reversible="Reversible: void the batch in Xero",
    )
    preconds = [
        Precondition("Xero connected", True, "token fresh"),
        Precondition("No stale lock", False, "lock held"),
    ]
    kw = dict(
        title="Schedule bills",
        blast_radius=br,
        preconditions=preconds,
        equivalent_cli="xbook bills schedule",
        progress="step 1 of 4",
        ready=False,
        remedy=None,
    )
    m = render.model_preflight(**kw)
    txt = _text(render.render_preflight(**kw))

    assert m.kind == "walk.preflight"
    assert m.title == "Schedule bills"
    # Precondition rows mirror state (enabled == ok).
    pre = next(reg for reg in m.regions if reg.role == "preconditions")
    assert [(row.label, row.enabled) for row in pre.rows] == [
        ("Xero connected", True),
        ("No stale lock", False),
    ]
    for row in pre.rows:
        assert row.label in txt
    # Blast-radius detail lines are present as change rows.
    changes = next(reg for reg in m.regions if reg.role == "changes")
    assert [row.label for row in changes.rows] == list(br.details)
    assert m.meta["equivalent_cli"] == "xbook bills schedule"
    assert m.meta["ready"] is False
    assert m.meta["progress"] == "step 1 of 4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_screen_models.py::test_preflight_model_parity -q`
Expected: FAIL — `AttributeError: ... has no attribute 'model_preflight'`

- [ ] **Step 3: Implement `model_preflight` in `render.py`**

Add at the end of `render.py`:

```python
def model_preflight(
    *,
    title: str,
    blast_radius: BlastRadius,
    preconditions: list,
    equivalent_cli: str,
    progress: str = "",
    ready: bool = True,
    remedy: object | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_preflight`. Mirrors its keyword inputs."""
    changes = [MRow(id=f"change:{i}", label=d) for i, d in enumerate(blast_radius.details)]
    precond_rows = [
        MRow(
            id=f"precond:{i}",
            label=p.label,
            fields=[MField("ok", str(p.ok), "status"), MField("detail", p.detail)],
            enabled=p.ok,
        )
        for i, p in enumerate(preconditions)
    ]
    if ready:
        actions = ["enter", "y", "n"]
    elif remedy is not None:
        actions = [remedy.key, "back"]
    else:
        actions = ["any"]
    meta: dict = {
        "equivalent_cli": equivalent_cli,
        "progress": progress,
        "ready": ready,
        "blast_radius_summary": blast_radius.summary,
        "reversible": blast_radius.reversible,
        "remedy": {"key": remedy.key, "label": remedy.label} if remedy is not None else None,
    }
    return ScreenModel(
        kind="walk.preflight",
        title=title,
        regions=[
            MRegion("what_this_does", "what this does", text=blast_radius.summary),
            MRegion("changes", "what changes", rows=changes, text=blast_radius.reversible or None),
            MRegion("preconditions", "preconditions", rows=precond_rows),
        ],
        actions=actions,
        meta=meta,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_screen_models.py::test_preflight_model_parity -q`
Expected: PASS

- [ ] **Step 5: Emit the preflight model from `walk.py`**

In `src/clonway_cockpit/walk.py`, add the imports near the top (after the existing
`from clonway_cockpit import keys, render`):

```python
from clonway_cockpit.model import ScreenModel
```

Add a small emit helper after `_present`:

```python
def _emit(ctx: WizardContext, model: ScreenModel) -> None:
    """Publish a screen's semantic model to the cockpit observer, if one is bound."""
    if ctx.on_screen is not None:
        ctx.on_screen(model)
```

In `preflight()`, replace the `_present(ctx, render.render_preflight(...))` call (the
block that passes `title=…, blast_radius=…, preconditions=…, equivalent_cli=…,
progress=progress, ready=ready, remedy=remedy`) with a shared-kwargs build that renders
*and* emits:

```python
    pf = dict(
        title=title,
        blast_radius=blast_radius,
        preconditions=preconditions,
        equivalent_cli=equivalent_cli,
        progress=progress,
        ready=ready,
        remedy=remedy,
    )
    _present(ctx, render.render_preflight(**pf))
    _emit(ctx, render.model_preflight(**pf))
```

(The recursive `preflight(...)` call after a remedy re-runs this block, so the
re-checked preconditions emit a fresh model automatically — no extra change needed.)

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy src`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/walk.py tests/test_screen_models.py
git commit -m "feat(walk): model_preflight + emit preflight ScreenModel"
```

---

## Task 6: Walk result model + parity + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py` (add `model_walk_result`)
- Modify: `src/clonway_cockpit/walk.py` (emit the result model in `run_walk`, both ok + error paths)
- Test: `tests/test_screen_models.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models.py`:

```python
def test_walk_result_model_parity():
    kw = dict(
        title="Schedule bills",
        ok=True,
        message="Posted 3 bills\nBatch ref BP-204",
        links=[("Bill BP-204", "https://go.xero.com/bp204")],
    )
    m = render.model_walk_result(**kw)
    txt = _text(render.render_walk_result(**kw))

    assert m.kind == "walk.result"
    assert m.title == "Schedule bills"
    assert m.meta["ok"] is True
    assert m.meta["message"] == "Posted 3 bills\nBatch ref BP-204"
    assert m.meta["links"] == [{"label": "Bill BP-204", "url": "https://go.xero.com/bp204"}]
    assert "Posted 3 bills" in txt


def test_walk_result_model_failure():
    m = render.model_walk_result(title="X", ok=False, message="boom")
    assert m.meta["ok"] is False
    assert m.meta["links"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_screen_models.py::test_walk_result_model_parity -q`
Expected: FAIL — `AttributeError: ... has no attribute 'model_walk_result'`

- [ ] **Step 3: Implement `model_walk_result` in `render.py`**

Add at the end of `render.py`:

```python
def model_walk_result(
    title: str,
    *,
    ok: bool,
    message: str,
    links: list[tuple[str, str]] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_walk_result`."""
    link_dicts = [{"label": lbl, "url": url} for lbl, url in (links or [])]
    return ScreenModel(
        kind="walk.result",
        title=title,
        regions=[MRegion("result", "", text=message)],
        actions=["any"],
        meta={"ok": ok, "message": message, "links": link_dicts},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_screen_models.py::test_walk_result_model_parity tests/test_screen_models.py::test_walk_result_model_failure -q`
Expected: PASS

- [ ] **Step 5: Emit the result model from `run_walk`**

In `src/clonway_cockpit/walk.py`, in `run_walk`, the error path currently is:

```python
        if not result.ok:
            _present(ctx, render.render_walk_result(title, ok=False, message=result.message))
            _await(ctx)
            return
```

Change it to also emit:

```python
        if not result.ok:
            _present(ctx, render.render_walk_result(title, ok=False, message=result.message))
            _emit(ctx, render.model_walk_result(title, ok=False, message=result.message))
            _await(ctx)
            return
```

And the success path at the end of `run_walk`:

```python
    _present(
        ctx,
        render.render_walk_result(
            title,
            ok=True,
            message=bag.get("summary") or "Done.",
            links=bag.get("result_links"),
        ),
    )
    _emit(
        ctx,
        render.model_walk_result(
            title,
            ok=True,
            message=bag.get("summary") or "Done.",
            links=bag.get("result_links"),
        ),
    )
    _await(ctx)
```

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy src`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/walk.py tests/test_screen_models.py
git commit -m "feat(walk): model_walk_result + emit result ScreenModel (ok + error)"
```

---

## Task 7: `CockpitDriver` — in-process headless driver

**Files:**
- Create: `src/clonway_cockpit/agent.py`
- Test: `tests/test_agent_driver.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_agent_driver.py
from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, Pill
from clonway_cockpit.walk import BlastRadius, Precondition, make_walk_handler

_PILLS = (Pill("Xero", "synced", "06:45", "ok", "xero"),)


def _walk_ctx(screen, read_key, *, focus=None):
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


def _host(state: CockpitState) -> shell.Host:
    return shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )


def test_driver_records_home_model():
    d = CockpitDriver(_host(CockpitState(tenant_name="Clonway", pills=_PILLS)), keys=["q"])
    stream = d.run()
    assert stream, "no screens captured"
    assert stream[0].kind == "home"
    assert d.last.kind == "home"


def test_driver_drives_into_a_walk_preflight():
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="demo",
            shelf="C",
            title="Demo walk",
            summary="s",
            equivalent_cli="x",
            run=make_walk_handler(
                title="Demo",
                steps=[],
                blast_radius=BlastRadius("does a thing"),
                preconditions_fn=lambda ctx: [Precondition("ready", True)],
                equivalent_cli="x",
            ),
        )
    )
    # Open shelf C (single spec → opens the walk directly), then cancel the preflight,
    # then quit.
    d = CockpitDriver(_host(CockpitState(tenant_name="Clonway")), keys=["c", "n", "q"])
    stream = d.run()
    kinds = [s.kind for s in stream]
    assert "walk.preflight" in kinds, kinds
    pre = next(s for s in stream if s.kind == "walk.preflight")
    assert pre.title == "Demo"
    assert pre.to_dict()["kind"] == "walk.preflight"  # JSON-serialisable
    clear_capabilities()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_driver.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clonway_cockpit.agent'`

- [ ] **Step 3: Implement `CockpitDriver`**

```python
# src/clonway_cockpit/agent.py
"""In-process headless driver for the cockpit.

``CockpitDriver`` runs the real shell loop (``shell.run_cockpit``) with a scripted
key sequence and a no-op screen, installing the ``on_screen`` observer so it records
the ``ScreenModel`` stream the loop emits. It is the non-brittle test harness and the
in-process core the subprocess ``--agent`` protocol (M2) is built on top of.

Driving is scripted (a fixed key list) rather than interactive ``send()`` stepping;
interactive stepping arrives with the M2 stdio protocol, which needs a thread/queue
pump. For verification — drive a known path, assert on the recorded models — scripted
keys match the existing framework test harness exactly."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from clonway_cockpit import shell
from clonway_cockpit.model import ScreenModel
from rich.console import RenderableType


class _NullScreen:
    """A screen sink that renders nothing — the driver reads models, not pixels."""

    def update(self, renderable: RenderableType) -> None:
        return None


class CockpitDriver:
    """Drive the cockpit headlessly and record the ScreenModel stream it emits."""

    def __init__(self, host: shell.Host, keys: Iterable[str] | None = None) -> None:
        self._stream: list[ScreenModel] = []
        self._host = replace(host, on_screen=self._stream.append)
        self._keys: list[str] = list(keys or [])

    def _read_key(self) -> str:
        # Out of scripted keys → 'q' so every nested loop terminates (matches the
        # framework test harness's _keys helper).
        return self._keys.pop(0) if self._keys else "q"

    def run(self) -> list[ScreenModel]:
        """Run the full home loop with the scripted keys; return the recorded stream."""
        shell.run_cockpit(self._host, read_key=self._read_key, screen=_NullScreen())
        return self._stream

    @property
    def stream(self) -> list[ScreenModel]:
        return self._stream

    @property
    def last(self) -> ScreenModel:
        return self._stream[-1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_driver.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Full suite + lint + typecheck**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: all PASS / no errors.

- [ ] **Step 6: Commit**

```bash
git add src/clonway_cockpit/agent.py tests/test_agent_driver.py
git commit -m "feat(agent): CockpitDriver — headless scripted driver recording the ScreenModel stream"
```

---

## Task 8: Document the `Row.id` contract + model overview

**Files:**
- Create: `docs/agent-screen-model.md`

- [ ] **Step 1: Write the doc**

```markdown
# The agent screen model

`clonway_cockpit.model.ScreenModel` is the structured, JSON-serialisable description
of a cockpit screen that agents read and assert against (via `Host.on_screen` or
`clonway_cockpit.agent.CockpitDriver`). The human cockpit still renders Rich
renderables; the model is built from the same inputs by the `model_*` functions in
`render.py`, and parity tests keep the two in agreement.

## `Row.id` — a semi-public contract

Agents key on `Row.id`. Treat these as stable; changing one is a breaking change for
any agent script that asserts on it.

| Screen (`ScreenModel.kind`) | Row ids |
|---|---|
| `home` | `pill:<i>`, `need:<i>`, `shelf:<LETTER>` |
| `shelf_menu` | `option:<key>`, `back` |
| `walk.preflight` | `change:<i>`, `precond:<i>` |
| `walk.result` | (prose region, no rows) |

`ScreenModel.selection` is the id of the currently-cursored row (or `null`).
`ScreenModel.actions` is a best-effort list of keys/verbs the screen honours.
`ScreenModel.meta` carries screen-specific facts (e.g. preflight `ready`/`equivalent_cli`,
result `ok`/`links`).

## Driving headlessly

```python
from clonway_cockpit.agent import CockpitDriver
driver = CockpitDriver(host, keys=["c", "n", "q"])  # open shelf C, cancel preflight, quit
stream = driver.run()
assert any(s.kind == "walk.preflight" for s in stream)
```

## Scope

M1 covers home, shelf menu, walk preflight, walk result. Follow-on (M1-rest): progress,
doctor, filter, note, capability card, the confirm screens, help. Worker shelf-report
screens and the walk review/apply screen adopt the model in M3.
```

- [ ] **Step 2: Commit**

```bash
git add docs/agent-screen-model.md
git commit -m "docs: agent screen model + Row.id semi-public contract"
```

---

## Final verification

- [ ] **Run the whole gate:**

Run: `make check`
Expected: lint, format-check, typecheck, and the full test suite all pass.

- [ ] **Confirm the live cockpit is byte-identical:** the existing `tests/test_shell.py`
  / `tests/test_walk.py` golden text assertions still pass unchanged (proves no human
  visual regression). They were run as part of `make check` above.

---

## Self-review

**Spec coverage (against the M1 milestone in `2026-06-06-agent-navigable-cockpit-design.md`):**
- `ScreenModel` contract → Task 1. ✓
- Render produces a model (model+parity interpretation, per approved decision) → Tasks 3–6. ✓
- Seam emits the model (`Host.on_screen` + `WizardContext.on_screen`, threaded into walks) → Task 2; emitted in Tasks 3–6. ✓
- `CockpitDriver` in-process + new test harness → Task 7; parity tests replace `export_text` substring asserts for the migrated screens → Tasks 3–6. ✓
- `Row.id` documented as a semi-public contract → Task 8. ✓
- Framework-only (no xbook/xops changes) → confirmed; all paths under `src/clonway_cockpit/` + `tests/`. ✓
- Deferred deliberately (stated in Scope note): other primitives (M1-rest), subprocess `--agent` protocol (M2), shelf reports (M3), write-gate handshake (M4), interactive `CockpitDriver.send()` (M2). Spec's "unstructured fallback" is not needed in M1 (every screen we emit here has a concrete model) and lands with M1-rest/M3.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Every code step shows complete code; every command shows the exact invocation + expected outcome.

**Type/name consistency:** `model_cockpit_screen`/`model_menu`/`model_preflight`/`model_walk_result`, `_selection_id`, `_home_actions`, `_emit`, `CockpitDriver.run/stream/last`, `Host.on_screen`, `WizardContext.on_screen`, `Field/Row/Region/ScreenModel` (aliased `M*` inside `render.py`) used consistently across tasks. `ScreenModel.to_dict()` defined in Task 1, used in Task 7. `_emit` defined in Task 5, reused in Task 6.
