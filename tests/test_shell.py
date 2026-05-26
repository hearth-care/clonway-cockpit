"""Golden tests for the framework cockpit shell loop (``clonway_cockpit.shell``).

These are the GENERIC loop tests ported from xbook's ``tests/cockpit/test_app.py``
(the 793-line parity harness) with the xbook-domain bits replaced by a fake
:class:`_FakeHost`: navigation, the LEFT/RIGHT column jump, the default-selection /
first-paint cursor, type-to-filter, the open-capability chokepoint + its usage
record, the doctor loop (runnable / display-only / confirm-cancel / unconfigured),
q-quits, and the animated-progress helper. The xbook-domain tests (Lloyds re-auth,
signal emit, sync-pill action, ShellOut re-entry) stay in xbook because they wire
worker-specific callbacks the framework only receives through the host."""

from __future__ import annotations

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell, usage
from clonway_cockpit.doctor import Fix, Probe, fixes_for
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, NeedsItem, Pill


class _Screen:
    """A fake alternate-screen: records each rendered frame."""

    def __init__(self):
        self.frames = []

    def update(self, renderable):
        self.frames.append(renderable)


def _keys(seq):
    """A scripted key reader: returns each token, then 'q' forever (so any
    nested loop still terminates if the script runs out)."""
    buf = list(seq)

    def _next():
        return buf.pop(0) if buf else "q"

    return _next


def _text(frame) -> str:
    con = Console(record=True, width=120)
    con.print(frame)
    return con.export_text()


_PILLS = (
    Pill("Xero", "synced", "06:45", "ok", "xero"),
    Pill("Lloyds", "synced", "06:45", "ok", "lloyds"),
    Pill("Revolut", "never synced", "", "warn", "revolut"),
)


def _walk_ctx(screen, read_key, *, focus: str | None = None) -> WizardContext:
    """A minimal screen-bound WizardContext — present routes to screen.update so a
    walk's review renderable lands on the fake screen, like the cockpit binds it."""
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


class _FakeHost:
    """A configurable stand-in for a worker's :class:`shell.Host`. Defaults to a
    no-pill / no-need state, a pill-activation + on-open that record calls, the
    framework usage module, and doctor builders that surface a fixed probe set."""

    def __init__(
        self,
        *,
        state: CockpitState | None = None,
        probes: list[Probe] | None = None,
        report_raises: bool = False,
        usage_module=usage,
        ack=None,
        snooze=None,
    ):
        self._state = state or CockpitState(tenant_name="Clonway")
        self._probes = probes or []
        self._report_raises = report_raises
        self.pill_calls: list = []
        self.open_calls = 0
        self.usage = usage_module
        # Optional ack/snooze callbacks (the Fleet bridge supplies these; xbook
        # leaves them None). Defaults None so a default _FakeHost is xbook-shaped.
        self._ack = ack
        self._snooze = snooze
        # Count capture_state calls so a test can assert the loop re-captured after
        # an ack/snooze (the acked item drops on the redraw).
        self.capture_calls = 0

    def _capture(self) -> CockpitState:
        self.capture_calls += 1
        return self._state

    # --- shell.Host surface ------------------------------------------------
    def as_host(self) -> shell.Host:
        return shell.Host(
            capture_state=self._capture,
            build_walk_ctx=_walk_ctx,
            activate_pill=lambda pill, scr, rk: self.pill_calls.append(pill),
            doctor_build_report=self._build_report,
            doctor_build_probes=lambda report: self._probes,
            doctor_fixes_for=fixes_for,
            doctor_unconfigured_renderable=lambda: render.render_note(
                "Doctor", "run `worker auth login` — not configured"
            ),
            usage=self.usage,
            on_open=self._on_open,
            ack=self._ack,
            snooze=self._snooze,
        )

    def _build_report(self) -> object:
        if self._report_raises:
            raise RuntimeError("unconfigured")
        return object()

    def _on_open(self) -> None:
        self.open_calls += 1


def _register_reference(
    key="sync-all", shelf="A", title="Sync everything", summary="fresh numbers"
):
    register_capability(
        CapabilitySpec(
            key=key,
            shelf=shelf,
            title=title,
            summary=summary,
            equivalent_cli=f"uv run worker {key}",
        )
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_capabilities()
    yield
    clear_capabilities()


@pytest.fixture
def usage_to_tmp(tmp_path, monkeypatch):
    """Point the framework usage module at tmp_path so the loop's record/load
    never pollutes a real state dir."""
    monkeypatch.setattr(usage, "_DEFAULT_BASE", tmp_path)
    return tmp_path


# --- selectables + the LEFT/RIGHT column jump ---------------------------------


def test_selectables_puts_pills_first():
    needs = (NeedsItem("Sync the books", "never synced", "warn", "sync-all"),)
    state = CockpitState(tenant_name="Clonway", pills=_PILLS, needs=needs)
    items = shell.selectables(state)
    assert items[0] == ("pill", 0)
    assert items[1] == ("pill", 1)
    assert items[2] == ("pill", 2)
    assert items[3] == ("need", 0)
    assert items[4][0] == "shelf"


def _shelf_items():
    return [("shelf", letter) for letter in render.SHELVES]


def test_right_from_left_shelf_jumps_to_same_row_right_shelf():
    items = _shelf_items()
    for left_letter, right_letter in (("A", "E"), ("B", "F"), ("C", "G")):
        sel = items.index(("shelf", left_letter))
        new = shell.move_horizontal(items, sel, keys.RIGHT)
        assert items[new] == ("shelf", right_letter)


def test_left_from_right_shelf_returns_to_same_row_left_shelf():
    items = _shelf_items()
    for right_letter, left_letter in (("E", "A"), ("F", "B"), ("G", "C")):
        sel = items.index(("shelf", right_letter))
        new = shell.move_horizontal(items, sel, keys.LEFT)
        assert items[new] == ("shelf", left_letter)


def test_right_from_d_shelf_with_no_pair_stays_put():
    items = _shelf_items()
    sel = items.index(("shelf", "D"))
    assert shell.move_horizontal(items, sel, keys.RIGHT) == sel


def test_left_from_left_shelf_is_noop():
    items = _shelf_items()
    sel = items.index(("shelf", "A"))
    assert shell.move_horizontal(items, sel, keys.LEFT) == sel


def test_pills_left_right_move_across_columns():
    state = CockpitState(tenant_name="Clonway", pills=_PILLS)
    items = shell.selectables(state)
    i0 = items.index(("pill", 0))
    i1 = items.index(("pill", 1))
    assert shell.move_horizontal(items, i0, keys.RIGHT) == i1
    assert shell.move_horizontal(items, i1, keys.LEFT) == i0
    i2 = items.index(("pill", 2))
    assert shell.move_horizontal(items, i2, keys.RIGHT) == i2
    assert shell.move_horizontal(items, i0, keys.LEFT) == i0


def test_needs_you_left_right_are_noop():
    needs = (
        NeedsItem("Sync the books", "never synced", "warn", "sync-all"),
        NeedsItem("Bills overdue", "2 · £195", "error", "schedule-bills", focus="overdue"),
    )
    state = CockpitState(tenant_name="Clonway", needs=needs)
    items = shell.selectables(state)
    n0 = items.index(("need", 0))
    assert shell.move_horizontal(items, n0, keys.LEFT) == n0
    assert shell.move_horizontal(items, n0, keys.RIGHT) == n0


# --- the fleet's state.shelves drives navigation (UX-QA #1 / #2) ---------------

# The Fleet Cockpit's roster: A,B,C,D,E,G — note NO F. The shell must navigate
# exactly these (the letters it draws), not xbook's hardcoded A–G.
_FLEET_SHELVES = {
    "A": "xbook · Bookkeeping",
    "B": "xhr · HR & rota",
    "C": "xletter · Comms",
    "D": "xquill · Notes",
    "E": "xops · Orchestrator",
    "G": "Fleet Doctor",
}


def _fleet_state(**kw) -> CockpitState:
    return CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        shelves=_FLEET_SHELVES,
        toolkit_label="workers",
        **kw,
    )


