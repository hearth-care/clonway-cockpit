"""Instant Home: a provisional Home painted at once, the live capture off the main
thread, and a loading page with real progress when there is nothing saved to show.

Opt-in through ``Host.provisional_state``; the legacy blocking path stays covered by
``tests/test_shell.py``."""

from __future__ import annotations

import contextvars
import threading
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell
from clonway_cockpit.registry import WizardContext, clear_capabilities
from clonway_cockpit.state import CockpitState, NeedsItem

_WAIT = 5.0  # generous ceiling for thread hand-offs; never reached when the code is right

SAVED = CockpitState(
    tenant_name="Saved Ltd",
    freshness_note="as of 22:31",
    needs=(
        NeedsItem("Saved need one", "", "warn", None),
        NeedsItem("Saved need two", "", "warn", None),
    ),
)
LIVE = CockpitState(
    tenant_name="Live Ltd",
    needs=(NeedsItem("Live need", "", "warn", None),),
)


class _Screen:
    def __init__(self, on_frame=None) -> None:
        self.frames: list[Any] = []
        self._on_frame = on_frame

    def update(self, renderable: Any) -> None:
        self.frames.append(renderable)
        if self._on_frame is not None:
            self._on_frame(_text(renderable))

    def texts(self) -> list[str]:
        return [_text(frame) for frame in self.frames]


def _text(frame: Any) -> str:
    console = Console(record=True, width=120)
    console.print(frame)
    return console.export_text()


