"""Render-primitive tests — the framework chrome shared by every worker screen
(header / pulse / needs-you / toolkit / menu / walk-result / doctor / usage).

``CockpitState`` is built directly here: the framework spine carries only the
data shape, not the worker's ``capture()`` (which read a status report)."""

from __future__ import annotations

from datetime import UTC

from rich.console import Console

from clonway_cockpit import render
from clonway_cockpit.registry import CapabilitySpec
from clonway_cockpit.state import CockpitState, NeedsItem, Pill


def _state() -> CockpitState:
    return CockpitState(
        tenant_name="Clonway Care",
        date_label="Fri 23 May 2026",
        time_label="06:45",
        tenant_id="9b40…",
        pills=(
            Pill("Xero", "synced", "06:45", "ok", "xero"),
            Pill("Lloyds", "synced", "06:45", "ok", "lloyds"),
            Pill("Revolut", "synced", "06:45", "ok", "revolut"),
        ),
        needs=(NeedsItem("Bills overdue", "3 · £4,210", "error", "schedule-bills", "overdue"),),
    )


def _capture(renderable) -> str:
    con = Console(record=True, width=120)
    con.print(renderable)
    return con.export_text()


def test_cockpit_screen_has_three_regions():
    shelves = [
        CapabilitySpec(
            key="doctor",
            shelf="F",
            title="Doctor",
            summary="health",
            equivalent_cli="uv run xbook doctor",
        ),
    ]
    out = _capture(render.render_cockpit_screen(_state(), shelves))
    assert "Clonway Care" in out
    assert "pulse" in out and "needs you" in out and "toolkit" in out
    assert "Bills overdue" in out  # ranked needs-you item


def test_header_app_label_defaults_to_xbook():
    """The header product name defaults to "xbook" so the worker that extracted
    this framework is unchanged."""
    out = _capture(render.render_header(_state()))
    assert "xbook" in out


def test_header_app_label_is_configurable():
    """A worker (the Fleet Cockpit) can override the header product name."""
    state = CockpitState(
        tenant_name="Clonway Care",
        app_label="Clonway Office",
        date_label="Fri 23 May 2026",
        time_label="06:45",
    )
    out = _capture(render.render_header(state))
    assert "Clonway Office" in out
    assert "xbook" not in out


def test_render_uses_no_emoji():
    out = _capture(render.render_cockpit_screen(_state(), []))
    assert all(ord(ch) < 0x1F000 for ch in out)  # no emoji codepoints


def test_home_gutter_cues_disambiguate_grammars():
    """H-2 — each home section's dim gutter carries a one-word verb cue so the
    three nav grammars read distinctly."""
    out = _capture(render.render_cockpit_screen(_state(), []))
    assert "⏎ sync" in out  # the pulse gutter cue
    assert "A–G" in out  # the toolkit gutter cue


def test_home_drops_vestigial_trailing_caret():
    """P-4 — the home screen no longer ends with a lone '▸' shell-prompt line
    under the legend. The legend itself still opens with '▸ Press'."""
    out = _capture(render.render_cockpit_screen(_state(), []))
    assert out.rstrip().splitlines()[-1].strip() != "▸"


def _segments(renderable):
    con = Console(width=120)
    return list(con.render(renderable, con.options))


def test_apply_key_is_escalated():
    """H-3 — the irreversible apply token carries the amber-inverse style (bold
    black on the accent), different IN KIND from the _KEY_STYLE keys."""
    seg = next(s for s in _segments(render._apply_key()) if s.text.strip() == "[a]pply" and s.style)
    assert seg.style.bold is True
    assert seg.style.bgcolor is not None and seg.style.bgcolor.name == render.ACCENT


def test_pill_glyph_varies_by_severity():
    """P-1 — severity travels in the glyph, not colour alone."""
    ok = _capture(render._pill_text(Pill("Xero", "synced", "", "ok")))
    warn = _capture(render._pill_text(Pill("Lloyds", "never", "", "warn")))
    err = _capture(render._pill_text(Pill("Revolut", "fail", "", "error")))
    assert render._PILL_GLYPH["ok"] in ok
    assert (
        render._PILL_GLYPH["warn"] in warn
        and render._PILL_GLYPH["warn"] != render._PILL_GLYPH["ok"]
    )
    assert (
        render._PILL_GLYPH["error"] in err
        and render._PILL_GLYPH["error"] != render._PILL_GLYPH["ok"]
    )


def test_walk_progress_renders_optional_step_line():
    plain = _capture(render.render_walk_progress("Working…"))
    assert "Working…" in plain and "step" not in plain
    numbered = _capture(render.render_walk_progress("Building the plan…", "step 2 of 4"))
    assert "Building the plan…" in numbered and "step 2 of 4" in numbered


