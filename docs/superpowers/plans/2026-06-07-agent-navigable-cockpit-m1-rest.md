# Agent-navigable cockpit — M1-rest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the remaining framework cockpit primitives (capability card, the three progress screens, note, help, doctor, the two confirm screens, filter) a `model_*` semantic twin + parity test + emit at their draw site, add an `unstructured` fallback `ScreenModel`, and a contract test that fails if a framework screen ships without a model — completing the M1 framework so an agent gets structure from *every* framework screen, not just the home/menu/walk path.

**Architecture:** Pure-additive, mirroring M1 exactly. Each `model_*(...)` builder mirrors its `render_*(...)` signature and returns a `ScreenModel`; a **parity test** builds both from the same inputs and asserts every model row label appears in the rendered text and the model's `selection` matches the ❯-cursored row. Emit happens at each shell/walk draw site via `host.on_screen(...)` / `_emit(ctx, ...)`, right next to the existing `screen.update(...)`/`_present(...)`. Progress screens (animated, redrawn ~8×/s) emit through the `animate_*` helpers with **semantic-change dedup** so the stream carries one model per meaningful change, not per frame. The human cockpit stays byte-identical (no `render_*` body is touched; all defaults are no-ops).

**Tech Stack:** Python ≥3.12, Rich (render only), stdlib dataclasses. Gates: `make check` = `ruff check .` + `ruff format --check .` + `mypy src` + `pytest -q`.

**Repo gotchas (carry forward from M1):**
- A **ruff autofix-on-save hook strips unused imports** — add an import only in the same edit that uses it. All builders below reuse render.py's existing `MRow`/`MField`/`MRegion`/`ScreenModel`/`Console` imports; walk.py and shell.py already import `ScreenModel`. **No new imports are required** in src — keep it that way.
- `mypy src` is enforced; unannotated defaults are `Any`. `model_remedy_confirm(remedy)` / `model_doctor_confirm(fix)` mirror the untyped `render_*` confirm signatures — leave their params unannotated to match (a `walk.Remedy` / `doctor.Fix`), exactly as `model_preflight(remedy=None)` does.
- Parity uses a fixed-width `Console(record=True, width=120)`; the page frame caps body width ~112 cols. Keep test labels short enough not to wrap.

**Where each model is emitted (the draw sites, all in `shell.py` unless noted):**

| Model | render fn | draw site |
|---|---|---|
| `model_note` | `render_note` | `_ack_snooze_need` (`shell.py:518`), `_activate_need` (`shell.py:549`) |
| `model_capability_card` | `render_capability_card` | `_open_capability` reference-only branch (`shell.py:666`) |
| `model_help` | `render_help` | `_home` `?` branch (`shell.py:433`) |
| `model_remedy_confirm` | `render_remedy_confirm` | `walk.preflight` (`walk.py:375`) |
| `model_doctor_confirm` | `render_doctor_confirm` | `_run_doctor_fix` (`shell.py:763`) |
| `model_doctor` | `render_doctor` | `_doctor` loop (`shell.py:700`) |
| `model_filter` | `render_filter` | `_filter` loop (`shell.py:821`) |
| `model_walk_progress` | `render_walk_progress` | `_run_doctor_fix` plain branch (`shell.py:774`) |
| `model_sync_progress` | `render_sync_progress` | `animate_until_done` via `run_with_progress` (doctor "Sync now") |
| `model_staged_progress` | `render_staged_progress` | `animate_staged` (worker-driven; emit param wired, adoption is M3) |
| `model_unstructured` | (any) | doctor-unconfigured renderable (`shell.py:688`, `shell.py:752`) |

---

## File Structure

- **Modify `src/clonway_cockpit/render.py`** — append the new `model_*` builders after `model_walk_result` (the existing model section, ~line 1276). All use existing imports.
- **Modify `src/clonway_cockpit/walk.py`** — emit `model_remedy_confirm` in `preflight`; thread an optional `emit`/`model_frame` through `_run_animated`, `animate_until_done`, `animate_staged` (semantic-change dedup).
- **Modify `src/clonway_cockpit/shell.py`** — add `host.on_screen(...)` at the note/card/help/doctor/doctor-confirm/filter/progress/unconfigured draw sites; thread `emit` into `run_with_progress`; wire `_run_doctor_fix`.
- **Create `tests/test_screen_models_rest.py`** — parity tests for every new model (mirrors `tests/test_screen_models.py`).
- **Create `tests/test_seam_rest.py`** — emit tests: drive each new draw site and assert the model lands in the stream.
- **Create `tests/test_contract.py`** — completeness guard: every page-framing `render_*` has a registered `model_*`; `model_unstructured` produces `kind="unstructured"`.

Each task is TDD: write the failing test, run it red, implement the minimal builder/wiring, run it green, commit.

---

## Task 1: `model_note` + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py` (append after `model_walk_result`)
- Modify: `src/clonway_cockpit/shell.py:518`, `src/clonway_cockpit/shell.py:549`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_screen_models_rest.py` with the shared helpers + the note test:

```python
"""Parity + emit tests for the M1-rest ScreenModel builders (model_* in render.py).

Same contract as test_screen_models.py: build the model and the renderable from the
SAME inputs, render the renderable to text, and assert the two agree — every model row
label is on the rendered screen, and the model's selection matches the ❯-cursored row.
"""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render


def _text(frame) -> str:  # noqa: ANN001
    con = Console(record=True, width=120)
    con.print(frame)
    return con.export_text()


def _cursored_line_has(txt: str, label: str) -> bool:
    return any("❯" in line and label in line for line in txt.splitlines())


# --- Task 1: note --------------------------------------------------------------


def test_note_model_parity():
    kw = dict(title="Acknowledged", detail="Bills overdue cleared for today")
    m = render.model_note(**kw)
    txt = _text(render.render_note(**kw))

    assert m.kind == "note"
    assert m.title == "Acknowledged"
    prose = next(reg for reg in m.regions if reg.role == "prose")
    assert prose.text == "Bills overdue cleared for today"
    assert "Bills overdue cleared for today" in txt
    assert "Acknowledged" in txt
    assert m.actions == ["any"]
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py::test_note_model_parity -q`
Expected: FAIL — `AttributeError: module 'clonway_cockpit.render' has no attribute 'model_note'`

- [ ] **Step 3: Implement `model_note`**

Append to `src/clonway_cockpit/render.py`:

```python
def model_note(title: str, detail: str) -> ScreenModel:
    """The semantic twin of :func:`render_note` — a titled prose leaf, any key returns."""
    return ScreenModel(
        kind="note",
        title=title,
        regions=[MRegion("prose", "", text=detail)],
        actions=["any"],
        meta={"detail": detail},
    )
```

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py::test_note_model_parity -q`
Expected: PASS

- [ ] **Step 5: Emit at both note draw sites**

In `src/clonway_cockpit/shell.py`, `_ack_snooze_need` (currently `shell.py:518`), change the final line:

```python
    message = cb(need) or verb
    host.on_screen(r.model_note(verb, message))
    _show(screen, r.render_note(verb, message), read_key)
```

In `_activate_need` (currently `shell.py:549`), change the `else` branch:

```python
    else:
        host.on_screen(r.model_note(need.title, need.detail))
        _show(screen, r.render_note(need.title, need.detail), read_key)
```

- [ ] **Step 6: Write the failing emit test**

Create `tests/test_seam_rest.py` with shared host helpers + the note emit test:

```python
"""Emit tests for the M1-rest draw sites: drive the real shell/walk path with scripted
keys and a no-op screen, then assert the new model lands in the recorded stream."""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, NeedsItem, Pill


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


def _kinds(stream: list[ScreenModel]) -> list[str]:
    return [m.kind for m in stream]


# --- Task 1: note emit ---------------------------------------------------------


def test_note_emitted_when_opening_a_plain_need():
    # A need with no capability_key drills to a note (its title/detail). Land the
    # cursor on it (it is the only actionable row) and press enter.
    state = CockpitState(
        tenant_name="Clonway",
        needs=(NeedsItem("Read me", "just a note", "warn", ""),),
    )
    driver = CockpitDriver(_host(state), keys=["\r", "x", "q"])  # enter need → any key → quit
    stream = driver.run()
    notes = [m for m in stream if m.kind == "note"]
    assert notes, f"no note emitted; saw {_kinds(stream)}"
    assert notes[0].title == "Read me"
```

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_note_emitted_when_opening_a_plain_need -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render): model_note + emit note ScreenModel from the shell"
```

---

## Task 2: `model_capability_card` + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/shell.py:666`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 2: capability card ---------------------------------------------------


def test_capability_card_model_parity():
    from clonway_cockpit.registry import CapabilitySpec

    spec = CapabilitySpec(
        key="loans",
        shelf="F",
        title="Term loans",
        summary="Review the loan schedule",
        equivalent_cli="xbook loans review",
    )
    m = render.model_capability_card(spec)
    txt = _text(render.render_capability_card(spec))

    assert m.kind == "card"
    assert m.title == "Term loans"
    what = next(reg for reg in m.regions if reg.role == "what_this_does")
    assert what.text == "Review the loan schedule"
    assert "Review the loan schedule" in txt
    assert m.meta["equivalent_cli"] == "xbook loans review"
    assert "xbook loans review" in txt
    assert m.actions == ["any"]
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py::test_capability_card_model_parity -q`
Expected: FAIL — no attribute `model_capability_card`

- [ ] **Step 3: Implement `model_capability_card`**

Append to `src/clonway_cockpit/render.py`:

```python
def model_capability_card(spec: CapabilitySpec) -> ScreenModel:
    """The semantic twin of :func:`render_capability_card` — a reference-only
    capability (no walk yet): title, what-it-does prose, the equivalent-CLI."""
    return ScreenModel(
        kind="card",
        title=spec.title,
        regions=[MRegion("what_this_does", "what this does", text=spec.summary)],
        actions=["any"],
        meta={"equivalent_cli": spec.equivalent_cli, "summary": spec.summary},
    )
```

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py::test_capability_card_model_parity -q`
Expected: PASS

- [ ] **Step 5: Emit at the card draw site**

In `src/clonway_cockpit/shell.py`, `_open_capability` final line (currently `shell.py:666`):

```python
    # reference-only: no handler, just the equivalent-CLI card
    host.on_screen(r.model_capability_card(spec))
    _show(screen, r.render_capability_card(spec), read_key)
```

- [ ] **Step 6: Write the failing emit test**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 2: capability card emit ----------------------------------------------


def test_capability_card_emitted_for_reference_only_spec():
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="loans",
            shelf="F",
            title="Term loans",
            summary="Review the loan schedule",
            equivalent_cli="xbook loans review",
        )  # run=None → reference-only card
    )
    state = CockpitState(tenant_name="Clonway")
    # Shelf F has one spec → opens directly into the card; any key returns; quit.
    driver = CockpitDriver(_host(state), keys=["f", "x", "q"])
    stream = driver.run()
    clear_capabilities()
    cards = [m for m in stream if m.kind == "card"]
    assert cards, f"no card emitted; saw {_kinds(stream)}"
    assert cards[0].title == "Term loans"
```

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_capability_card_emitted_for_reference_only_spec -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render): model_capability_card + emit card ScreenModel"
```

---

## Task 3: `model_help` + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/shell.py:433`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 3: help --------------------------------------------------------------


def test_help_model_parity_default_lines():
    m = render.model_help()
    txt = _text(render.render_help())

    assert m.kind == "help"
    assert m.title == "Keys"
    rows = m.regions[0].rows
    assert rows, "help model has no rows"
    for row in rows:
        assert row.label in txt, f"help description {row.label!r} not rendered"
        key = next(f.value for f in row.fields if f.label == "keys")
        assert key in txt
    assert m.actions == ["any"]


def test_help_model_parity_worker_lines():
    lines = (("⏎", "open worker"), ("r", "refresh"))
    m = render.model_help(lines)
    txt = _text(render.render_help(lines))
    assert [row.label for row in m.regions[0].rows] == ["open worker", "refresh"]
    assert "open worker" in txt
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py -k help -q`
Expected: FAIL — no attribute `model_help`

- [ ] **Step 3: Implement `model_help`**

The default `help_lines` must match `render_help`'s default body exactly. Factor the default once so render and model never drift. Append to `src/clonway_cockpit/render.py`:

```python
# The default home help body (key, description) — shared by render_help and
# model_help so the rendered help and its semantic twin never drift.
_DEFAULT_HELP_LINES: tuple[tuple[str, str], ...] = (
    ("↑ ↓", "move the highlight"),
    ("← →", "jump between the two columns (pulse pills · toolkit shelves)"),
    ("⏎", "open the item · sync the selected pulse pill"),
    ("1–9", "jump to a needs-you item"),
    ("A–G", "open a toolkit shelf"),
    ("/", "filter capabilities by name"),
    ("r", "refresh the cockpit"),
    ("q / esc", "back · quit"),
)