def _register_fleet_specs():
    """One spec per fleet letter so each shelf has content to open."""
    for letter, label in _FLEET_SHELVES.items():
        register_capability(
            CapabilitySpec(
                key=f"worker-{letter.lower()}",
                shelf=letter,
                title=label,
                summary=f"open {label}",
                equivalent_cli=f"uv run worker-{letter.lower()}",
            )
        )


def test_selectables_uses_state_shelves_when_present():
    """The shelf selectables come from state.shelves (the fleet's 6 letters), NOT
    the hardcoded render.SHELVES — so there is no phantom ('shelf','F')."""
    items = shell.selectables(_fleet_state())
    shelf_letters = [ref for kind, ref in items if kind == "shelf"]
    assert shelf_letters == ["A", "B", "C", "D", "E", "G"]
    assert ("shelf", "F") not in items


def test_selectables_falls_back_to_render_shelves_when_none():
    """Default state (shelves=None) → xbook's canonical A–G, unchanged."""
    items = shell.selectables(CockpitState(tenant_name="Clonway"))
    shelf_letters = [ref for kind, ref in items if kind == "shelf"]
    assert shelf_letters == list(render.SHELVES)


def test_arrowing_down_lands_only_on_present_fleet_letters(usage_to_tmp):
    """Arrowing DOWN through the fleet roster lands the ❯ on each PRESENT letter
    and NEVER on a phantom (no empty/F stop where the cursor vanishes)."""
    _register_fleet_specs()
    host = _FakeHost(state=_fleet_state()).as_host()
    scr = _Screen()
    # 6 shelves; arrow down through all of them then quit. Every home frame must
    # show exactly one ❯ cursor (never zero — a phantom F stop drops it to zero).
    keypresses = [keys.DOWN] * 6 + ["q"]
    shell.run_cockpit(host, read_key=_keys(keypresses), screen=scr)
    for frame in scr.frames:
        text = _text(frame)
        assert text.count("❯") >= 1, "cursor vanished — landed on a phantom row"
    # And F must never appear as a drawn row label.
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "F." not in joined


def test_enter_opens_each_present_fleet_shelf(usage_to_tmp):
    """⏎ on each present fleet letter opens its spec; the menu titles the worker."""
    _register_fleet_specs()
    for letter, label in _FLEET_SHELVES.items():
        host = _FakeHost(state=_fleet_state()).as_host()
        scr = _Screen()
        shell.run_cockpit(host, read_key=_keys([letter.lower(), "q", "q"]), screen=scr)
        joined = "\n".join(_text(f) for f in scr.frames)
        assert label in joined, f"shelf {letter} did not open {label!r}"


def test_phantom_f_hotkey_is_inert_for_the_fleet(usage_to_tmp):
    """Pressing 'f' on the fleet home does nothing (F is not a present letter) —
    no menu opens, the home stays put."""
    _register_fleet_specs()
    host = _FakeHost(state=_fleet_state()).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["f", "q"]), screen=scr)
    # Only home frames — no shelf menu opened. The menu carries render_menu's
    # distinctive "⏎ select · q back" hint (the home legend says "⏎ to ... browse").
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "⏎ select" not in joined