def _host(**changes: Any) -> shell.Host:
    usage = SimpleNamespace(record=lambda *args: None, load=lambda: {})
    host = shell.Host(
        capture_state=lambda: LIVE,
        build_walk_ctx=lambda screen, read_key, **kwargs: WizardContext(
            state={},
            client=None,
            console=SimpleNamespace(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            **kwargs,
        ),
        activate_pill=lambda pill, screen, read_key: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda report: [],
        doctor_fixes_for=lambda probes: [],
        doctor_unconfigured_renderable=lambda: "unconfigured",
        usage=usage,
        on_open=lambda: None,
    )
    return replace(host, **changes)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_capabilities()
    yield
    clear_capabilities()


def _home_models(models: list[Any]) -> list[Any]:
    return [m for m in models if m.kind == "home"]


def test_saved_home_is_painted_at_once_and_swapped_for_live_without_a_key():
    release = threading.Event()
    frames_at_first_key: list[int] = []
    models: list[Any] = []

    def capture() -> CockpitState:
        assert release.wait(_WAIT)
        return LIVE

    # The capture is held until the saved Home has been painted, proving that
    # paint did not wait for it.
    screen = _Screen(on_frame=lambda text: release.set())

    def read_key() -> str:
        frames_at_first_key.append(len(screen.frames))
        return "q"

    host = _host(capture_state=capture, provisional_state=lambda: SAVED, on_screen=models.append)
    shell.run_cockpit(host, read_key=read_key, screen=screen)

    first, second = screen.texts()
    assert "Saved Ltd" in first and "as of 22:31 · refreshing…" in first
    assert "Live Ltd" in second and "refreshing" not in second and "as of" not in second
    assert frames_at_first_key == [2]  # the live Home arrived before any key was read
    homes = _home_models(models)
    assert [m.meta["tenant_name"] for m in homes] == ["Live Ltd"]


def test_keys_typed_during_the_refresh_act_on_the_saved_home(monkeypatch):
    """A cursor move while the capture runs moves the cursor on the saved Home at
    once; on the swap the cursor is kept within the live Home's rows."""
    release = threading.Event()
    typed = [keys.DOWN]
    models: list[Any] = []

    def capture() -> CockpitState:
        assert release.wait(_WAIT)
        return LIVE

    monkeypatch.setattr(shell.keys, "pending", lambda timeout=0.0: bool(typed))

    def read_key() -> str:
        if typed:
            key = typed.pop(0)
            if not typed:
                release.set()
            return key
        return "q"

    screen = _Screen()
    host = _host(capture_state=capture, provisional_state=lambda: SAVED, on_screen=models.append)
    shell.run_cockpit(host, read_key=read_key, screen=screen)

    saved, live = screen.texts()
    (cursor_line,) = [line for line in saved.splitlines() if "❯" in line]
    assert "Saved need two" in cursor_line
    assert "Live Ltd" in live
    # Row 1 on the saved Home; the live Home has one need, so row 1 is shelf A.
    (home,) = _home_models(models)
    assert home.selection == "shelf:A"


def test_a_failed_refresh_keeps_the_saved_home_marked_and_r_retries():
    calls: list[int] = []
    models: list[Any] = []

    painted = threading.Event()

    def capture() -> CockpitState:
        calls.append(1)
        assert painted.wait(_WAIT)
        if len(calls) == 1:
            raise RuntimeError("tenant unreachable")
        return LIVE

    scripted = ["r", "q"]
    screen = _Screen(on_frame=lambda text: painted.set())
    host = _host(capture_state=capture, provisional_state=lambda: SAVED, on_screen=models.append)
    shell.run_cockpit(host, read_key=lambda: scripted.pop(0), screen=screen)

    texts = screen.texts()
    assert "Saved Ltd" in texts[0] and "refreshing…" in texts[0]
    failed = texts[1]
    assert "Saved Ltd" in failed
    assert "as of 22:31 · couldn't refresh — press r to retry" in failed
    assert len(calls) == 2  # r started a second capture
    assert "Live Ltd" in texts[-1] and "couldn't refresh" not in texts[-1]
    assert [m.meta["tenant_name"] for m in _home_models(models)] == ["Live Ltd"]


def test_agent_mode_never_sees_the_saved_home():
    provisional_calls: list[int] = []
    models: list[Any] = []

    def provisional() -> CockpitState:
        provisional_calls.append(1)
        return SAVED

    host = _host(agent_mode=True, provisional_state=provisional, on_screen=models.append)
    shell.run_home(host, _Screen(), lambda: "q")

    assert provisional_calls == []
    assert [m.meta["tenant_name"] for m in _home_models(models)] == ["Live Ltd"]
    assert all("freshness_note" not in m.meta for m in models)


def test_loading_page_ticks_each_stage_as_the_capture_reports_it():
    """With nothing saved, a framed checklist shows each start-up stage, ticked
    only when the capture itself reports it done."""
    first_ticked = threading.Event()
    models: list[Any] = []

    def on_frame(text: str) -> None:
        if "✓ Loading secrets" in text:
            first_ticked.set()

    def background(reporter):
        reporter.start("secrets")
        reporter.done("secrets")
        reporter.start("ledger")
        assert first_ticked.wait(_WAIT)
        reporter.done("ledger")
        return lambda: LIVE

    screen = _Screen(on_frame=on_frame)
    host = _host(
        provisional_state=lambda: None,
        capture_state_background=background,
        startup_stages=(("secrets", "Loading secrets"), ("ledger", "Reading the ledger")),
        on_screen=models.append,
    )
    shell.run_cockpit(host, read_key=lambda: "q", screen=screen)

    texts = screen.texts()
    midway = next(t for t in texts if "✓ Loading secrets" in t)
    assert "Opening xbook" in midway
    assert "✓ Reading the ledger" not in midway
    assert "Live Ltd" in texts[-1] and "refreshing" not in texts[-1]
    progress = [m for m in models if m.kind == "walk.progress"]
    assert progress and progress[0].regions[0].rows[0].label == "Loading secrets"
    assert [m.meta["tenant_name"] for m in _home_models(models)] == ["Live Ltd"]


def test_loading_page_failure_offers_a_retry_instead_of_crashing():
    calls: list[int] = []

    def capture() -> CockpitState:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return LIVE

    scripted = ["x", "q"]  # x on the failure page retries; q quits the live Home
    screen = _Screen()
    host = _host(capture_state=capture, provisional_state=lambda: None)
    shell.run_cockpit(host, read_key=lambda: scripted.pop(0), screen=screen)

    texts = screen.texts()
    assert any("Home couldn't load" in t and "RuntimeError" in t for t in texts)
    assert "Live Ltd" in texts[-1]
    assert len(calls) == 2


def test_returning_to_home_refreshes_in_the_background_without_dropping_keys(monkeypatch):
    discarded: list[bool] = []
    monkeypatch.setattr(shell.keys, "discard_pending", lambda: discarded.append(True))
    release = threading.Event()
    calls: list[int] = []

    def capture() -> CockpitState:
        calls.append(1)
        if len(calls) > 1:  # the refresh after returning from help
            assert release.wait(_WAIT)
        return LIVE

    def on_frame(text: str) -> None:
        if "Live Ltd" in text and "refreshing…" in text:
            release.set()

    screen = _Screen(on_frame=on_frame)
    scripted = ["?", "x", "q"]
    host = _host(capture_state=capture, provisional_state=lambda: None)
    shell.run_cockpit(host, read_key=lambda: scripted.pop(0), screen=screen)

    texts = screen.texts()
    back = next(i for i, t in enumerate(texts) if "Live Ltd" in t and "refreshing…" in t)
    assert "Live Ltd" in texts[back + 1] and "refreshing" not in texts[back + 1]
    assert discarded == []
    assert len(calls) == 2


def test_context_variables_set_by_the_capture_reach_the_home_loop():
    """The capture runs off-thread, but a context variable it sets is visible on
    the main thread afterwards, exactly as if it had run inline."""
    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="unset")
    seen: list[str] = []

    def capture() -> CockpitState:
        marker.set("captured")
        return LIVE

    def read_key() -> str:
        seen.append(marker.get())
        return "q"

    host = _host(capture_state=capture, provisional_state=lambda: SAVED)
    contextvars.copy_context().run(shell.run_cockpit, host, read_key=read_key, screen=_Screen())

    assert seen == ["captured"]