def model_help(
    help_lines: tuple[tuple[str, str], ...] | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_help`. ``help_lines`` (key, description)
    pairs override the default body, mirroring ``render_help``."""
    rows_src = list(help_lines) if help_lines is not None else list(_DEFAULT_HELP_LINES)
    rows = [
        MRow(id=f"help:{i}", label=desc, fields=[MField("keys", k)])
        for i, (k, desc) in enumerate(rows_src)
    ]
    return ScreenModel(
        kind="help",
        title="Keys",
        regions=[MRegion("help", "Keys", rows=rows)],
        actions=["any"],
    )
```

Then point `render_help`'s default at the shared tuple so they can never drift. In `render_help`, replace the inline default list:

```python
    rows = list(help_lines) if help_lines is not None else list(_DEFAULT_HELP_LINES)
```

(`_DEFAULT_HELP_LINES` is defined above `render_help` — move the constant definition above `render_help` if your file order requires it, or keep `render_help` reading the module-level constant. The constant must be defined before both functions.)

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py -k help -q`
Expected: PASS (both help tests)

Also run the existing help render test to confirm the refactor is byte-identical:
Run: `uv run pytest tests/ -k help -q`
Expected: PASS

- [ ] **Step 5: Emit at the help draw site**

In `src/clonway_cockpit/shell.py`, `_home` `?` branch (currently `shell.py:433`):

```python
        elif low == "?":
            host.on_screen(r.model_help(state.help_lines))
            _show(screen, r.render_help(state.help_lines), read_key)
```

- [ ] **Step 6: Write the failing emit test**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 3: help emit ---------------------------------------------------------


def test_help_emitted_on_question_key():
    state = CockpitState(tenant_name="Clonway", pills=(Pill("Xero", "synced", "06:45", "ok", "xero"),))
    driver = CockpitDriver(_host(state), keys=["?", "x", "q"])
    stream = driver.run()
    helps = [m for m in stream if m.kind == "help"]
    assert helps, f"no help emitted; saw {_kinds(stream)}"
    assert helps[0].title == "Keys"
```

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_help_emitted_on_question_key -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render): model_help + shared default help lines + emit help ScreenModel"
```

---

## Task 4: `model_remedy_confirm` + `model_doctor_confirm` (the two confirm screens)

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/walk.py:375`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity tests**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 4: confirm screens ---------------------------------------------------


def test_remedy_confirm_model_parity():
    from clonway_cockpit.walk import Remedy

    remedy = Remedy(key="u", label="clear the stale apply lock", action=lambda: "cleared")
    m = render.model_remedy_confirm(remedy)
    txt = _text(render.render_remedy_confirm(remedy))

    assert m.kind == "confirm"
    assert m.title == "Clear the stale apply lock"
    assert "Clear the stale apply lock" in txt
    assert m.meta["confirm_of"] == "remedy"
    assert m.meta["key"] == "u"
    assert m.actions == ["enter", "y"]


def test_doctor_confirm_model_parity():
    from clonway_cockpit.doctor import Fix

    fix = Fix(title="Remove stale lock", cmd="xbook unlock", confirm=True, run=lambda: "ok")
    m = render.model_doctor_confirm(fix)
    txt = _text(render.render_doctor_confirm(fix))

    assert m.kind == "confirm"
    assert m.title == "Remove stale lock"
    assert "Remove stale lock" in txt
    assert m.meta["confirm_of"] == "doctor_fix"
    assert m.meta["cmd"] == "xbook unlock"
    assert "xbook unlock" in txt
    assert m.actions == ["enter", "y"]
```

- [ ] **Step 2: Run them red**

Run: `uv run pytest tests/test_screen_models_rest.py -k confirm -q`
Expected: FAIL — no attribute `model_remedy_confirm`

- [ ] **Step 3: Implement both confirm models**

Append to `src/clonway_cockpit/render.py`. Both params are intentionally unannotated to mirror the untyped `render_*` confirm signatures (a `walk.Remedy` / `doctor.Fix`):

```python
def model_remedy_confirm(remedy) -> ScreenModel:  # noqa: ANN001 — mirrors render_remedy_confirm
    """The semantic twin of :func:`render_remedy_confirm` — the one-key gate before
    an inline pre-flight remedy runs. ``remedy`` is a ``walk.Remedy``."""
    label = remedy.label.capitalize()
    return ScreenModel(
        kind="confirm",
        title=label,
        regions=[MRegion("prose", "", text=f"{label}?")],
        actions=["enter", "y"],
        meta={"confirm_of": "remedy", "key": remedy.key, "label": remedy.label},
    )


def model_doctor_confirm(fix) -> ScreenModel:  # noqa: ANN001 — mirrors render_doctor_confirm
    """The semantic twin of :func:`render_doctor_confirm` — the one-key gate before a
    state-changing Doctor fix runs. ``fix`` is a ``doctor.Fix``."""
    return ScreenModel(
        kind="confirm",
        title=fix.title,
        regions=[MRegion("prose", "", text=f"{fix.title}?")],
        actions=["enter", "y"],
        meta={"confirm_of": "doctor_fix", "cmd": fix.cmd},
    )
```

- [ ] **Step 4: Run them green**

Run: `uv run pytest tests/test_screen_models_rest.py -k confirm -q`
Expected: PASS (both)

- [ ] **Step 5: Emit the remedy confirm in `walk.preflight`**

In `src/clonway_cockpit/walk.py`, the inline-remedy branch (currently `walk.py:375`):

```python
                _present(ctx, render.render_remedy_confirm(remedy))
                _emit(ctx, render.model_remedy_confirm(remedy))
```

(The doctor confirm is emitted in Task 5, alongside the doctor model wiring.)

- [ ] **Step 6: Write the failing emit test (remedy confirm via a driven preflight)**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 4: remedy confirm emit ----------------------------------------------


def test_remedy_confirm_emitted_in_preflight():
    from clonway_cockpit.registry import BlastRadius
    from clonway_cockpit.walk import Precondition, Remedy, preflight

    captured: list[ScreenModel] = []
    remedy = Remedy(key="u", label="clear the stale apply lock", action=lambda: "cleared")
    preconds = [Precondition("No stale lock", False, "lock held", remedy=remedy)]
    ctx = WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        present=lambda frame: None,
        # press the remedy key, then cancel the confirm with a non-y key
        read_key=iter(["u", "n"]).__next__,
        on_screen=captured.append,
    )
    preflight(
        ctx,
        title="Schedule bills",
        blast_radius=BlastRadius(summary="posts a batch"),
        preconditions=preconds,
        equivalent_cli="xbook bills",
        recheck=lambda: preconds,
    )
    confirms = [m for m in captured if m.kind == "confirm"]
    assert confirms, f"no remedy confirm emitted; saw {[m.kind for m in captured]}"
    assert confirms[0].meta["confirm_of"] == "remedy"
```

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_remedy_confirm_emitted_in_preflight -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/walk.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render,walk): model_remedy_confirm + model_doctor_confirm + emit remedy confirm"
```

---

## Task 5: `model_doctor` + emit (doctor screen + doctor confirm)

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/shell.py:700`, `src/clonway_cockpit/shell.py:763`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 5: doctor ------------------------------------------------------------


