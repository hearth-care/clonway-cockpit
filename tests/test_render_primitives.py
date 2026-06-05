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


def test_pill_status_pad_separates_a_long_status_from_the_detail():
    """P3 — a ≥7-char status (the bridge emits the 9-char 'in-flight') must not
    collide with the detail. The status pad is widened so there is whitespace
    between status and detail."""
    out = _capture(render._pill_text(Pill("xquill", "in-flight", "07:30", "warn")))
    assert "in-flight07:30" not in out  # the regression: status ran into the detail
    assert "in-flight" in out and "07:30" in out
    # There is at least one space between the status text and the detail.
    import re as _re

    assert _re.search(r"in-flight\s+07:30", out)


def test_pill_short_statuses_keep_their_spacing():
    """P3 default-preserving — xbook's short statuses (≤ the new width) still render
    a space between status and detail; widening the pad only adds trailing space, it
    never removes the gap that was already there."""
    out = _capture(render._pill_text(Pill("Xero", "synced", "06:45", "ok")))
    import re as _re

    assert _re.search(r"synced\s+06:45", out)


def test_render_header_skips_separator_when_tenant_empty():
    """P4 — when tenant_name is empty (the fleet bridge), the header must not append
    a dangling '· ' tenant separator."""
    state = CockpitState(
        tenant_name="",
        app_label="Clonway Office",
        date_label="Mon 25 May 2026",
        time_label="08:00",
    )
    out = _capture(render.render_header(state))
    assert out.rstrip().endswith("08:00")  # no trailing "· "
    assert " · " in out  # the date/time separators are still present


def test_render_header_keeps_separator_when_tenant_present():
    """P4 default-preserving — a non-empty tenant still gets its '· {tenant}'
    segment, exactly as before."""
    out = _capture(render.render_header(_state()))
    assert "08:45" not in out  # sanity: _state's time is 06:45
    assert "· Clonway Care" in out.replace("  ", " ") or "Clonway Care" in out
    assert "Clonway Care" in out


def test_render_pulse_default_gutter_says_enter_sync():
    """P1 default-preserving — with no pulse_hint set, the gutter cue is the exact
    xbook '⏎ sync' string."""
    out = _capture(render.render_pulse(_state()))
    assert "⏎ sync" in out


def test_render_pulse_gutter_honours_custom_pulse_hint():
    """P1 — a state with pulse_hint set renders that cue in the gutter instead of
    '⏎ sync' (the fleet's read-only pills become '⏎ open')."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        pills=(
            Pill("xbook", "ran", "07:30", "ok"),
            Pill("xhr", "stale", "2d", "warn"),
            Pill("xletter", "idle", "", "ok"),
        ),
        pulse_hint="⏎ open",
    )
    out = _capture(render.render_pulse(state))
    assert "⏎ open" in out
    assert "⏎ sync" not in out


def test_cockpit_screen_threads_pulse_hint():
    """render_cockpit_screen routes state.pulse_hint into render_pulse's gutter.

    Needs 3+ pills so the pulse grid has a second gutter row (where the ⏎ cue
    lives)."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        pills=(
            Pill("xbook", "ran", "07:30", "ok"),
            Pill("xhr", "stale", "2d", "warn"),
            Pill("xletter", "idle", "", "ok"),
        ),
        pulse_hint="⏎ open",
    )
    out = _capture(render.render_cockpit_screen(state, []))
    assert "⏎ open" in out
    assert "⏎ sync" not in out


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


def test_render_help_default_is_xbook_verbatim():
    """H1 default-preserving — render_help() with no help_lines keeps xbook's exact
    help body (toolkit shelves / sync the pulse pill / A–G / filter capabilities)."""
    out = _capture(render.render_help())
    assert "toolkit shelves" in out
    assert "sync the selected pulse pill" in out
    assert "open a toolkit shelf" in out
    assert "filter capabilities by name" in out
    # The chrome (title + return hint) is present.
    assert "Keys" in out and "any key to return" in out


