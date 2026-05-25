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
    ):
        self._state = state or CockpitState(tenant_name="Clonway")
        self._probes = probes or []
        self._report_raises = report_raises
        self.pill_calls: list = []
        self.open_calls = 0
        self.usage = usage_module

    # --- shell.Host surface ------------------------------------------------
    def as_host(self) -> shell.Host:
        return shell.Host(
            capture_state=lambda: self._state,
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
    _register_reference()  # one capability on shelf A → rows = [it, Back]
    host = _FakeHost().as_host()
    scr = _Screen()
    # A → shelf (1 item); ↓↓ wraps onto Back; Enter returns; q quits.
    shell.run_cockpit(host, read_key=_keys(["a", keys.DOWN, keys.ENTER]), screen=scr)
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