def test_doctor_model_parity_and_selection():
    from clonway_cockpit.doctor import Fix, Probe

    probes = [
        Probe("Xero auth", "ok", "token fresh", None),
        Probe("Apply lock", "warn", "stale lock present", None),
    ]
    fixes = [
        Fix(title="Remove stale lock", cmd="xbook unlock", run=lambda: "ok"),
        Fix(title="Re-auth browser", cmd="xbook auth", run=None),  # display-only
    ]
    kw = dict(probes=probes, fixes=fixes, selected=0, app_label="xbook")
    m = render.model_doctor(**kw)
    txt = _text(render.render_doctor(**kw))

    assert m.kind == "doctor"
    assert m.title == "xbook doctor"
    probe_reg = next(reg for reg in m.regions if reg.role == "probes")
    assert [row.label for row in probe_reg.rows] == ["Xero auth", "Apply lock"]
    for row in probe_reg.rows:
        assert row.label in txt
    fix_reg = next(reg for reg in m.regions if reg.role == "fixes")
    assert [row.label for row in fix_reg.rows] == ["Remove stale lock", "Re-auth browser"]
    # The runnable fix is selectable + enabled; the display-only one is disabled.
    runnable = next(row for row in fix_reg.rows if row.id == "fix:0")
    assert runnable.enabled and runnable.selected
    display_only = next(row for row in fix_reg.rows if row.label == "Re-auth browser")
    assert not display_only.enabled
    assert m.selection == "fix:0"
    assert _cursored_line_has(txt, "Remove stale lock")
    assert m.meta == {"app_label": "xbook", "warnings": 1, "errors": 0, "ok": False}
    assert m.actions[:4] == ["up", "down", "enter", "q"]


def test_doctor_model_no_runnable_fixes_is_back_only():
    from clonway_cockpit.doctor import Fix, Probe

    probes = [Probe("All green", "ok", "fine", None)]
    fixes = [Fix(title="Re-auth browser", cmd="xbook auth", run=None)]
    m = render.model_doctor(probes=probes, fixes=fixes, selected=None)
    assert m.selection is None
    assert m.actions == ["q"]
    assert m.meta["ok"] is True
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py -k doctor -q`
Expected: FAIL — no attribute `model_doctor`

- [ ] **Step 3: Implement `model_doctor`**

The verdict (warnings/errors) is computed inline exactly as `render_doctor` does — no `doctor` import needed (avoids the import the render module deliberately keeps under TYPE_CHECKING). Append to `src/clonway_cockpit/render.py`:

```python
def model_doctor(
    probes: list[Probe],
    fixes: list[Fix],
    *,
    selected: int | None = None,
    usage: dict | None = None,
    specs: list[CapabilitySpec] | None = None,
    app_label: str = "xbook",
) -> ScreenModel:
    """The semantic twin of :func:`render_doctor`. ``selected`` indexes the RUNNABLE
    fixes (those with a ``run``), matching the render. The read-only "what you reach
    for" usage block is telemetry display, not navigable structure, so it is not
    semanticised here (its presence is flagged in ``meta``)."""
    probe_rows = [
        MRow(
            id=f"probe:{i}",
            label=p.name,
            fields=[MField("level", p.level, "status"), MField("detail", p.detail)],
        )
        for i, p in enumerate(probes)
    ]
    fix_rows: list[MRow] = []
    run_i = 0
    for i, f in enumerate(fixes):
        if f.run is not None:
            fix_rows.append(
                MRow(
                    id=f"fix:{run_i}",
                    label=f.title,
                    fields=[MField("cmd", f.cmd)],
                    selected=selected == run_i,
                    enabled=True,
                )
            )
            run_i += 1
        else:
            fix_rows.append(
                MRow(
                    id=f"fix:display:{i}",
                    label=f.title,
                    fields=[MField("cmd", f.cmd), MField("note", f.note)],
                    enabled=False,
                )
            )
    has_runnable = run_i > 0
    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    if has_runnable:
        actions = ["up", "down", "enter", "q"] + [str(n + 1) for n in range(run_i)]
        sel_id = f"fix:{selected}" if selected is not None else None
    else:
        actions = ["q"]
        sel_id = None
    return ScreenModel(
        kind="doctor",
        title=f"{app_label} doctor",
        regions=[
            MRegion("probes", "probes", rows=probe_rows),
            MRegion("fixes", "fixes", rows=fix_rows),
        ],
        selection=sel_id,
        actions=actions,
        meta={
            "app_label": app_label,
            "warnings": warns,
            "errors": errs,
            "ok": warns == 0 and errs == 0,
            **({"usage_present": True} if usage else {}),
        },
    )
```

Note: the `usage_present` key only appears when usage is truthy, so the `test_doctor_model_parity_and_selection` meta equality (usage omitted) holds. Confirm the test passes the meta `==` exactly.

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py -k doctor -q`
Expected: PASS (both)

- [ ] **Step 5: Emit the doctor model in the `_doctor` loop**

In `src/clonway_cockpit/shell.py`, `_doctor`, inside the `if dirty and not keys.pending():` block (currently `shell.py:700`), add the emit right after the `screen.update(...)`:

```python
        if dirty and not keys.pending():
            probes_arg = probes
            fixes_arg = fixes
            sel_arg = sel if runnable else None
            usage_arg = host.usage.load()
            specs_arg = host.get_capabilities()
            screen.update(
                r.render_doctor(
                    probes_arg,
                    fixes_arg,
                    selected=sel_arg,
                    usage=usage_arg,
                    specs=specs_arg,
                    app_label=host.app_label,
                )
            )
            host.on_screen(
                r.model_doctor(
                    probes_arg,
                    fixes_arg,
                    selected=sel_arg,
                    usage=usage_arg,
                    specs=specs_arg,
                    app_label=host.app_label,
                )
            )
            dirty = False
```

(Binding the args to locals avoids calling `host.usage.load()` / `host.get_capabilities()` twice and keeps render+model byte-aligned.)

- [ ] **Step 6: Emit the doctor confirm in `_run_doctor_fix`**

In `src/clonway_cockpit/shell.py`, `_run_doctor_fix` (currently `shell.py:763`):

```python
    if fix.confirm:
        host.on_screen(r.model_doctor_confirm(fix))
        screen.update(r.render_doctor_confirm(fix))
        if read_key() not in (keys.ENTER, "y", "Y"):
            return  # cancelled — the fix did NOT run
```

- [ ] **Step 7: Write the failing emit test**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 5: doctor emit -------------------------------------------------------