def test_render_help_renders_custom_help_lines():
    """H1 — a caller-supplied help body (the fleet's worker-accurate keys) renders
    in place of xbook's, keeping the same chrome/title."""
    lines = (
        ("↑ ↓", "move the highlight"),
        ("⏎", "open the selected worker"),
        ("A–E, G", "open a worker · Fleet Doctor"),
        ("q / esc", "back · quit"),
    )
    out = _capture(render.render_help(help_lines=lines))
    assert "open the selected worker" in out
    assert "open a worker · Fleet Doctor" in out
    # xbook's verbatim lines are gone.
    assert "toolkit shelves" not in out
    assert "sync the selected pulse pill" not in out
    # The chrome is unchanged.
    assert "Keys" in out and "any key to return" in out


def test_render_doctor_no_fixes_still_shows_a_back_hint():
    """D2 — a read-only Doctor (no runnable fixes) must still render a minimal
    'q back' footer so it isn't an exit-less cul-de-sac. No '⏎ run' / '↑↓ move'
    since nothing is runnable."""
    from clonway_cockpit.doctor import Probe

    probes = [Probe("worker · xbook", "ok", "ran ✓", None)]
    out = _capture(render.render_doctor(probes, [], app_label="Clonway Office"))
    assert "q" in out and "back" in out
    # Nothing runnable, so the run/move affordances must not appear.
    assert "run" not in out.replace("Clonway", "")  # 'run' only in the missing footer
    assert "move" not in out


def test_render_doctor_with_fixes_footer_unchanged():
    """D2 default-preserving — when there ARE runnable fixes, the full
    '↑↓ move · ⏎ run · q back' footer is unchanged."""
    from clonway_cockpit.doctor import Fix, Probe

    probes = [
        Probe(
            "state · lloyds",
            "warn",
            "stale",
            Fix("Sync now", "uv run xbook bank sync", run=lambda: "ok"),
        ),
    ]
    out = _capture(render.render_doctor(probes, [probes[0].fix], selected=0))
    assert "move" in out and "run" in out and "back" in out


def _minimal_probes_and_fixes():
    from clonway_cockpit.doctor import Probe

    probes = [Probe("auth · xero", "ok", "ok", None)]
    fixes: list = []
    return probes, fixes


def test_render_doctor_default_app_label_reads_xbook():
    """render_doctor() with no app_label → header contains 'xbook doctor'."""
    probes, fixes = _minimal_probes_and_fixes()
    out = _capture(render.render_doctor(probes, fixes))
    assert "xbook doctor" in out


def test_render_doctor_custom_app_label_overrides_header():
    """render_doctor(app_label='Clonway Office') → header contains 'Clonway Office doctor',
    not 'xbook doctor'."""
    probes, fixes = _minimal_probes_and_fixes()
    out = _capture(render.render_doctor(probes, fixes, app_label="Clonway Office"))
    assert "Clonway Office doctor" in out
    assert "xbook doctor" not in out


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


def test_render_doctor_display_only_fixes_show_back_only_footer():
    """L9 — when all fixes are display-only (run=None), ↑↓ and ⏎ are no-ops so
    the footer must NOT advertise them; only 'q back' should be shown."""
    from clonway_cockpit.doctor import Fix, Probe

    probes = [
        Probe(
            "reconcile · gap",
            "warn",
            "42 unmatched",
            Fix("List the gap", "uv run xbook gap", run=None),
        ),
    ]
    fixes = [probes[0].fix]
    out = _capture(render.render_doctor(probes, fixes, app_label="xbook"))
    # The fix IS shown (display-only row).
    assert "List the gap" in out
    assert "run in a terminal" in out
    # Footer must be back-only — no move or run affordances.
    # "move" must not appear (it only lives in the _doctor_footer, not the body).
    assert "move" not in out
    # "⏎ run" is the specific footer affordance; "run" also appears in chip text
    # ("uv run xbook gap") and the tag ("run in a terminal"), so check for the
    # exact footer token that the shell loop reacts to.
    assert "⏎" not in out
    assert "q" in out and "back" in out