def test_render_sync_progress_shows_spinner_elapsed_and_calm_default():
    out = _capture(render.render_sync_progress("Syncing Xero…", render.SPINNER_FRAMES[2], 12))
    assert "Syncing Xero…" in out
    assert "12s" in out
    assert render.SPINNER_FRAMES[2] in out
    assert "this can take up to a minute" in out


def test_render_sync_progress_surfaces_latest_activity_when_given():
    out = _capture(render.render_sync_progress("Syncing Xero…", latest="Xero · invoices 220/450"))
    assert "Xero · invoices 220/450" in out
    assert "this can take up to a minute" not in out


def test_preflight_label_is_what_changes_not_blast_radius():
    """M-3 — the section label reads 'what changes', not the ops jargon."""
    from clonway_cockpit.registry import BlastRadius

    out = _capture(
        render.render_preflight(
            title="Schedule bills",
            blast_radius=BlastRadius(summary="s", details=("Does NOT post.",)),
            preconditions=[],
            equivalent_cli="uv run xbook plan",
        )
    )
    assert "what changes" in out
    assert "blast radius" not in out.lower()


def test_render_pulse_marks_the_selected_pill():
    st = _state()  # 3 pills: Xero, Lloyds, Revolut
    plain = _capture(render.render_pulse(st))
    assert "❯" not in plain
    marked = _capture(render.render_pulse(st, selected=1))
    assert "❯" in marked
    assert "Lloyds" in marked


def test_cockpit_screen_pill_selection_marks_pulse():
    out = _capture(render.render_cockpit_screen(_state(), [], selection=("pill", 1)))
    pulse_band = out.split("needs you")[0]
    assert "❯" in pulse_band


def test_render_needs_you_empty_is_calm():
    out = _capture(render.render_needs_you(()))
    assert "nothing pending" in out


def test_render_needs_you_lists_items_with_count_badge():
    needs = (
        NeedsItem("Bills overdue", "3 · £4,210", "error", "schedule-bills"),
        NeedsItem("Sync is stale", "2d ago", "warn", "sync-all"),
    )
    out = _capture(render.render_needs_you(needs))
    assert "Bills overdue" in out and "Sync is stale" in out
    assert "2" in out and "items" in out


def test_render_doctor_marks_selected_and_dims_display_only():
    from clonway_cockpit.doctor import Fix, Probe

    probes = [
        Probe("auth · xero", "ok", "ok", None),
        Probe(
            "state · lloyds",
            "warn",
            "stale",
            Fix("Sync now", "uv run xbook bank sync", run=lambda: "ok"),
        ),
        Probe(
            "auth · xero",
            "error",
            "no token",
            Fix("Re-authenticate Xero", "uv run xbook auth login", "opens browser"),
        ),
    ]
    fixes = [p.fix for p in probes if p.fix]
    out = _capture(render.render_doctor(probes, fixes, selected=0))
    assert "❯" in out
    assert "Sync now" in out
    assert "⏎" in out and "run" in out  # the footer
    assert "run in a terminal" in out
    assert "Re-authenticate Xero" in out


def test_render_doctor_no_selection_renders_static():
    from clonway_cockpit.doctor import Fix, Probe

    probes = [
        Probe(
            "state · xero",
            "warn",
            "stale",
            Fix("Sync now", "uv run xbook xero sync", run=lambda: "ok"),
        ),
    ]
    out = _capture(render.render_doctor(probes, [probes[0].fix], selected=None))
    assert "❯" not in out
    assert "Sync now" in out


def test_walk_result_renders_xero_deeplinks():
    links = [
        ("Payment · X", "https://go.xero.com/Bank/ViewPayment.aspx?paymentID=abc"),
        (
            "Wages clearing payment (814)",
            "https://go.xero.com/Bank/ViewTransaction.aspx?bankTransactionID=d",
        ),
    ]
    renderable = render.render_walk_result(
        "Apply remittance", ok=True, message="Done.", links=links
    )
    con = Console(record=True, width=120)
    con.print(renderable)
    text = con.export_text()
    assert "view in Xero" in text
    assert "Payment · X" in text
    assert "Wages clearing payment (814)" in text

    con2 = Console(width=120)
    linked = {
        seg.text: seg.style.link
        for seg in con2.render(renderable, con2.options)
        if seg.style and seg.style.link
    }
    for label, url in links:
        assert linked.get(label) == url
        seg_style = next(
            s.style for s in con2.render(renderable, con2.options) if s.text == label and s.style
        )
        assert seg_style.underline is True
        assert seg_style.color is not None and seg_style.color.name == render.ACCENT