def test_doctor_emitted_when_opening_doctor():
    from clonway_cockpit.doctor import Probe

    probes = [Probe("Xero auth", "ok", "token fresh", None)]
    clear_capabilities()
    register_capability(
        CapabilitySpec(key="doctor", shelf="G", title="Doctor", summary="health", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: probes,
        doctor_fixes_for=lambda p: [],
    )
    # Shelf G has one spec (doctor) → opens directly; q exits doctor, q quits home.
    driver = CockpitDriver(host, keys=["g", "q", "q"])
    stream = driver.run()
    clear_capabilities()
    docs = [m for m in stream if m.kind == "doctor"]
    assert docs, f"no doctor model emitted; saw {_kinds(stream)}"
    assert docs[0].meta["ok"] is True
```

- [ ] **Step 8: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_doctor_emitted_when_opening_doctor -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render,shell): model_doctor + emit doctor + doctor-confirm ScreenModels"
```

---

## Task 6: `model_filter` + emit

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/shell.py:821`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/test_screen_models_rest.py`. The filter reads `.title`/`.summary` off each match, so the test uses a tiny stand-in matching the `_FilterRow` protocol:

```python
# --- Task 6: filter ------------------------------------------------------------


class _M:  # minimal _FilterRow: a title + a summary
    def __init__(self, title: str, summary: str) -> None:
        self.title = title
        self.summary = summary


def test_filter_model_parity_and_selection():
    matches = [_M("Schedule bills", "plan a batch"), _M("Clear payroll", "run payroll")]
    kw = dict(term="cl", matches=matches, selected=1, title="Find a tool")
    m = render.model_filter(**kw)
    txt = _text(render.render_filter(**kw))

    assert m.kind == "filter"
    assert m.title == "Find a tool"
    rows = m.regions[0].rows
    assert [row.id for row in rows] == ["match:0", "match:1"]
    for row in rows:
        assert row.label in txt
    assert m.selection == "match:1"
    assert _cursored_line_has(txt, "Clear payroll")
    assert m.meta["term"] == "cl"


def test_filter_model_no_match():
    m = render.model_filter("zzz", [], selected=None)
    assert m.regions[0].rows == []
    assert m.selection is None
    assert m.meta["term"] == "zzz"
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py -k filter -q`
Expected: FAIL — no attribute `model_filter`

- [ ] **Step 3: Implement `model_filter`**

Mirror `render_filter`'s caps (matches[:9]) and default title. Append to `src/clonway_cockpit/render.py`:

```python
def model_filter(
    term: str,
    matches: Sequence[_FilterRow],
    *,
    selected: int | None = None,
    title: str | None = None,
) -> ScreenModel:
    """The semantic twin of :func:`render_filter`. Lists the (capped at 9) matches —
    capabilities and/or needs — each a row keyed ``match:<i>``; mirrors the rendered
    Back/cap behaviour. ``selected`` indexes the shown matches."""
    shown = list(matches[:9])
    rows = [
        MRow(
            id=f"match:{i}",
            label=s.title,
            fields=[MField("summary", s.summary)],
            selected=selected == i,
        )
        for i, s in enumerate(shown)
    ]
    sel_id = f"match:{selected}" if selected is not None and shown else None
    return ScreenModel(
        kind="filter",
        title=title or "Find a tool",
        regions=[MRegion("matches", "", rows=rows)],
        selection=sel_id,
        actions=["up", "down", "enter", "esc", "backspace"],
        meta={"term": term},
    )
```

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py -k filter -q`
Expected: PASS (both)

- [ ] **Step 5: Emit in the `_filter` loop**

In `src/clonway_cockpit/shell.py`, `_filter`, alongside the `screen.update(...)` (currently `shell.py:821`):

```python
        screen.update(
            r.render_filter(
                term,
                matches,
                selected=(sel if matches else None),
                title=state.filter_title,
            )
        )
        host.on_screen(
            r.model_filter(
                term,
                matches,
                selected=(sel if matches else None),
                title=state.filter_title,
            )
        )
```

- [ ] **Step 6: Write the failing emit test**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 6: filter emit -------------------------------------------------------


def test_filter_emitted_on_slash():
    clear_capabilities()
    register_capability(
        CapabilitySpec(key="sb", shelf="C", title="Schedule bills", summary="plan", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    # / opens the filter; type "s"; esc closes filter; q quits home.
    driver = CockpitDriver(_host(state), keys=["/", "s", "\x1b", "q"])
    stream = driver.run()
    clear_capabilities()
    filters = [m for m in stream if m.kind == "filter"]
    assert filters, f"no filter emitted; saw {_kinds(stream)}"
    # The last filter frame (after typing 's') matched the registered capability.
    assert any(row.label == "Schedule bills" for f in filters for row in f.regions[0].rows)
```

(`\x1b` is ESC — `keys.ESC`. Confirm `keys.ESC == "\x1b"`; if it differs, import `keys` and use `keys.ESC`.)

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_filter_emitted_on_slash -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render,shell): model_filter + emit filter ScreenModel"
```

---

## Task 7: progress models (`model_walk_progress`, `model_sync_progress`, `model_staged_progress`)

Pure builders first (parity). Emit wiring is Task 8.

**Files:**
- Modify: `src/clonway_cockpit/render.py`
- Test: `tests/test_screen_models_rest.py`

- [ ] **Step 1: Write the failing parity tests**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 7: progress ----------------------------------------------------------


def test_walk_progress_model_parity():
    kw = dict(message="Posting batch…", progress="step 3 of 4")
    m = render.model_walk_progress(**kw)
    txt = _text(render.render_walk_progress(**kw))
    assert m.kind == "walk.progress"
    assert m.regions[0].text == "Posting batch…"
    assert "Posting batch…" in txt
    assert m.meta["message"] == "Posting batch…"
    assert m.meta["progress"] == "step 3 of 4"


def test_sync_progress_model_parity():
    lines = ("Fetching invoices", "Reconciling")
    m = render.model_sync_progress("Syncing Xero", lines=lines, elapsed=12)
    txt = _text(render.render_sync_progress("Syncing Xero", lines=lines, elapsed=12))
    assert m.kind == "walk.progress"
    assert m.meta["label"] == "Syncing Xero"
    assert m.meta["elapsed"] == 12
    assert [row.label for row in m.regions[0].rows] == list(lines)
    for line in lines:
        assert line in txt
    assert "Syncing Xero" in txt


def test_staged_progress_model_parity():
    from clonway_cockpit.walk import StageReporter

    reporter = StageReporter([("fetch", "Fetch data"), ("post", "Post batch")])
    reporter.done("fetch", "12 rows")
    reporter.start("post")
    stages = reporter.snapshot()
    m = render.model_staged_progress("Schedule bills", stages, elapsed=5, controls="q cancel")
    txt = _text(render.render_staged_progress("Schedule bills", stages, elapsed=5, controls="q cancel"))
    assert m.kind == "walk.progress"
    rows = m.regions[0].rows
    assert [row.id for row in rows] == ["stage:fetch", "stage:post"]
    assert [row.label for row in rows] == ["Fetch data", "Post batch"]
    for row in rows:
        assert row.label in txt
    assert m.meta["stages"][0]["status"] == "done"
    assert m.meta["stages"][1]["status"] == "active"
    assert m.actions == ["q"]  # cancellable
```

- [ ] **Step 2: Run them red**

Run: `uv run pytest tests/test_screen_models_rest.py -k progress -q`
Expected: FAIL — no attribute `model_walk_progress`

- [ ] **Step 3: Implement the three progress models**

The spinner `frame` is pure decoration, so the model builders omit it; `elapsed` is informative and rides in `meta`. Append to `src/clonway_cockpit/render.py`:

```python
def model_walk_progress(message: str, progress: str = "") -> ScreenModel:
    """The semantic twin of :func:`render_walk_progress` — a transient 'working…'
    leaf with no operator input."""
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("prose", "", text=message)],
        actions=[],
        meta={"message": message, "progress": progress},
    )


def model_sync_progress(
    label: str,
    *,
    latest: str = "",
    lines: tuple[str, ...] = (),
    elapsed: int = 0,
) -> ScreenModel:
    """The semantic twin of :func:`render_sync_progress`. The spinner ``frame`` is
    cosmetic and omitted; ``elapsed`` and the live-log ``lines`` carry the meaning."""
    rows = [MRow(id=f"log:{i}", label=ln) for i, ln in enumerate(lines)]
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("activity", label, rows=rows)],
        actions=[],
        meta={"label": label, "elapsed": elapsed, "latest": latest},
    )


def model_staged_progress(
    label: str,
    stages: Sequence,
    *,
    hint: str = "",
    elapsed: int = 0,
    controls: str = "",
) -> ScreenModel:
    """The semantic twin of :func:`render_staged_progress` — one row per stage with
    its status; ``controls`` (e.g. ``"q cancel"``) makes ``q`` an action."""
    rows = [
        MRow(
            id=f"stage:{st.key}",
            label=st.label,
            fields=[MField("status", st.status, "status"), MField("detail", st.detail)],
        )
        for st in stages
    ]
    return ScreenModel(
        kind="walk.progress",
        title="",
        regions=[MRegion("stages", label, rows=rows)],
        actions=["q"] if controls else [],
        meta={
            "label": label,
            "elapsed": elapsed,
            "hint": hint,
            "controls": controls,
            "stages": [
                {"key": s.key, "label": s.label, "status": s.status, "detail": s.detail}
                for s in stages
            ],
        },
    )
```

- [ ] **Step 4: Run them green**

Run: `uv run pytest tests/test_screen_models_rest.py -k progress -q`
Expected: PASS (all three)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/render.py tests/test_screen_models_rest.py
git commit -m "feat(render): model_walk_progress + model_sync_progress + model_staged_progress"
```

---

## Task 8: progress emit — thread `emit` through the animation helpers (dedup)

Animated progress redraws ~8×/s; emitting a model per frame would flood the stream. Emit **on semantic change** (ignoring the per-second `elapsed` tick): one model when the screen first appears, and again whenever the log lines / stage statuses change.

**Files:**
- Modify: `src/clonway_cockpit/walk.py` (`_run_animated`, `animate_until_done`, `animate_staged`)
- Modify: `src/clonway_cockpit/shell.py` (`run_with_progress`, `_run_doctor_fix`)
- Test: `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing emit test (staged dedup)**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 8: progress emit -----------------------------------------------------


def test_staged_progress_emits_one_model_per_stage_change():
    from clonway_cockpit import walk

    emitted: list[ScreenModel] = []

    def fn(reporter):
        reporter.start("fetch")
        reporter.done("fetch")
        reporter.start("post")
        reporter.done("post")
        return "done"

    # Deterministic time: clock advances 0,0,0…; sleep is a no-op; so the loop spins
    # purely on the worker finishing. emit fires on each distinct snapshot.
    walk.animate_staged(
        present=lambda frame: None,
        label="Schedule bills",
        fn=fn,
        stages=[("fetch", "Fetch data"), ("post", "Post batch")],
        emit=emitted.append,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        tick=0.0,
    )
    assert emitted, "no progress models emitted"
    assert all(m.kind == "walk.progress" for m in emitted)
    # Distinct stage-status signatures only — never two identical adjacent emits.
    sigs = [tuple((s["key"], s["status"]) for s in m.meta["stages"]) for m in emitted]
    assert all(a != b for a, b in zip(sigs, sigs[1:], strict=False)), f"duplicate emits: {sigs}"


def test_sync_progress_emits_through_run_with_progress():
    emitted: list[ScreenModel] = []
    shell.run_with_progress(
        screen=_NullScreenForTest(),
        label="Syncing",
        fn=lambda: "ok",
        emit=emitted.append,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        tick=0.0,
    )
    syncs = [m for m in emitted if m.kind == "walk.progress"]
    assert syncs, "no sync progress model emitted"
    assert syncs[0].meta["label"] == "Syncing"


class _NullScreenForTest:
    def update(self, frame) -> None:  # noqa: ANN001
        return None
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_seam_rest.py -k "staged_progress_emits or sync_progress_emits" -q`
Expected: FAIL — `animate_staged()` / `run_with_progress()` got an unexpected keyword argument `emit`

- [ ] **Step 3: Thread `emit` + `model_frame` through `_run_animated`**

In `src/clonway_cockpit/walk.py`, extend `_run_animated`'s signature and loop. Add two keyword params and a dedup of the emitted model (ignoring `elapsed`):

```python
def _run_animated[T](
    present: Callable[[RenderableType], None],
    fn: Callable[..., T],
    render_frame: Callable[[str, int], RenderableType],
    *,
    worker_arg: object | None,
    pass_arg: bool,
    tick: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll_cancel: Callable[[], bool] | None = None,
    model_frame: Callable[[int], ScreenModel] | None = None,
    emit: Callable[[ScreenModel], None] | None = None,
) -> T:
```

Inside the loop, after `present(render_frame(frame, elapsed))`, add the deduped emit. Track the last emitted signature in a local initialised before the loop:

```python
    thread = threading.Thread(target=_worker, daemon=True)
    started = clock()
    thread.start()
    i = 0
    last_sig: object = None
    while True:
        frame = render.SPINNER_FRAMES[i % len(render.SPINNER_FRAMES)]
        elapsed = int(clock() - started)
        present(render_frame(frame, elapsed))
        if emit is not None and model_frame is not None:
            model = model_frame(elapsed)
            # Dedup on everything but the per-second elapsed tick, so a steady
            # screen emits once and a stage transition emits exactly once.
            d = model.to_dict()
            d["meta"] = {k: v for k, v in d["meta"].items() if k != "elapsed"}
            sig = repr(d)
            if sig != last_sig:
                emit(model)
                last_sig = sig
        i += 1
        thread.join(timeout=tick)
        if not thread.is_alive():
            break
        if poll_cancel is not None:
            if poll_cancel():
                raise Cancelled
        else:
            sleep(tick)
```

- [ ] **Step 4: Forward `emit` from `animate_until_done` and `animate_staged`**

In `animate_until_done`, add `emit: Callable[[ScreenModel], None] | None = None` to the signature, and pass a `model_frame` + `emit` to `_run_animated`:

```python
    return _run_animated(
        present,
        fn,
        lambda frame, elapsed: render.render_sync_progress(label, frame, elapsed, lines=tuple(buf)),
        worker_arg=_log,
        pass_arg=_accepts_log,
        tick=tick,
        clock=clock,
        sleep=sleep,
        model_frame=lambda elapsed: render.model_sync_progress(
            label, lines=tuple(buf), elapsed=elapsed
        ),
        emit=emit,
    )
