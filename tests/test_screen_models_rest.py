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
    txt = _text(
        render.render_staged_progress("Schedule bills", stages, elapsed=5, controls="q cancel")
    )
    assert m.kind == "walk.progress"
    rows = m.regions[0].rows
    assert [row.id for row in rows] == ["stage:fetch", "stage:post"]
    assert [row.label for row in rows] == ["Fetch data", "Post batch"]
    for row in rows:
        assert row.label in txt
    assert m.meta["stages"][0]["status"] == "done"
    assert m.meta["stages"][1]["status"] == "active"
    assert m.actions == ["q"]  # cancellable


# --- Task 9: unstructured fallback --------------------------------------------


def test_unstructured_model_carries_rendered_text():
    renderable = render.render_note("Setup needed", "run xbook init first")
    m = render.model_unstructured(renderable, title="Setup needed")
    assert m.kind == "unstructured"
    assert m.title == "Setup needed"
    prose = next(reg for reg in m.regions if reg.role == "prose")
    assert "run xbook init first" in (prose.text or "")
    assert m.actions == ["any"]
