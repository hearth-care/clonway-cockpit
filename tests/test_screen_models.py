"""Parity + emit tests for the agent ScreenModel builders (``model_*`` in render.py).

Each parity test builds the model and the matching renderable from the SAME inputs,
renders the renderable to text, and asserts the two agree — every row label the model
claims is on the rendered screen, and the model's selection matches the ❯-cursored row.
This is the no-drift guarantee without rewriting the (untouched) ``render_*`` functions.
"""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import CapabilitySpec
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

_PILLS = (
    Pill("Xero", "synced", "06:45", "ok", "xero"),
    Pill("Lloyds", "synced", "06:45", "ok", "lloyds"),
)


def _text(frame) -> str:  # noqa: ANN001
    con = Console(record=True, width=120)
    con.print(frame)
    return con.export_text()


def _cursored_line_has(txt: str, label: str) -> bool:
    return any("❯" in line and label in line for line in txt.splitlines())


def _keys(seq):  # noqa: ANN001, ANN202
    buf = list(seq)
    return lambda: buf.pop(0) if buf else "q"


class _Screen:
    def update(self, frame) -> None:  # noqa: ANN001
        pass


# --- Task 3: home --------------------------------------------------------------


def test_home_model_parity_and_selection():
    state = CockpitState(
        tenant_name="Clonway",
        app_label="xbook",
        pills=_PILLS,
        needs=(NeedsItem("Bills overdue", "2 bills", "warn", "schedule-bills"),),
    )
    specs = [
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="plan",
            equivalent_cli="xbook bills",
        )
    ]
    selection = ("shelf", "C")
    m = render.model_cockpit_screen(state, specs, selection=selection, extra_regions=None)
    txt = _text(render.render_cockpit_screen(state, specs, selection=selection))

    assert m.kind == "home"
    for region in m.regions:
        for row in region.rows:
            assert row.label in txt, f"model row {row.label!r} not in render"
    assert m.selection == "shelf:C"
    sel_label = next(r.label for reg in m.regions for r in reg.rows if r.id == m.selection)
    assert _cursored_line_has(txt, sel_label)
    pill_ids = {r.id for reg in m.regions if reg.role == "pulse" for r in reg.rows}
    assert pill_ids == {"pill:0", "pill:1"}
    need_ids = {r.id for reg in m.regions if reg.role == "needs" for r in reg.rows}
    assert need_ids == {"need:0"}
    assert m.meta["app_label"] == "xbook"


def test_home_model_emitted_via_run_cockpit():
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
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=_Screen())
    assert captured, "no home model emitted"
    assert captured[0].kind == "home"