```

In `animate_staged`, add `emit: Callable[[ScreenModel], None] | None = None` to the signature, and pass:

```python
    return _run_animated(
        present,
        fn,
        lambda frame, elapsed: render.render_staged_progress(
            label,
            reporter.snapshot(),
            frame,
            elapsed,
            hint=hint,
            hint_after_s=hint_after_s,
            controls=controls,
        ),
        worker_arg=reporter,
        pass_arg=True,
        tick=tick,
        clock=clock,
        sleep=sleep,
        poll_cancel=poll,
        model_frame=lambda elapsed: render.model_staged_progress(
            label,
            reporter.snapshot(),
            hint=hint,
            elapsed=elapsed,
            controls=controls,
        ),
        emit=emit,
    )
```

- [ ] **Step 5: Forward `emit` from shell `run_with_progress`**

In `src/clonway_cockpit/shell.py`, `run_with_progress`, add `emit: Callable[[ScreenModel], None] | None = None` to the signature and forward it:

```python
def run_with_progress[T](
    screen: Screen,
    label: str,
    fn: Callable[[], T],
    *,
    tick: float = _PROGRESS_TICK,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[ScreenModel], None] | None = None,
) -> T:
    ...
    return walk.animate_until_done(
        screen.update, label, fn, tick=tick, clock=clock, sleep=sleep, emit=emit
    )
```

- [ ] **Step 6: Wire the doctor-fix progress sites in `_run_doctor_fix`**

In `src/clonway_cockpit/shell.py`, `_run_doctor_fix` (currently `shell.py:771`), emit at both the animated "Sync now" path and the plain working screen, plus the result:

```python
    try:
        if fix.title == "Sync now":
            msg = run_with_progress(screen, f"{fix.title}…", fix.run, emit=host.on_screen)
        else:
            host.on_screen(r.model_walk_progress(f"{fix.title}…"))
            screen.update(r.render_walk_progress(f"{fix.title}…"))
            msg = fix.run()
        ok = True
    except Exception as e:  # noqa: BLE001 — surface any failure as a clean result
        msg, ok = str(e), False
    host.on_screen(r.model_walk_result("Doctor", ok=ok, message=msg))
    screen.update(r.render_walk_result("Doctor", ok=ok, message=msg))
    read_key()
```

- [ ] **Step 7: Run the emit tests green**

Run: `uv run pytest tests/test_seam_rest.py -k "staged_progress_emits or sync_progress_emits" -q`
Expected: PASS

Run the existing walk/progress suite to confirm the animation refactor didn't regress:
Run: `uv run pytest tests/test_walk.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/walk.py src/clonway_cockpit/shell.py tests/test_seam_rest.py
git commit -m "feat(walk,shell): emit walk.progress ScreenModels with semantic-change dedup"
```

---

## Task 9: `model_unstructured` fallback + wire the doctor-unconfigured site

The design's error model: any screen not yet migrated emits `ScreenModel(kind="unstructured", …)` carrying the rendered text, so the driver still works and the model flags it isn't semantic. The framework's own unmigrated leaf is the worker-supplied doctor-unconfigured renderable.

**Files:**
- Modify: `src/clonway_cockpit/render.py`, `src/clonway_cockpit/shell.py:688`, `src/clonway_cockpit/shell.py:752`
- Test: `tests/test_screen_models_rest.py`, `tests/test_seam_rest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_screen_models_rest.py`:

```python
# --- Task 9: unstructured fallback --------------------------------------------


def test_unstructured_model_carries_rendered_text():
    renderable = render.render_note("Setup needed", "run xbook init first")
    m = render.model_unstructured(renderable, title="Setup needed")
    assert m.kind == "unstructured"
    assert m.title == "Setup needed"
    prose = next(reg for reg in m.regions if reg.role == "prose")
    assert "run xbook init first" in (prose.text or "")
    assert m.actions == ["any"]
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/test_screen_models_rest.py::test_unstructured_model_carries_rendered_text -q`
Expected: FAIL — no attribute `model_unstructured`

- [ ] **Step 3: Implement `model_unstructured`**

Append to `src/clonway_cockpit/render.py` (reuses the module's existing `Console` import):

```python
def model_unstructured(renderable: RenderableType, *, title: str = "") -> ScreenModel:
    """Fallback model for a screen not yet migrated to a ``model_*`` twin: capture
    the rendered text into a prose region and flag it explicitly as not-yet-semantic,
    so the driver still records a usable (if opaque) snapshot."""
    con = Console(record=True, width=_PANEL_WIDTH)
    con.print(renderable)
    return ScreenModel(
        kind="unstructured",
        title=title,
        regions=[MRegion("prose", "", text=con.export_text())],
        actions=["any"],
    )
```

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/test_screen_models_rest.py::test_unstructured_model_carries_rendered_text -q`
Expected: PASS

- [ ] **Step 5: Wire the two doctor-unconfigured sites**

In `src/clonway_cockpit/shell.py`, `_doctor` (currently `shell.py:687`):

```python
    try:
        report = host.doctor_build_report()
    except Exception:  # noqa: BLE001 — unconfigured/offline → setup hint, don't crash
        unconfigured = host.doctor_unconfigured_renderable()
        host.on_screen(r.model_unstructured(unconfigured, title="Doctor"))
        _show(screen, unconfigured, read_key)
        return
```

In `_rebuild_doctor_report` (currently `shell.py:749`):

```python
    try:
        return host.doctor_build_report()
    except Exception:  # noqa: BLE001 — became unconfigured/offline → setup hint, don't crash
        unconfigured = host.doctor_unconfigured_renderable()
        host.on_screen(r.model_unstructured(unconfigured, title="Doctor"))
        _show(screen, unconfigured, read_key)
        return None
```

- [ ] **Step 6: Write the failing emit test**

Append to `tests/test_seam_rest.py`:

```python
# --- Task 9: unstructured emit -------------------------------------------------


def test_unstructured_emitted_when_doctor_unconfigured():
    def boom():
        raise RuntimeError("not configured")

    clear_capabilities()
    register_capability(
        CapabilitySpec(key="doctor", shelf="G", title="Doctor", summary="health", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_report=boom,
        doctor_unconfigured_renderable=lambda: render.render_note("Setup", "run init"),
    )
    driver = CockpitDriver(host, keys=["g", "x", "q"])  # open doctor → any key → quit
    stream = driver.run()
    clear_capabilities()
    unstr = [m for m in stream if m.kind == "unstructured"]
    assert unstr, f"no unstructured model emitted; saw {_kinds(stream)}"
```

- [ ] **Step 7: Run the emit test green**

Run: `uv run pytest tests/test_seam_rest.py::test_unstructured_emitted_when_doctor_unconfigured -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/clonway_cockpit/render.py src/clonway_cockpit/shell.py tests/test_screen_models_rest.py tests/test_seam_rest.py
git commit -m "feat(render,shell): model_unstructured fallback + emit it for the doctor-unconfigured screen"
```

---

## Task 10: contract test — every framework screen has a model

A build-failing guard so a new framework primitive can't ship without a `model_*` twin (the "must-verify screen is still unstructured" guard, framework edition).