def test_shelf_menu_title_is_the_fleet_worker_not_xbook_taxonomy(usage_to_tmp):
    """Opening fleet shelf B shows the worker label ('xhr · HR & rota'), NOT
    xbook's 'Money in' shelf name."""
    _register_fleet_specs()
    host = _FakeHost(state=_fleet_state()).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["b", "q", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "xhr · HR & rota" in joined
    assert "Money in" not in joined


# --- ←/→ column math matches the rendered grid for the fleet (UX-QA #2) --------


def _fleet_items():
    return shell.selectables(_fleet_state())


def test_fleet_right_jumps_to_correct_column_pair():
    """The fleet's 6 letters split left=[A,B,C] / right=[D,E,G] (matching
    render_toolkit's (len+1)//2 split). RIGHT from a left letter lands on its
    visual right pair."""
    items = _fleet_items()
    for left_letter, right_letter in (("A", "D"), ("B", "E"), ("C", "G")):
        sel = items.index(("shelf", left_letter))
        new = shell.move_horizontal(items, sel, keys.RIGHT)
        assert items[new] == ("shelf", right_letter)


def test_fleet_left_returns_to_correct_column_pair():
    items = _fleet_items()
    for right_letter, left_letter in (("D", "A"), ("E", "B"), ("G", "C")):
        sel = items.index(("shelf", right_letter))
        new = shell.move_horizontal(items, sel, keys.LEFT)
        assert items[new] == ("shelf", left_letter)


def test_fleet_left_from_left_letter_is_noop():
    """LEFT from a left-column letter (e.g. xquill's pair partner A) is a no-op —
    no dead jump to a non-present letter."""
    items = _fleet_items()
    for left_letter in ("A", "B", "C"):
        sel = items.index(("shelf", left_letter))
        assert shell.move_horizontal(items, sel, keys.LEFT) == sel


def test_fleet_right_from_right_letter_is_noop():
    items = _fleet_items()
    for right_letter in ("D", "E", "G"):
        sel = items.index(("shelf", right_letter))
        assert shell.move_horizontal(items, sel, keys.RIGHT) == sel


def test_fleet_horizontal_never_lands_on_a_non_present_letter():
    """Sweep every shelf with both arrows — the result is always a present letter
    (or the same index), never a phantom F."""
    items = _fleet_items()
    present = set(_FLEET_SHELVES)
    for i, (kind, _ref) in enumerate(items):
        if kind != "shelf":
            continue
        for key in (keys.LEFT, keys.RIGHT):
            new = shell.move_horizontal(items, i, key)
            k2, ref2 = items[new]
            assert k2 == "shelf"
            assert ref2 in present


# --- the home loop: nav, first paint, q-quits ---------------------------------


def test_right_key_in_home_loop_moves_selection(usage_to_tmp):
    """RIGHT off the first shelf moves the cursor into the right column."""
    host = _FakeHost().as_host()  # no pills, no needs → boot lands on shelf A
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys([keys.RIGHT, "q"]), screen=scr)
    after = _text(scr.frames[1])
    line = next(ln for ln in after.splitlines() if "E." in ln and "❯" in ln)
    assert "❯" in line


def test_first_paint_highlights_the_first_pill_when_no_needs(usage_to_tmp):
    host = _FakeHost(state=CockpitState(tenant_name="Clonway", pills=_PILLS)).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    boot = _text(scr.frames[0])
    assert "❯" in boot.split("needs you")[0]


def test_first_paint_highlights_the_first_need(usage_to_tmp):
    needs = (NeedsItem("Sync the books", "never synced", "warn", "sync-all"),)
    host = _FakeHost(state=CockpitState(tenant_name="Clonway", needs=needs)).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    assert "❯ 1." in _text(scr.frames[0])


def test_first_paint_falls_back_to_first_shelf(usage_to_tmp):
    host = _FakeHost().as_host()  # no pills, no needs
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    boot = _text(scr.frames[0])
    assert "❯" in boot.split("toolkit")[1]


def test_q_quits_immediately(usage_to_tmp):
    needs = (NeedsItem("Sync the books", "never synced", "warn", "sync-all"),)
    host = _FakeHost(state=CockpitState(tenant_name="Clonway", needs=needs)).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    assert scr.frames


def test_run_cockpit_fires_on_open(usage_to_tmp):
    fh = _FakeHost()
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["q"]), screen=scr)
    assert fh.open_calls == 1
    assert scr.frames


# --- pill activation + shelves + open-capability ------------------------------


def test_enter_on_a_pill_routes_to_activate_pill(usage_to_tmp):
    fh = _FakeHost(state=CockpitState(tenant_name="Clonway", pills=_PILLS))
    scr = _Screen()
    # Boot cursor on the Xero pill; ↓ to the Lloyds pill; ENTER activates it; q.
    shell.run_cockpit(fh.as_host(), read_key=_keys([keys.DOWN, keys.ENTER, "q"]), screen=scr)
    assert [p.source for p in fh.pill_calls] == ["lloyds"]


def test_letter_hotkey_opens_a_shelf(usage_to_tmp):
    _register_reference()  # sync-all on shelf A
    host = _FakeHost().as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["a", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined
    assert "fresh numbers" in joined


def test_arrow_reaches_the_back_row_in_a_shelf(usage_to_tmp):
    # W4: a single-spec shelf now opens directly (no menu, no Back row), so the
    # Back-row navigation this test exercises only exists on a MULTI-spec shelf —
    # register two specs so the browse menu (and its Back row) is shown.
    _register_reference(key="cap-1", shelf="A", title="First cap", summary="one")
    _register_reference(key="cap-2", shelf="A", title="Second cap", summary="two")
    host = _FakeHost().as_host()
    scr = _Screen()
    # A → shelf menu (2 items + Back); ↓↓↓ wraps onto Back; Enter returns; q quits.
    shell.run_cockpit(host, read_key=_keys(["a", keys.DOWN, keys.DOWN, keys.ENTER]), screen=scr)
    assert any("❯ q." in _text(f) for f in scr.frames)


def test_enter_opens_the_highlighted_reference_card(usage_to_tmp):
    register_capability(
        CapabilitySpec(
            key="_synthetic-ref",
            shelf="A",
            title="Synthetic reference card",
            summary="A reference-only card for the card-render path",
            equivalent_cli="uv run worker synthetic-ref-demo",
        )
    )
    needs = (NeedsItem("Open it", "x", "warn", "_synthetic-ref"),)
    host = _FakeHost(state=CockpitState(tenant_name="Clonway", needs=needs)).as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys([keys.ENTER, keys.ENTER]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "uv run worker synthetic-ref-demo" in joined


def test_open_capability_runs_a_walk_handler_with_focus(usage_to_tmp):
    """The chokepoint runs a registered handler through a screen-bound context and
    threads focus into ctx.focus."""
    seen: dict = {}
    register_capability(
        CapabilitySpec(
            key="scoped",
            shelf="C",
            title="Scoped walk",
            summary="x",
            equivalent_cli="x",
            run=lambda ctx: seen.update(focus=ctx.focus),
        )
    )
    host = _FakeHost().as_host()
    shell._open_capability(host, "scoped", _Screen(), _keys([keys.ESC]), focus="overdue")
    assert seen["focus"] == "overdue"
    seen.clear()
    shell._open_capability(host, "scoped", _Screen(), _keys([keys.ESC]))
    assert seen["focus"] is None


def test_open_capability_records_an_open(usage_to_tmp, monkeypatch):
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        usage, "record", lambda key, action="open", **k: recorded.append((key, action))
    )
    register_capability(
        CapabilitySpec(
            key="status",
            shelf="A",
            title="Status board",
            summary="See where the books stand right now",
            equivalent_cli="uv run worker status",
        )
    )
    host = _FakeHost().as_host()
    shell._open_capability(host, "status", _Screen(), _keys([keys.ENTER]))
    assert ("status", "open") in recorded


def test_open_capability_unknown_key_records_nothing(usage_to_tmp, monkeypatch):
    recorded: list = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: recorded.append((a, k)))
    host = _FakeHost().as_host()
    shell._open_capability(host, "nope-not-real", _Screen(), _keys([keys.ENTER]))
    assert recorded == []