def test_render_doctor_completion_pct_clamped_at_100():
    """L10 — when applied > opened the completion % must be clamped at 100 and
    never render a nonsensical value like 520% or 258%."""
    usage = {
        "schedule-bills": {"open": 5, "applied": 26, "cancelled": 0, "last": _now_iso()},
        "payroll-clear": {"open": 7, "applied": 15, "cancelled": 0, "last": _now_iso()},
    }
    specs = [
        CapabilitySpec(
            key="schedule-bills",
            shelf="C",
            title="Schedule bills",
            summary="plan + apply",
            equivalent_cli="uv run xbook plan",
        ),
        CapabilitySpec(
            key="payroll-clear",
            shelf="C",
            title="Clear payroll",
            summary="post pay run",
            equivalent_cli="uv run xbook payroll clear",
        ),
    ]
    out = _capture(render.render_usage_section(usage, specs))
    # Completion section is shown (both walks have opens > 0).
    assert "completion" in out
    # No pct value should exceed 100%.
    import re

    pcts = [int(m) for m in re.findall(r"(\d+)%", out)]
    assert pcts, "expected at least one % value in completion section"
    assert all(p <= 100 for p in pcts), f"completion % exceeded 100: {pcts}"


def _now_iso():
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def test_render_toolkit_default_shelves_unchanged():
    """No ``shelves`` → the per-domain A-G SHELVES taxonomy + the "toolkit" gutter
    cue, so the extracting worker (xbook) is unchanged."""
    out = _capture(render.render_toolkit(_specs()))
    assert "toolkit" in out
    assert "A. Daily rhythm" in out
    assert "B. Money in" in out
    assert "G. Diagnostics & setup" in out
    assert "A–G" in out  # the canonical second-gutter cue


def test_render_toolkit_custom_shelves_and_label():
    """A custom ``shelves`` map + ``label`` renders exactly those letters under the
    given gutter cue — the WORKERS-style taxonomy, not xbook's shelves."""
    shelves = {"A": "xbook · Bookkeeping", "B": "xhr · HR & rota"}
    out = _capture(render.render_toolkit([], shelves=shelves, label="workers"))
    assert "workers" in out
    assert "A. xbook · Bookkeeping" in out
    assert "B. xhr · HR & rota" in out
    # The default taxonomy is not leaked in.
    assert "Daily rhythm" not in out
    assert "Money in" not in out
    # Two letters fit on a single row, so there is no second-gutter cue — but the
    # hardcoded default cue must NOT leak in for a custom map.
    assert "A–G" not in out


def test_render_toolkit_custom_shelves_derives_letter_range_cue():
    """The derived range cue spans the actual custom letters (e.g. A–E for the
    five-worker roster), not the hardcoded A–G."""
    shelves = {ltr: f"w{ltr}" for ltr in "ABCDE"}
    out = _capture(render.render_toolkit([], shelves=shelves, label="workers"))
    assert "A–E" in out
    assert "A–G" not in out


# --- R1: _letters_cue compresses contiguous runs, gap-aware --------------------


def test_letters_cue_contiguous_run_unchanged():
    """A single contiguous run renders 'first–last' exactly as before — xbook's
    canonical A–G is unchanged."""
    assert render._letters_cue(list("ABCDEFG")) == "A–G"


def test_letters_cue_gapped_set_compresses_each_run():
    """The bridge's [A,B,C,D,E,G] has a gap at F: the cue must compress the
    contiguous A–E run and list G separately, never the lying 'A–G'."""
    assert render._letters_cue(list("ABCDEG")) == "A–E, G"


def test_letters_cue_two_gap_set():
    """Two gaps → three runs, each compressed independently and comma-joined."""
    assert render._letters_cue(list("ACDFG")) == "A, C–D, F–G"


def test_letters_cue_single_letter_stays_itself():
    """A lone letter is its own cue (no dash)."""
    assert render._letters_cue(["A"]) == "A"