**Files:**
- Create: `tests/test_contract.py`

- [ ] **Step 1: Write the contract test**

Create `tests/test_contract.py`:

```python
"""Contract: every full-screen framework render primitive has a model_* twin.

A framework screen is a public ``render_*`` that frames a page via ``page()``. Each must
have a registered ``model_*`` builder, so an agent gets structure (not an ``unstructured``
fallback) from every framework screen. A new primitive that forgets its model fails here.
"""

from __future__ import annotations

import inspect

from clonway_cockpit import render

# render_* (page-framing) → its model_* twin. Sub-components (header/pulse/needs_you/
# toolkit/usage_section) and helpers don't frame a page, so they are not listed.
FRAMEWORK_SCREENS: dict[str, str] = {
    "render_cockpit_screen": "model_cockpit_screen",
    "render_menu": "model_menu",
    "render_capability_card": "model_capability_card",
    "render_preflight": "model_preflight",
    "render_remedy_confirm": "model_remedy_confirm",
    "render_walk_progress": "model_walk_progress",
    "render_sync_progress": "model_sync_progress",
    "render_staged_progress": "model_staged_progress",
    "render_walk_result": "model_walk_result",
    "render_note": "model_note",
    "render_help": "model_help",
    "render_doctor": "model_doctor",
    "render_doctor_confirm": "model_doctor_confirm",
    "render_filter": "model_filter",
}


def test_every_registered_screen_has_a_model():
    for render_fn, model_fn in FRAMEWORK_SCREENS.items():
        assert hasattr(render, render_fn), f"missing render fn {render_fn}"
        assert hasattr(render, model_fn), f"{render_fn} has no model builder {model_fn}"


def test_no_unregistered_page_framing_screen():
    """Any public render_* that frames a page() must be registered above, so a new
    framework primitive can't be added without a model twin."""
    page_screens: set[str] = set()
    for name, fn in inspect.getmembers(render, inspect.isfunction):
        if not name.startswith("render_"):
            continue
        try:
            src = inspect.getsource(fn)
        except OSError:  # pragma: no cover - source always available in-tree
            continue
        if "page(" in src:
            page_screens.add(name)
    missing = page_screens - set(FRAMEWORK_SCREENS)
    assert not missing, f"page-framing framework screens with no registered model: {missing}"


def test_unstructured_is_explicitly_flagged():
    m = render.model_unstructured(render.render_note("x", "y"))
    assert m.kind == "unstructured"
```

- [ ] **Step 2: Run it green**

Run: `uv run pytest tests/test_contract.py -q`
Expected: PASS (3 tests). If `test_no_unregistered_page_framing_screen` reports a screen, that screen genuinely lacks a model — add its model + register it, don't relax the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test(contract): every page-framing framework screen has a model twin"
```

---

## Task 11: docs + full gate + final verification

**Files:**
- Modify: `docs/agent-screen-model.md` (extend the Row.id / kind contract)

- [ ] **Step 1: Extend the contract doc**

Append to `docs/agent-screen-model.md` the new screen `kind`s and `Row.id` schemes introduced by M1-rest, so agents know the new contract surface:

```markdown
## M1-rest screens (framework primitives)

| kind | screen | Row.id scheme | key meta |
|------|--------|---------------|----------|
| `card` | reference-only capability | — (prose) | `equivalent_cli` |
| `note` | a titled note leaf | — (prose) | `detail` |
| `help` | the keys help | `help:<i>` (field `keys`) | — |
| `confirm` | remedy / doctor-fix gate | — (prose) | `confirm_of` (`remedy`\|`doctor_fix`) |
| `doctor` | the Doctor screen | `probe:<i>`, `fix:<n>` (runnable), `fix:display:<i>` | `warnings`, `errors`, `ok` |
| `filter` | type-to-filter | `match:<i>` | `term` |
| `walk.progress` | working / sync / staged | `log:<i>` (sync), `stage:<key>` (staged) | `label`, `elapsed`, `stages` |
| `unstructured` | not-yet-migrated screen | — (prose holds rendered text) | — |

`walk.progress` is emitted on **semantic change** (a new log line / a stage status
change), not per animation frame — `elapsed` ticks are not separate emits.
```

- [ ] **Step 2: Run the full gate**

Run: `make check`
Expected: `ruff check` clean, `ruff format --check` clean, `mypy src` clean, `pytest` all green (baseline 346 + the new M1-rest tests, ~30 added). If `ruff format` flags files, run `uv run ruff format .` and re-commit.

- [ ] **Step 3: Confirm the human cockpit is byte-identical**

The M1 invariant: no `render_*` body was modified except `render_help` (which now reads the extracted `_DEFAULT_HELP_LINES` constant — semantically identical output). Verify the existing render/golden tests are untouched and green:

Run: `uv run pytest tests/test_shell.py tests/test_walk.py tests/test_render.py -q`
Expected: PASS (no edits to these files; behaviour unchanged).

- [ ] **Step 4: Commit docs + any format fixups**

```bash
git add docs/agent-screen-model.md
git commit -m "docs: M1-rest screen kinds + Row.id contract"
```

- [ ] **Step 5: Ship**

Open the PR against `main` with the M1-rest summary + test plan (use the `ship-pr` skill / repo conventions; no `Co-Authored-By`/🤖 trailers per repo rule).

---

## Self-Review (run after drafting; fix inline)

**Spec coverage** (handoff's M1-rest = "model+parity+emit for the remaining framework primitives" + unstructured fallback + contract test):

| Primitive (handoff) | model | parity test | emit | task |
|---|---|---|---|---|
| capability card | ✅ | ✅ | ✅ | 2 |
| progress (walk/sync/staged) | ✅×3 | ✅×3 | ✅ (dedup) | 7,8 |
| note | ✅ | ✅ | ✅ | 1 |
| help | ✅ | ✅ | ✅ | 3 |
| doctor | ✅ | ✅ | ✅ | 5 |
| confirm ×2 | ✅×2 | ✅×2 | ✅ | 4,5 |
| filter | ✅ | ✅ | ✅ | 6 |
| unstructured fallback | ✅ | ✅ | ✅ | 9 |
| contract test | — | — | ✅ | 10 |

**Type consistency:** `model_*` signatures mirror their `render_*` exactly (verified against render.py). `model_remedy_confirm`/`model_doctor_confirm`/`model_doctor` params match the untyped/typed render counterparts. `emit`/`model_frame` keyword params added consistently down `run_with_progress` → `animate_until_done`/`animate_staged` → `_run_animated`. Row.id schemes (`probe:`, `fix:`, `fix:display:`, `match:`, `help:`, `stage:`, `log:`) are unique and documented.

**Placeholder scan:** every code step carries complete code; every run step has an exact command + expected outcome. No TODOs.

**Byte-identical guard:** only `render_help` is touched (extract default lines to a shared constant — same output); all other `render_*` bodies are unchanged; emits sit beside existing draws. The contract + golden tests in Task 11 prove it.