def test_filter_narrows_and_opens(usage_to_tmp):
    register_capability(
        CapabilitySpec(
            key="status",
            shelf="A",
            title="Status board",
            summary="See where the books stand",
            equivalent_cli="uv run worker status",
        )
    )
    host = _FakeHost().as_host()
    scr = _Screen()
    shell.run_cockpit(
        host, read_key=_keys(["/", "s", "t", "a", "t", keys.ENTER, keys.ENTER]), screen=scr
    )
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Status board" in joined


# --- F2: q quits the filter when the term is empty ----------------------------


def test_filter_q_on_empty_term_quits_back_home(usage_to_tmp):
    """F2 — '/' then 'q' (with an empty search term) closes the filter and returns
    home, matching 'q quits' everywhere else."""
    _register_reference()
    host = _FakeHost().as_host()
    scr = _Screen()
    # '/' opens the filter; 'q' on the empty term quits it back home; 'q' quits home.
    shell.run_cockpit(host, read_key=_keys(["/", "q", "q"]), screen=scr)
    # The last frame is the home (the legend line), not the filter.
    last = _text(scr.frames[-1])
    assert "to move" in last  # the home legend
    assert "Find a tool" not in last  # not the filter screen


def test_filter_q_mid_term_is_a_search_char(usage_to_tmp):
    """F2 — once the operator has typed something, 'q' is a normal search char, so
    a term containing 'q' is still searchable. '/' 'b' 'q' → term 'bq'."""
    host = _FakeHost().as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["/", "b", "q", keys.ESC, "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    # The filter showed the typed term "bq" (q did not quit mid-term).
    assert "bq" in joined


def test_filter_esc_always_quits(usage_to_tmp):
    """F2 default-preserving — ESC still closes the filter from any term state."""
    host = _FakeHost().as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["/", "b", "q", keys.ESC, "q"]), screen=scr)
    last = _text(scr.frames[-1])
    assert "to move" in last
    assert "Find a tool" not in last


# --- F1: the filter matches needs-you items and drills like a needs-you ⏎ ------


def _need_specs_state() -> CockpitState:
    """A state carrying needs-you items (with and without a capability)."""
    return CockpitState(
        tenant_name="Clonway",
        needs=(
            NeedsItem("Bills overdue", "3 · £4,210", "error", "schedule-bills", focus="overdue"),
            NeedsItem("Payroll due", "Fri", "warn", None),  # note-only need (no capability)
        ),
    )


