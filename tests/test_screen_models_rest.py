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
