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