def test_walk_result_without_links_omits_xero_section():
    out = _capture(render.render_walk_result("Schedule bills", ok=True, message="3 scheduled."))
    assert "view in Xero" not in out
    assert "3 scheduled." in out


def _specs():
    return [
        CapabilitySpec(
            key="schedule-bills",
            shelf="C",
            title="Schedule bills",
            summary="plan + apply",
            equivalent_cli="uv run xbook plan",
        ),
        CapabilitySpec(
            key="reconcile-gap",
            shelf="C",
            title="Reconcile gap",
            summary="show unmatched",
            equivalent_cli="uv run xbook gap",
        ),
        CapabilitySpec(
            key="subscriptions",
            shelf="C",
            title="Subscriptions audit",
            summary="SaaS spend",
            equivalent_cli="uv run xbook subscriptions audit",
        ),
    ]


def test_usage_section_empty_is_graceful():
    out = _capture(render.render_usage_section({}, _specs()))
    assert "no usage recorded yet" in out
    assert "most used" not in out


def test_usage_section_shows_most_used_never_used_completion():
    usage = {
        "schedule-bills": {"open": 10, "applied": 7, "cancelled": 3, "last": _now_iso()},
        "reconcile-gap": {"open": 4, "applied": 0, "cancelled": 0, "last": _now_iso()},
    }
    out = _capture(render.render_usage_section(usage, _specs()))
    assert "most used" in out
    assert "Schedule bills" in out
    assert "10 opens" in out
    assert "never used" in out
    assert "Subscriptions audit" in out
    assert "completion" in out
    assert "7 applied" in out and "70%" in out


def test_usage_section_skips_zero_open_completion_walks():
    usage = {"reconcile-gap": {"open": 2, "applied": 0, "cancelled": 0, "last": _now_iso()}}
    out = _capture(render.render_usage_section(usage, _specs()))
    assert "completion" not in out


def test_usage_notch_scales_and_blanks_zero():
    assert render.usage_notch(0, 10) == ""
    assert render.usage_notch(5, 0) == ""
    assert render.usage_notch(10, 10) == render._NOTCH_GLYPHS[-1]
    one = render.usage_notch(1, 10)
    assert one == render._NOTCH_GLYPHS[0]
    assert render._NOTCH_GLYPHS.index(render.usage_notch(8, 10)) >= render._NOTCH_GLYPHS.index(
        render.usage_notch(2, 10)
    )


def test_render_menu_shows_notch_on_used_rows_only():
    options = [(str(i), s.title, s.summary) for i, s in enumerate(_specs(), 1)]
    opens = [10, 0, 1]
    out = _capture(render.render_menu("Money out", options, opens=opens, peak=10))
    assert any(g in out for g in render._NOTCH_GLYPHS)
    assert render._NOTCH_GLYPHS[-1] in out


def test_render_menu_without_usage_is_unchanged():
    options = [(str(i), s.title, s.summary) for i, s in enumerate(_specs(), 1)]
    out = _capture(render.render_menu("Money out", options))
    assert not any(g in out for g in render._NOTCH_GLYPHS)
    assert "Schedule bills" in out and "Back" in out


def test_render_doctor_appends_usage_section_when_supplied():
    from clonway_cockpit.doctor import Probe

    probes = [Probe("auth · xero", "ok", "ok", None)]
    usage = {"schedule-bills": {"open": 3, "applied": 2, "cancelled": 1, "last": _now_iso()}}
    out = _capture(render.render_doctor(probes, [], usage=usage, specs=_specs()))
    assert "what you reach for" in out
    assert "Schedule bills" in out


def test_render_doctor_omits_usage_section_when_none():
    from clonway_cockpit.doctor import Probe

    probes = [Probe("auth · xero", "ok", "ok", None)]
    out = _capture(render.render_doctor(probes, []))
    assert "what you reach for" not in out


def _now_iso():
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def test_sub_screens_share_the_visual_language():
    menu = _capture(render.render_menu("Money out", [("1", "Schedule bills", "plan + apply")]))
    assert "browse" in menu and "Money out" in menu and "1." in menu and "Back" in menu

    spec = CapabilitySpec(
        key="reconcile-gap",
        shelf="C",
        title="Reconcile gap",
        summary="show unmatched Lloyds lines",
        equivalent_cli="uv run xbook gap",
    )
    card = _capture(render.render_capability_card(spec))
    assert "Reconcile gap" in card and "what this does" in card
    assert "uv run xbook gap" in card