def test_before_action_runs_for_actions_but_not_for_cursor_moves():
    calls: list[int] = []
    scripted = [keys.DOWN, keys.UP, "r", "?", "x", "q"]
    host = _host(before_action=lambda: calls.append(1))
    shell.run_cockpit(host, read_key=lambda: scripted.pop(0), screen=_Screen())
    assert calls == [1]  # only "?"; cursor moves, r and q pass straight through


def test_freshness_note_renders_under_the_header_and_in_the_model():
    state = CockpitState(tenant_name="Clonway", freshness_note="as of 22:31 · refreshing…")
    assert "as of 22:31 · refreshing…" in _text(render.render_header(state))
    model = render.model_cockpit_screen(state, [])
    assert model.meta["freshness_note"] == "as of 22:31 · refreshing…"
    assert (
        "freshness_note"
        not in render.model_cockpit_screen(replace(state, freshness_note=None), []).meta
    )


def test_a_worker_key_still_recaptures_before_home_is_shown_again():
    """A worker key (xbook's park) re-captures on the main thread as before, after
    letting any background capture finish, so the acted-on row moves at once."""
    calls: list[int] = []

    def capture() -> CockpitState:
        calls.append(1)
        return replace(LIVE, tenant_name=f"Live {len(calls)}")

    scripted = ["z", "q"]
    screen = _Screen()
    host = _host(
        capture_state=capture,
        provisional_state=lambda: SAVED,
        handle_extra_key=lambda state, sel, key, scr, rk: key == "z",
    )
    shell.run_cockpit(host, read_key=lambda: scripted.pop(0), screen=screen)

    texts = screen.texts()
    assert "Live 2" in texts[-1] and "refreshing" not in texts[-1]
    assert not any("Live 2" in t and "refreshing" in t for t in texts)
    assert len(calls) == 2
