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


# --- Task 4: shelf menu --------------------------------------------------------


def test_menu_model_parity():
    title = "Compliance & reports"
    options = [("1", "Loans", "term loans"), ("2", "Insurance", "policies")]
    m = render.model_menu(title, options, selected=1)
    txt = _text(render.render_menu(title, options, selected=1))

    assert m.kind == "shelf_menu"
    assert m.title == title
    rows = m.regions[0].rows
    assert [row.id for row in rows] == ["option:1", "option:2", "back"]
    for row in rows:
        assert row.label in txt
    assert m.selection == "option:2"
    assert _cursored_line_has(txt, "Insurance")


def test_menu_model_back_selected():
    options = [("1", "Loans", "term loans")]
    m = render.model_menu("X", options, selected=1)  # index == len(options) → Back
    assert m.selection == "back"


# --- Task 5: walk preflight ----------------------------------------------------


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
    pre = next(reg for reg in m.regions if reg.role == "preconditions")
    assert [(row.label, row.enabled) for row in pre.rows] == [
        ("Xero connected", True),
        ("No stale lock", False),
    ]
    for row in pre.rows:
        assert row.label in txt
    changes = next(reg for reg in m.regions if reg.role == "changes")
    assert [row.label for row in changes.rows] == list(br.details)
    assert m.meta["equivalent_cli"] == "xbook bills schedule"
    assert m.meta["ready"] is False
    assert m.meta["progress"] == "step 1 of 4"


# --- Task 6: walk result -------------------------------------------------------


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