def test_render_toolkit_gapped_shelves_cue_is_gap_aware():
    """The WORKERS-region gutter for the bridge's gapped roster shows 'A–E, G',
    matching the legend below — no phantom-F 'A–G'."""
    shelves = {ltr: f"w{ltr}" for ltr in "ABCDEG"}
    out = _capture(render.render_toolkit([], shelves=shelves, label="workers"))
    assert "A–E, G" in out
    assert "A–G" not in out


def test_render_cockpit_screen_renders_custom_shelves_under_label():
    """render_cockpit_screen threads CockpitState.shelves / toolkit_label into the
    bottom region, so the home shows the worker rows under "workers"."""
    state = CockpitState(
        tenant_name="Clonway Care",
        app_label="Clonway Office",
        date_label="Mon 25 May 2026",
        time_label="08:00",
        shelves={"A": "xbook · Bookkeeping", "B": "xhr · HR & rota"},
        toolkit_label="workers",
    )
    out = _capture(render.render_cockpit_screen(state, []))
    assert "workers" in out
    assert "xbook · Bookkeeping" in out
    assert "xhr · HR & rota" in out
    # The bottom region is the roster, NOT xbook's shelf taxonomy.
    assert "Daily rhythm" not in out
    assert "Money in" not in out


def test_render_cockpit_screen_default_state_keeps_shelf_taxonomy():
    """A CockpitState with no shelves (xbook's default) still shows the A-G shelf
    taxonomy under "toolkit" — the extracting worker is unaffected."""
    out = _capture(render.render_cockpit_screen(_state(), _specs()))
    assert "toolkit" in out
    assert "A. Daily rhythm" in out
    assert "workers" not in out


# --- the legend reflects the app (UX-QA #5) -----------------------------------


def test_legend_default_is_xbook_unchanged():
    """The default state (no shelves, no legend_hint) keeps xbook's exact legend
    text — 'open / sync' and the canonical 'A–G to browse'."""
    out = _capture(render._legend(_state()))
    assert "to open / sync" in out
    assert "A–G to browse" in out


def test_legend_derives_letter_range_from_state_shelves():
    """A fleet state with A,B,C,D,E,G shelves reflects the real letter RANGE
    ('A–G' here is correct because G is present) — but a 5-letter roster shows
    'A–E', never the hardcoded 7-letter assumption."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        shelves={ltr: f"w{ltr}" for ltr in "ABCDE"},
        toolkit_label="workers",
    )
    out = _capture(render._legend(state))
    assert "A–E" in out
    assert "A–G" not in out


def test_legend_hint_overrides_open_sync_cue():
    """A custom legend_hint replaces the 'open / sync' cue, so the fleet (which
    can't sync another worker) doesn't advertise a dead 'sync' key."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        shelves={
            "A": "xbook",
            "B": "xhr",
            "C": "xletter",
            "D": "xquill",
            "E": "xops",
            "G": "Doctor",
        },
        toolkit_label="workers",
        legend_hint="open worker",
    )
    out = _capture(render._legend(state))
    assert "open worker" in out
    assert "sync" not in out


def test_cockpit_screen_threads_legend_hint():
    """render_cockpit_screen routes state.legend_hint into the rendered legend."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        shelves={"A": "xbook", "G": "Doctor"},
        toolkit_label="workers",
        legend_hint="open worker",
    )
    out = _capture(render.render_cockpit_screen(state, []))
    assert "open worker" in out
    # The legend line itself must not advertise "sync" (the pulse-empty placeholder
    # "run a sync" is a separate region, not the legend).
    legend_line = next(ln for ln in out.splitlines() if "to move" in ln)
    assert "sync" not in legend_line


def test_legend_shelf_hint_overrides_computed_shelf_segment():
    """A custom shelf_hint replaces the computed 'A–G to browse' shelf segment, so
    the fleet (whose shelves are A,B,C,D,E,G — no F) doesn't imply F is a live
    browsable letter and can say the letters open a worker, not 'browse' (H2)."""
    state = CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        shelves={
            "A": "xbook",
            "B": "xhr",
            "C": "xletter",
            "D": "xquill",
            "E": "xops",
            "G": "Doctor",
        },
        toolkit_label="workers",
        shelf_hint="A–E, G open a worker",
    )
    out = _capture(render._legend(state))
    assert "A–E, G open a worker" in out
    assert "A–G to browse" not in out


def test_legend_default_shelf_segment_byte_identical():
    """The default state (no shelf_hint) renders the canonical xbook legend line
    byte-for-byte — pinned in full so the default path can never drift."""
    out = _capture(render._legend(_state()))
    assert out == (
        "▸ Press ↑↓←→ to move · ⏎ to open / sync · A–G to browse · "
        "/ to filter · ? for help · q to quit\n"
    )


# --- R2: the filter screen title is parametrised -------------------------------


def test_render_filter_default_title_is_find_a_tool():
    """No title passed → the canonical 'Find a tool' header, byte-identical to
    xbook's single-worker filter."""
    out = _capture(render.render_filter("", []))
    assert "Find a tool" in out