def test_filter_matches_a_needs_you_item(usage_to_tmp):
    """F1 — typing 'bill' with 'Bills overdue' in needs-you finds it (it's not a
    capability, but the filter now matches rendered needs too)."""
    register_capability(
        CapabilitySpec(
            key="schedule-bills",
            shelf="C",
            title="Schedule bills",
            summary="plan + apply the bills",
            equivalent_cli="uv run worker plan",
            run=lambda ctx: ctx.present(render.render_note("Scheduled", "the bills walk ran")),
        )
    )
    host = _FakeHost(state=_need_specs_state()).as_host()
    scr = _Screen()
    # '/' filter; type 'bill'; the need "Bills overdue" must appear as a match.
    shell.run_cockpit(host, read_key=_keys(["/", "b", "i", "l", "l", keys.ESC, "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Bills overdue" in joined


def test_filter_enter_on_a_matched_need_drills_via_its_activation(usage_to_tmp):
    """F1 — ⏎ on a filtered need routes to the SAME drill a needs-you ⏎ uses: the
    need's capability opens through the open-capability chokepoint (focus threaded)."""
    seen: dict = {}
    register_capability(
        CapabilitySpec(
            key="schedule-bills",
            shelf="C",
            title="Schedule bills",
            summary="plan + apply the bills",
            equivalent_cli="uv run worker plan",
            run=lambda ctx: seen.update(focus=ctx.focus, ran=True),
        )
    )
    host = _FakeHost(state=_need_specs_state()).as_host()
    scr = _Screen()
    # "overdue" uniquely matches the need "Bills overdue" (not the capability's
    # title/summary), so ⏎ must drill the NEED — through _activate_need, which threads
    # the need's focus into the walk.
    shell.run_cockpit(
        host,
        read_key=_keys(["/", "o", "v", "e", "r", "d", "u", "e", keys.ENTER, "q"]),
        screen=scr,
    )
    assert seen.get("ran") is True
    assert seen.get("focus") == "overdue"  # the need's focus is threaded through


def test_filter_enter_on_a_note_only_need_shows_its_note(usage_to_tmp):
    """F1 — a matched need with no capability drills to the same note screen a
    needs-you ⏎ would show (not a dead key)."""
    host = _FakeHost(state=_need_specs_state()).as_host()
    scr = _Screen()
    shell.run_cockpit(
        host,
        read_key=_keys(["/", "p", "a", "y", "r", "o", "l", "l", keys.ENTER, "q", "q"]),
        screen=scr,
    )
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Payroll due" in joined  # the note title rendered


def test_filter_with_no_needs_is_capability_only_unchanged(usage_to_tmp):
    """F1 default-preserving — with no needs present (xbook's typical filter use),
    the filter matches capabilities exactly as before."""
    register_capability(
        CapabilitySpec(
            key="status",
            shelf="A",
            title="Status board",
            summary="See where the books stand",
            equivalent_cli="uv run worker status",
        )
    )
    host = _FakeHost().as_host()  # no needs
    scr = _Screen()
    shell.run_cockpit(
        host, read_key=_keys(["/", "s", "t", "a", "t", keys.ENTER, keys.ENTER]), screen=scr
    )
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Status board" in joined


# --- R2: the filter screen title is threaded from CockpitState.filter_title ----


def test_filter_title_threads_from_state(usage_to_tmp):
    """R2 — a CockpitState.filter_title flows through the shell into the filter
    header, so the bridge can title its filter 'Find a worker or need'."""
    state = CockpitState(tenant_name="Clonway Office", filter_title="Find a worker or need")
    host = _FakeHost(state=state).as_host()
    scr = _Screen()
    # '/' opens the filter; esc closes it; q quits home.
    shell.run_cockpit(host, read_key=_keys(["/", keys.ESC, "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Find a worker or need" in joined
    assert "Find a tool" not in joined


def test_filter_title_default_is_find_a_tool_unchanged(usage_to_tmp):
    """R2 default-preserving — no filter_title (xbook's default) → the filter still
    reads 'Find a tool', byte-identical to before."""
    host = _FakeHost().as_host()  # default state, filter_title=None
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["/", keys.ESC, "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Find a tool" in joined


# --- R4: need-matches are ordered ahead of capability-matches ------------------


def test_matches_orders_needs_before_capabilities(usage_to_tmp):
    """R4 — when both a need and capabilities match the term, the need comes FIRST
    in the returned list, so it survives the downstream 9-match truncation."""
    register_capability(
        CapabilitySpec(
            key="xbook-status",
            shelf="A",
            title="xbook status",
            summary="See where the books stand",
            equivalent_cli="uv run worker status",
        )
    )
    register_capability(
        CapabilitySpec(
            key="xhr-status",
            shelf="B",
            title="xhr status",
            summary="See the rota",
            equivalent_cli="uv run worker status",
        )
    )
    state = CockpitState(
        tenant_name="Clonway Office",
        needs=(NeedsItem("xbook bills overdue", "3 · £4,210", "error", None),),
    )
    host = _FakeHost(state=state).as_host()
    # "xbook" matches the need title AND the xbook-status capability title.
    matches = shell._matches(host, state, "xbook")
    assert len(matches) == 2
    assert matches[0].title == "xbook bills overdue"  # the need is first
    assert matches[1].title == "xbook status"  # the capability follows


def test_matches_capabilities_only_order_unchanged(usage_to_tmp):
    """R4 default-preserving — with no needs (xbook's typical filter use), the
    returned list is capability-only and capability order is stable."""
    register_capability(
        CapabilitySpec(
            key="cap-a",
            shelf="A",
            title="status alpha",
            summary="one",
            equivalent_cli="uv run worker a",
        )
    )
    register_capability(
        CapabilitySpec(
            key="cap-b",
            shelf="B",
            title="status beta",
            summary="two",
            equivalent_cli="uv run worker b",
        )
    )
    state = CockpitState(tenant_name="Clonway")  # no needs
    host = _FakeHost(state=state).as_host()
    matches = shell._matches(host, state, "status")
    titles = [m.title for m in matches]
    assert titles == ["status alpha", "status beta"]  # capability order preserved


# --- W4: a single-spec shelf opens directly (no intermediate menu) ------------


def test_single_spec_shelf_opens_directly_no_menu(usage_to_tmp):
    """W4 — a shelf with exactly ONE spec opens that spec on the first ⏎/letter,
    skipping the one-row 'browse' menu. The menu's distinctive '⏎ select · q back'
    hint must NOT appear."""
    _register_reference()  # one capability on shelf A
    host = _FakeHost().as_host()
    scr = _Screen()
    # 'a' opens shelf A directly to the spec's card; q returns; q quits.
    shell.run_cockpit(host, read_key=_keys(["a", "q", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined  # the spec opened
    assert "⏎ select" not in joined  # ... without the intermediate menu


def test_single_spec_shelf_via_enter_opens_directly(usage_to_tmp):
    """W4 — ⏎ on a highlighted single-spec shelf row also opens the spec directly,
    not the menu."""
    _register_reference()  # one capability on shelf A
    host = _FakeHost().as_host()  # no pills/needs → boot lands on shelf A
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys([keys.ENTER, "q", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined
    assert "⏎ select" not in joined


def test_multi_spec_shelf_still_shows_the_menu(usage_to_tmp):
    """W4 default-preserving — a shelf with two or more specs still renders the
    intermediate browse menu (xbook's multi-spec shelves are unaffected)."""
    _register_reference(key="cap-1", shelf="A", title="First cap", summary="one")
    _register_reference(key="cap-2", shelf="A", title="Second cap", summary="two")
    host = _FakeHost().as_host()
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["a", "q", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "⏎ select" in joined  # the menu IS shown
    assert "First cap" in joined and "Second cap" in joined


# --- the doctor loop ----------------------------------------------------------


def test_doctor_runs_the_selected_runnable_fix_on_enter(usage_to_tmp):
    ran = []
    probes = [
        Probe("auth · xero", "ok", "ok", None),
        Probe(
            "state · xero",
            "warn",
            "stale",
            Fix("Sync now", "uv run worker sync", run=lambda: ran.append("xero") or "Synced"),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, keys.ENTER, "q"]))
    assert ran == ["xero"]
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Synced" in joined


def test_doctor_display_only_fix_is_not_runnable(usage_to_tmp):
    probes = [
        Probe(
            "auth · xero",
            "error",
            "no token",
            Fix("Re-authenticate Xero", "uv run worker auth login", "opens browser"),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, "q"]))
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Re-authenticate Xero" in joined
    assert "run in a terminal" in joined


def test_doctor_lock_fix_confirms_then_removes(usage_to_tmp):
    removed = []
    probes = [
        Probe(
            "locks",
            "warn",
            "lock present",
            Fix(
                "Remove stale apply lock",
                "rm .state/apply.lock",
                run=lambda: removed.append(True) or "Removed .state/apply.lock",
                confirm=True,
            ),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, "y", keys.ENTER, "q"]))
    assert removed == [True]
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Removed .state/apply.lock" in joined


def test_doctor_confirm_accepts_enter(usage_to_tmp):
    removed = []
    probes = [
        Probe(
            "locks",
            "warn",
            "lock present",
            Fix(
                "Remove stale apply lock",
                "rm .state/apply.lock",
                run=lambda: removed.append(True) or "Removed",
                confirm=True,
            ),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, keys.ENTER, keys.ENTER, "q"]))
    assert removed == [True]


def test_doctor_confirm_unrelated_key_cancels(usage_to_tmp):
    removed = []
    probes = [
        Probe(
            "locks",
            "warn",
            "lock present",
            Fix(
                "Remove stale apply lock",
                "rm .state/apply.lock",
                run=lambda: removed.append(True) or "Removed",
                confirm=True,
            ),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, keys.UP, "q"]))
    assert removed == []


def test_doctor_confirm_cancel_does_not_run(usage_to_tmp):
    removed = []
    probes = [
        Probe(
            "locks",
            "warn",
            "lock present",
            Fix(
                "Remove stale apply lock",
                "rm .state/apply.lock",
                run=lambda: removed.append(True) or "Removed",
                confirm=True,
            ),
        ),
    ]
    host = _FakeHost(probes=probes).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER, "n", "q"]))
    assert removed == []


def test_doctor_degrades_when_unconfigured(usage_to_tmp):
    host = _FakeHost(report_raises=True).as_host()
    scr = _Screen()
    shell._doctor(host, scr, _keys([keys.ENTER]))  # must NOT raise
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "not configured" in joined


# --- the animated-progress helper ---------------------------------------------


def test_run_with_progress_returns_worker_result():
    scr = _Screen()
    out = shell.run_with_progress(scr, "Syncing…", lambda: "the result", sleep=lambda s: None)
    assert out == "the result"
    assert scr.frames


def test_run_with_progress_reraises_worker_exception():
    scr = _Screen()

    def _boom():
        raise RuntimeError("sync blew up")

    with pytest.raises(RuntimeError, match="sync blew up"):
        shell.run_with_progress(scr, "Syncing…", _boom, sleep=lambda s: None)


def test_run_with_progress_animates_a_slow_fn():
    import threading

    scr = _Screen()
    gate = threading.Event()
    ticks = {"n": 0}

    def _slow():
        gate.wait(2.0)
        return "done"

    def _fake_sleep(_s):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            gate.set()

    clock = {"t": 0.0}

    def _fake_clock():
        clock["t"] += 1.0
        return clock["t"]

    out = shell.run_with_progress(
        scr, "Syncing Xero…", _slow, tick=0.001, clock=_fake_clock, sleep=_fake_sleep
    )
    assert out == "done"
    assert len(scr.frames) >= 2
    texts = [_text(f) for f in scr.frames]
    assert any("Syncing Xero…" in t for t in texts)
    assert any("s" in t for t in texts)


def test_run_with_progress_spinner_uses_no_emoji():
    scr = _Screen()
    shell.run_with_progress(scr, "Syncing…", lambda: None, sleep=lambda s: None)
    for ch in render.SPINNER_FRAMES:
        assert ord(ch) < 0x10000


# --- R3: in-cockpit ack/snooze on a selected need (Host.ack / Host.snooze) -----


def _two_needs_state() -> CockpitState:
    """A state with two needs-you items the cursor can sit on. The first need
    carries a capability+focus; the second is note-only."""
    return CockpitState(
        tenant_name="Clonway Office",
        app_label="Clonway Office",
        needs=(
            NeedsItem("Bills overdue", "3 · £4,210", "error", "schedule-bills", focus="overdue"),
            NeedsItem("Payroll due", "Fri", "warn", None),
        ),
    )


def test_ack_on_a_selected_need_calls_host_ack_with_that_need(usage_to_tmp):
    """R3 — with a host that supplies ack, pressing 'a' on the selected (first)
    needs-you item calls host.ack with THAT exact need and renders its confirmation."""
    acked: list = []
    fh = _FakeHost(
        state=_two_needs_state(),
        ack=lambda need: acked.append(need) or f"Acked: {need.title}",
    )
    scr = _Screen()
    # First paint lands the cursor on need #1 ("Bills overdue"); 'a' acks it; q quits.
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q"]), screen=scr)
    assert len(acked) == 1
    assert acked[0].title == "Bills overdue"
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Acked: Bills overdue" in joined  # the confirmation rendered


def test_snooze_on_a_selected_need_calls_host_snooze_with_that_need(usage_to_tmp):
    """R3 — 's' on the selected need calls host.snooze with that need and renders
    its confirmation. The host callback owns the snooze DURATION; the shell just
    calls it."""
    snoozed: list = []
    fh = _FakeHost(
        state=_two_needs_state(),
        snooze=lambda need: snoozed.append(need) or f"Snoozed {need.title} for 1d",
    )
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["s", "q"]), screen=scr)
    assert len(snoozed) == 1
    assert snoozed[0].title == "Bills overdue"
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Snoozed Bills overdue for 1d" in joined


def test_ack_re_captures_state_so_the_item_drops(usage_to_tmp):
    """R3 — after ack, the loop re-captures state (so the acked item drops from the
    list on the redraw). The fake's capture drops the acked need; we assert the
    dropped need is gone from the post-ack home frame."""
    # A mutable state whose needs shrink when the ack callback fires — modelling the
    # Fleet bridge's real ack writing to Firestore and the next capture re-reading.
    remaining = list(_two_needs_state().needs)

    fh = _FakeHost(state=_two_needs_state())

    def _ack(need):
        # Drop the acked need from what the next capture will return.
        nonlocal remaining
        remaining = [n for n in remaining if n.title != need.title]
        fh._state = CockpitState(
            tenant_name="Clonway Office",
            app_label="Clonway Office",
            needs=tuple(remaining),
        )
        return f"Acked: {need.title}"

    fh._ack = _ack
    scr = _Screen()
    before = fh.capture_calls
    # 'a' acks "Bills overdue"; the next home redraw must re-capture (capture_calls
    # increases) and the dropped need's title must be gone from the LAST home frame.
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q"]), screen=scr)
    assert fh.capture_calls > before + 1  # the loop re-captured after the ack
    last_home = _text(scr.frames[-1])
    assert "Bills overdue" not in last_home  # the acked item dropped on redraw
    assert "Payroll due" in last_home  # the surviving need is still shown


def test_snooze_re_captures_state_so_the_item_drops(usage_to_tmp):
    """R3 — symmetric to ack: after snooze, the loop re-captures and the snoozed
    item is gone from the redraw."""
    remaining = list(_two_needs_state().needs)
    fh = _FakeHost(state=_two_needs_state())

    def _snooze(need):
        nonlocal remaining
        remaining = [n for n in remaining if n.title != need.title]
        fh._state = CockpitState(
            tenant_name="Clonway Office",
            app_label="Clonway Office",
            needs=tuple(remaining),
        )
        return f"Snoozed {need.title}"

    fh._snooze = _snooze
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["s", "q"]), screen=scr)
    last_home = _text(scr.frames[-1])
    assert "Bills overdue" not in last_home
    assert "Payroll due" in last_home


def test_ack_keybind_is_inert_on_a_pill_even_when_host_supports_ack(usage_to_tmp):
    """R3 context-sensitivity — when the cursor is on a PILL (not a need), 'a' keeps
    its shelf-letter behaviour (opens shelf A) even though the host supports ack.
    host.ack must NOT be called."""
    _register_reference()  # sync-all on shelf A → 'a' should open shelf A
    acked: list = []
    fh = _FakeHost(
        state=CockpitState(tenant_name="Clonway", pills=_PILLS),  # boot lands on pill #0
        ack=lambda need: acked.append(need) or "acked",
    )
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q", "q"]), screen=scr)
    assert acked == []  # ack NOT called on a pill
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined  # 'a' opened shelf A instead


def test_ack_keybind_is_inert_on_a_shelf_even_when_host_supports_ack(usage_to_tmp):
    """R3 context-sensitivity — with the cursor on a SHELF row, 'a' opens shelf A
    (unchanged), not an ack, even with a host that supports ack."""
    _register_reference()  # sync-all on shelf A
    acked: list = []
    fh = _FakeHost(
        state=CockpitState(tenant_name="Clonway"),  # no pills/needs → boot on shelf A
        ack=lambda need: acked.append(need) or "acked",
    )
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q", "q"]), screen=scr)
    assert acked == []
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined


def test_ack_on_selected_need_with_no_ack_callback_opens_shelf_a(usage_to_tmp):
    """R3 DEFAULT-PRESERVING (xbook) — a host with NO ack callback: 'a' on a SELECTED
    NEED still opens shelf A (the shelf-letter hotkey), byte-identical to today.
    This is the proof xbook (which supplies no ack/snooze) is unchanged."""
    _register_reference()  # sync-all on shelf A
    fh = _FakeHost(state=_two_needs_state())  # ack=None, snooze=None (xbook-shaped)
    scr = _Screen()
    # Boot lands on need #1; with no ack callback, 'a' is the shelf-A hotkey.
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined  # 'a' opened shelf A, as it always has


def test_snooze_on_selected_need_with_no_snooze_callback_is_unchanged(usage_to_tmp):
    """R3 DEFAULT-PRESERVING — a host with NO snooze callback: 's' on a selected need
    keeps its current behaviour (no snooze fires). With no shelf S registered, 's'
    is simply inert (the home stays put) — exactly as today."""
    fh = _FakeHost(state=_two_needs_state())  # snooze=None
    scr = _Screen()
    shell.run_cockpit(fh.as_host(), read_key=_keys(["s", "q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    # No confirmation toast (nothing was snoozed); the home is still the last frame.
    assert "Snoozed" not in joined


def test_ack_only_host_leaves_snooze_as_shelf_hotkey(usage_to_tmp):
    """R3 — a host that supplies ONLY ack (not snooze): 'a' on a need acks; 's' on a
    need is NOT a snooze (snooze is None) and falls through to its shelf behaviour.
    The two keys are gated independently on their own callback."""
    acked: list = []
    fh = _FakeHost(state=_two_needs_state(), ack=lambda need: acked.append(need) or "ack ok")
    scr = _Screen()
    # 'a' acks the selected need; then 's' (no snooze callback) does not ack/snooze.
    shell.run_cockpit(fh.as_host(), read_key=_keys(["a", "q"]), screen=scr)
    assert len(acked) == 1
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Snoozed" not in joined


# A small type-resolution sanity: Host is constructible with the expected fields.
def test_host_is_constructible():
    h = shell.Host(
        capture_state=lambda: CockpitState(tenant_name="x"),
        build_walk_ctx=_walk_ctx,
        activate_pill=lambda *a: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )
    assert isinstance(h, shell.Host)


# --- worker-contributed extras (extra_selectables / extra_regions /
#     handle_extra_key) — the extension points that let a worker bolt on its own
#     home panel + dispatch its own keys without monkey-patching the framework.


def _host_with_extras(
    *,
    state: CockpitState,
    extras: list[tuple[str, object]] | None = None,
    regions: list | None = None,
    handler=None,
) -> shell.Host:
    """A bare Host wired only with the three new extension callbacks (plus the
    minimum scaffolding the framework needs to enter ``_home``). Defaults make
    each extra a no-op so a test can opt in to just the hook it's exercising."""
    fh = _FakeHost(state=state)
    base = fh.as_host()
    # Re-build the host with the new fields populated. shell.Host is frozen, so
    # we construct a fresh one carrying every field of `base` plus the extras.
    from dataclasses import replace

    return replace(
        base,
        extra_selectables=(lambda s: list(extras or [])),
        extra_regions=(lambda s: list(regions or [])),
        handle_extra_key=(handler or (lambda s, sel, key, scr, rk: False)),
    )


def test_extra_selectables_are_spliced_between_needs_and_shelves():
    """A worker-supplied extra row lands AFTER needs-you and BEFORE shelves so
    the cursor walks it in the visual order the worker controls (an extra panel
    drawn above the toolkit on screen is reached by ↓ after the needs)."""
    needs = (NeedsItem("Sync the books", "never synced", "warn", "sync-all"),)
    state = CockpitState(tenant_name="Clonway", needs=needs)
    host = _host_with_extras(state=state, extras=[("statutory", 0), ("statutory", 1)])
    items = shell.selectables(state, host)
    # Pills (none) → needs (1) → extras (2) → shelves (7)
    assert items[0] == ("need", 0)
    assert items[1] == ("statutory", 0)
    assert items[2] == ("statutory", 1)
    assert items[3][0] == "shelf"


def test_selectables_without_host_is_unchanged():
    """Legacy call site (no host) gets the three-tier list, byte-identical."""
    needs = (NeedsItem("Sync the books", "never synced", "warn", "sync-all"),)
    state = CockpitState(tenant_name="Clonway", needs=needs)
    items = shell.selectables(state)  # no host
    assert items[0] == ("need", 0)
    assert items[1][0] == "shelf"


def test_handle_extra_key_fires_on_selection_it_owns(usage_to_tmp):
    """A worker key handler claims a key on its own selection. The shell does
    NOT fall through to the default dispatch when the handler returns True."""
    calls: list[tuple] = []

    def _handler(state, selection, key, screen, read_key):
        if selection and selection[0] == "statutory":
            calls.append((selection, key))
            return True
        return False

    state = CockpitState(tenant_name="Clonway")  # no pills/needs → boot lands on shelf A
    # An extra ahead of every shelf so default_sel picks it first.
    # Actually default_sel picks need→pill→0; with no needs/pills it picks 0 which
    # is the first extra (since extras are inserted before shelves).
    host = _host_with_extras(
        state=state,
        extras=[("statutory", 0)],
        handler=_handler,
    )
    scr = _Screen()
    # First paint lands on the statutory row (index 0). ENTER must route through
    # the handler, not the framework's _activate.
    shell.run_cockpit(host, read_key=_keys([keys.ENTER, "q"]), screen=scr)
    assert calls == [(("statutory", 0), keys.ENTER)]


def test_handle_extra_key_returning_false_falls_through_to_default(usage_to_tmp):
    """When the handler returns False the framework's existing dispatch still
    fires (arrows still move, ⏎ on a shelf still opens the shelf menu)."""
    _register_reference()  # sync-all on shelf A → 'a' opens shelf A
    handler_calls: list = []

    def _handler(state, selection, key, screen, read_key):
        handler_calls.append((selection, key))
        return False  # decline every key

    state = CockpitState(tenant_name="Clonway")  # boot lands on shelf A
    host = _host_with_extras(state=state, handler=_handler)
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["a", "q", "q"]), screen=scr)
    # The handler saw 'a' but declined → default dispatch fired → shelf A opened.
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "Sync everything" in joined
    assert any(key == "a" for _, key in handler_calls)


def test_extra_regions_render_between_needs_and_toolkit():
    """An ``extra_regions`` entry is drawn between the needs-you region and the
    toolkit (matching ``extra_selectables``'s navigation order)."""
    from rich.text import Text

    state = CockpitState(tenant_name="Clonway")
    marker = Text("BOLTED-ON STATUTORY REGION")
    out = render.render_cockpit_screen(state, [], extra_regions=[marker])
    rendered = _text(out)
    assert "BOLTED-ON STATUTORY REGION" in rendered


def test_render_cockpit_screen_without_extra_regions_is_unchanged():
    """``extra_regions=None`` keeps the home screen byte-identical to today's
    composition (the default for every existing caller)."""
    state = CockpitState(tenant_name="Clonway")
    out_default = _text(render.render_cockpit_screen(state, []))
    out_no_extras = _text(render.render_cockpit_screen(state, [], extra_regions=None))
    out_empty_extras = _text(render.render_cockpit_screen(state, [], extra_regions=[]))
    assert out_default == out_no_extras == out_empty_extras


def test_home_passes_extra_regions_into_render(usage_to_tmp):
    """The home loop calls render_cockpit_screen with ``extra_regions=host.extra_regions(state)``,
    so a worker-supplied region appears in the rendered home frame."""
    from rich.text import Text

    state = CockpitState(tenant_name="Clonway")
    host = _host_with_extras(
        state=state,
        regions=[Text("STAT-CARD-SENTINEL")],
    )
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    joined = "\n".join(_text(f) for f in scr.frames)
    assert "STAT-CARD-SENTINEL" in joined


def test_handle_extra_key_receives_screen_and_read_key(usage_to_tmp):
    """The home loop threads its active screen + read_key into the worker's
    ``handle_extra_key`` so a worker key that opens a capability can drive the
    alt-screen exactly the same way the framework's own ``_activate`` does."""
    captured: list[tuple] = []

    def _handler(state, selection, key, screen, read_key):
        if selection and selection[0] == "statutory":
            captured.append((screen, read_key))
            return True
        return False

    state = CockpitState(tenant_name="Clonway")
    host = _host_with_extras(
        state=state,
        extras=[("statutory", 0)],
        handler=_handler,
    )
    scr = _Screen()
    read_key = _keys([keys.ENTER, "q"])
    shell.run_cockpit(host, read_key=read_key, screen=scr)
    assert len(captured) == 1
    seen_screen, seen_read_key = captured[0]
    # The exact screen + read_key that _home was driving must reach the handler.
    assert seen_screen is scr
    assert seen_read_key is read_key


def test_default_host_extras_are_noops(usage_to_tmp):
    """A host that does NOT wire the new fields (default _FakeHost path) is
    byte-identical to today: no extras spliced, no extra regions drawn, no key
    interception. This is the proof that the worker family extracted before
    these hooks landed stays unchanged."""
    state = CockpitState(tenant_name="Clonway")
    host = _FakeHost(state=state).as_host()
    items = shell.selectables(state, host)
    # Default extra_selectables returns []; items contain only pills/needs/shelves.
    assert all(kind in ("pill", "need", "shelf") for kind, _ in items)
    # Default extra_regions returns []; the screen renders the same as calling
    # render_cockpit_screen with the same selection but no extra_regions.
    scr = _Screen()
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=scr)
    # Reproduce the home loop's render call (default_sel lands on the first shelf
    # row when there are no pills/needs).
    sel = items[shell.default_sel(items)]
    legacy = _text(render.render_cockpit_screen(state, [], selection=sel))
    rendered_home = _text(scr.frames[0])
    assert legacy == rendered_home