def test_render_filter_custom_title_renders():
    """A custom title (the bridge finds workers AND needs) replaces 'Find a tool'."""
    out = _capture(render.render_filter("", [], title="Find a worker or need"))
    assert "Find a worker or need" in out
    assert "Find a tool" not in out


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


# --- cross-deck breadcrumb (Fleet-Cockpit §4.3) -------------------------------


def test_render_header_no_breadcrumb_is_byte_identical():
    """Default-preserving — a state with no breadcrumb renders the header exactly
    as before (no mode-line, no separators leaked in). Pinned in full so the
    default path can never drift; xbook (which never sets a crumb) is unchanged."""
    out = _capture(render.render_header(_state()))
    assert out == "xbook · Fri 23 May 2026 · 06:45 · Clonway Care (tenant 9b40…)\n"
    assert "▸" not in out  # no crumb glyph when unset


def test_render_header_renders_supplied_breadcrumb_trail():
    """A state carrying a breadcrumb trail renders it as a persistent 'A ▸ B ▸ C'
    mode-line. The framework only RENDERS the supplied trail; the worker/bridge
    decides the content."""
    state = CockpitState(
        tenant_name="",
        app_label="Clonway Office",
        date_label="Mon 25 May 2026",
        time_label="08:00",
        breadcrumb=("Fleet", "xbook", "Schedule bills"),
    )
    out = _capture(render.render_header(state))
    assert "Fleet ▸ xbook ▸ Schedule bills" in out
    # The standard header bits still render above/around the crumb.
    assert "Clonway Office" in out and "08:00" in out


def test_render_header_single_breadcrumb_renders_without_separator():
    """A one-element trail renders just the crumb — no dangling ' ▸ ' separator."""
    state = CockpitState(
        tenant_name="",
        app_label="Clonway Office",
        date_label="Mon 25 May 2026",
        time_label="08:00",
        breadcrumb=("Fleet",),
    )
    out = _capture(render.render_header(state))
    assert "Fleet" in out
    assert "▸" not in out  # no separator for a lone crumb


def test_render_header_empty_breadcrumb_tuple_is_byte_identical():
    """An empty breadcrumb tuple is treated like None — no mode-line — so a worker
    that always passes a (possibly empty) trail never accidentally adds chrome."""
    state = CockpitState(
        tenant_name="Clonway Care",
        date_label="Fri 23 May 2026",
        time_label="06:45",
        tenant_id="9b40…",
        breadcrumb=(),
    )
    out = _capture(render.render_header(state))
    assert out == "xbook · Fri 23 May 2026 · 06:45 · Clonway Care (tenant 9b40…)\n"


def test_cockpit_screen_threads_breadcrumb():
    """render_cockpit_screen routes state.breadcrumb into the rendered header."""
    state = CockpitState(
        tenant_name="",
        app_label="Clonway Office",
        date_label="Mon 25 May 2026",
        time_label="08:00",
        breadcrumb=("Fleet", "xbook", "Schedule bills"),
    )
    out = _capture(render.render_cockpit_screen(state, []))
    assert "Fleet ▸ xbook ▸ Schedule bills" in out


def test_cockpit_screen_default_state_has_no_breadcrumb():
    """Default-preserving — a state with no breadcrumb renders the home screen with
    no mode-line crumb (the crumb glyph ▸ appears only in the legend's '▸ Press')."""
    out = _capture(render.render_cockpit_screen(_state(), []))
    # The only ▸ on the home screen is the legend opener — no crumb mode-line.
    crumb_lines = [ln for ln in out.splitlines() if "▸" in ln and "Press" not in ln]
    assert crumb_lines == []


# --- render_sync_progress live-log panel (PR 1) --------------------------------


def test_render_sync_progress_multi_lines_dim_and_stacked():
    """When ``lines`` is non-empty, each entry is rendered as a separate dim row
    beneath the spinner head; the calm reassurance is suppressed."""
    lines = ("xero · invoices 100/200", "lloyds · rows 50/100")
    out = _capture(render.render_sync_progress("Syncing", lines=lines))
    assert "xero · invoices 100/200" in out
    assert "lloyds · rows 50/100" in out
    assert "this can take up to a minute" not in out


def test_render_sync_progress_lines_suppresses_calm_default():
    """``lines`` takes precedence over the calm-reassurance default (and over
    ``latest`` for backwards compat) — the reassurance line must not appear when
    lines are present."""
    out = _capture(
        render.render_sync_progress("Syncing", latest="old latest", lines=("new line 1",))
    )
    assert "new line 1" in out
    assert "this can take up to a minute" not in out


def test_render_doctor_completion_applied_clamped_to_opened():
    """applied > opened is a telemetry inconsistency (an apply recorded without a
    matching open). The completion line must not read 'X opened · Y applied' with
    Y > X — clamp the displayed applied to opened so it reads coherently."""
    usage = {
        "schedule-bills": {"open": 5, "applied": 26, "cancelled": 0, "last": _now_iso()},
    }
    specs = [
        CapabilitySpec(
            key="schedule-bills",
            shelf="C",
            title="Schedule bills",
            summary="plan + apply",
            equivalent_cli="uv run xbook plan",
        ),
    ]
    out = _capture(render.render_usage_section(usage, specs))
    assert "5 opened · 5 applied" in out
    assert "26 applied" not in out


def test_render_staged_progress_states_and_hint():
    from clonway_cockpit.walk import Stage

    stages = [
        Stage("accounts", "Accounts", "done", "120"),
        Stage("contacts", "Contacts", "active", "page 7 · 1,400"),
        Stage("pnl", "P&L", "pending"),
        Stage("payroll", "Payroll", "skipped", "skipped"),
    ]
    out = _capture(
        render.render_staged_progress(
            "Syncing Xero…",
            stages,
            render.SPINNER_FRAMES[0],
            12,
            hint="rate-limited, still working",
            hint_after_s=60,
        )
    )
    assert "Syncing Xero…" in out and "12s" in out
    assert "✓" in out and "Accounts" in out and "120" in out
    assert "Contacts" in out and "page 7 · 1,400" in out
    assert "·" in out and "P&L" in out  # pending glyph
    assert "⚠" in out and "Payroll" in out  # skipped glyph
    assert "├─" in out and "└─" in out  # stages nest under the head as a tree
    assert "rate-limited, still working" not in out  # elapsed 12 < hint_after_s


def test_render_staged_progress_shows_hint_past_threshold():
    from clonway_cockpit.walk import Stage

    out = _capture(
        render.render_staged_progress(
            "Syncing Xero…",
            [Stage("accounts", "Accounts", "active")],
            render.SPINNER_FRAMES[0],
            75,
            hint="rate-limited, still working",
            hint_after_s=60,
        )
    )
    assert "rate-limited, still working" in out


def test_render_staged_progress_shows_controls_hint():
    from clonway_cockpit.walk import Stage

    out = _capture(
        render.render_staged_progress(
            "Syncing Xero…",
            [Stage("a", "Accounts", "active")],
            render.SPINNER_FRAMES[0],
            5,
            controls="q cancel",
        )
    )
    assert "q cancel" in out
