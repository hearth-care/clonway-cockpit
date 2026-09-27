"""The viewport fits every page to the live terminal: short pages pass through
untouched, tall pages keep header and footer pinned around a scrollable middle, and a
resize repaints at the new size. Driven through a recorder that renders exactly what
Rich's alt-screen would show (``rich.screen.Screen`` at the console's size)."""

from __future__ import annotations

import io
import signal

import pytest
from rich.console import Console, Group
from rich.screen import Screen
from rich.text import Text

from clonway_cockpit import keys, render
from clonway_cockpit.viewport import Viewport


def _console(width: int = 80, height: int = 24) -> Console:
    return Console(
        width=width, height=height, file=io.StringIO(), force_terminal=True, color_system=None
    )


class _Recorder:
    """Stands in for ``console.screen()``: keeps each frame as the plain text rows
    the terminal would display."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.frames: list[list[str]] = []
        self.renderables: list[object] = []

    def update(self, renderable) -> None:
        self.renderables.append(renderable)
        lines = self.console.render_lines(Screen(renderable), self.console.options)
        self.frames.append(["".join(s.text for s in line) for line in lines])

    @property
    def last(self) -> list[str]:
        return self.frames[-1]


def _page(rows: int = 60, *, title: str = "Report", cursor: int | None = None):
    body = [Text(f"{'❯' if i == cursor else ' '} row {i:02d}") for i in range(rows)]
    # Title and key help each set off by a blank line, as the cockpit's screens are:
    # the default pins are then frame edge, padding, title/help and the blank line.
    return render.page(Group(Text(title), Text(""), *body, Text(""), Text("q quit · ⏎ open")))


def _visible_rows(frame: list[str]) -> list[int]:
    return [int(line.split("row ")[1][:2]) for line in frame if "row " in line]


def _note(frame: list[str]) -> str:
    return next(line for line in frame if "PgUp/PgDn" in line)


def _viewport(width: int = 80, height: int = 24) -> tuple[Viewport, _Recorder]:
    rec = _Recorder(_console(width, height))
    return Viewport(rec, rec.console), rec


def test_short_page_passes_through_unchanged():
    view, rec = _viewport()
    direct = _Recorder(_console())
    page = _page(5)
    direct.update(page)
    view.update(page)
    assert rec.renderables == [page]
    assert rec.last == direct.last
    assert not view.overflowing


def test_tall_page_pins_header_and_footer_with_a_scroll_note():
    view, rec = _viewport(80, 24)
    view.update(_page(60))
    frame = rec.last
    assert len(frame) == 24
    assert frame[0].lstrip().startswith("╭")
    assert "Report" in frame[2]
    assert frame[-1].lstrip().startswith("╰")
    assert "q quit" in frame[-3]
    note = _note(frame)
    assert frame.index(note) == 24 - 4 - 1
    assert "↓" in note and "below" in note and "↑" not in note
    # The note sits inside the frame: both side borders survive.
    assert note.startswith("│") and note.rstrip().endswith("│")
    assert _visible_rows(frame)[0] == 0
    assert all(len(line) == 80 for line in frame)


def test_page_down_and_up_move_and_clamp():
    view, rec = _viewport(80, 24)
    view.update(_page(60))
    first = _visible_rows(rec.last)
    view.scroll_page(1)
    moved = _visible_rows(rec.last)
    assert moved[0] == first[-1]  # one line of overlap between pages
    assert "↑" in _note(rec.last) and "↓" in _note(rec.last)
    for _ in range(20):
        view.scroll_page(1)
    assert _visible_rows(rec.last)[-1] == 59
    assert "↓" not in _note(rec.last)
    for _ in range(20):
        view.scroll_page(-1)
    assert _visible_rows(rec.last)[0] == 0
    assert "↑" not in _note(rec.last)
    view.scroll_to_end()
    assert _visible_rows(rec.last)[-1] == 59
    view.scroll_to_start()
    assert _visible_rows(rec.last)[0] == 0
    assert all(len(frame) == 24 for frame in rec.frames)


def test_different_screen_resets_scroll_same_screen_keeps_it():
    view, rec = _viewport()
    view.update(_page(60))
    view.scroll_page(1)
    view.scroll_page(1)
    scrolled = _visible_rows(rec.last)[0]
    assert scrolled > 0
    view.update(_page(60))  # same screen re-rendered (data refresh)
    assert _visible_rows(rec.last)[0] == scrolled
    view.update(_page(60, title="Another screen"))
    assert _visible_rows(rec.last)[0] == 0


def test_cursor_follow_keeps_the_selected_row_visible():
    view, rec = _viewport()
    view.update(_page(60, cursor=5))
    assert 5 in _visible_rows(rec.last)
    view.update(_page(60, cursor=40))
    rows = _visible_rows(rec.last)
    assert 40 in rows and 41 in rows  # one line of context below the cursor
    assert rows[-1] == 41  # moved the minimum distance
    view.update(_page(60, cursor=39))  # moving up inside the window does not scroll
    assert _visible_rows(rec.last) == rows


def test_manual_scroll_survives_a_redraw_until_the_cursor_moves():
    view, rec = _viewport()
    view.update(_page(60, cursor=5))
    read = view.wrap_read_key(iter([keys.PGDN, keys.PGDN, "x"]).__next__)
    assert read() == "x"
    assert 5 not in _visible_rows(rec.last)
    view.update(_page(60, cursor=5))  # redraw with the cursor where it was
    assert 5 not in _visible_rows(rec.last)
    view.update(_page(60, cursor=6))  # the cursor moved: follow it again
    assert 6 in _visible_rows(rec.last)


def test_resize_repaints_at_the_new_size():
    view, rec = _viewport(80, 24)
    before = signal.getsignal(signal.SIGWINCH)
    uninstall = view.install_resize_handler()
    try:
        view.update(_page(60))
        handler = signal.getsignal(signal.SIGWINCH)
        assert callable(handler)
        for width, height in ((100, 30), (120, 40)):
            rec.console.size = (width, height)
            handler(signal.SIGWINCH, None)
            assert len(rec.last) == height
            assert all(len(line) == width for line in rec.last)
            assert "PgUp/PgDn" in _note(rec.last)
            assert rec.last[-1].lstrip().startswith("╰")
    finally:
        uninstall()
    assert signal.getsignal(signal.SIGWINCH) == before


def test_resize_before_any_page_draws_nothing():
    view, rec = _viewport()
    uninstall = view.install_resize_handler()
    try:
        signal.getsignal(signal.SIGWINCH)(signal.SIGWINCH, None)
    finally:
        uninstall()
    assert rec.frames == []


def test_tiny_terminal_degrades_without_overflow():
    view, rec = _viewport(80, 8)
    view.update(_page(60, cursor=30))
    frame = rec.last
    assert len(frame) == 8
    assert frame[-1].lstrip().startswith("╰")
    assert "PgUp/PgDn" in _note(frame)
    assert 30 in _visible_rows(frame)


@pytest.mark.parametrize("height", [1, 2, 3, 4, 5])
def test_very_short_terminals_still_draw_exactly_their_height(height):
    view, rec = _viewport(80, height)
    view.update(_page(60))
    assert len(rec.last) == height
    assert rec.last[-1].lstrip().startswith("╰")


def test_wrap_read_key_swallows_scroll_keys_and_passes_others():
    view, rec = _viewport()
    view.update(_page(60))
    read = view.wrap_read_key(iter([keys.PGDN, "q"]).__next__)
    assert read() == "q"
    assert _visible_rows(rec.last)[0] > 0
    read = view.wrap_read_key(iter([keys.HOME, keys.DOWN]).__next__)
    assert read() == keys.DOWN
    assert _visible_rows(rec.last)[0] == 0


def test_home_and_end_pass_through_when_the_page_fits():
    view, _ = _viewport()
    view.update(_page(5))
    read = view.wrap_read_key(iter([keys.HOME, keys.END]).__next__)
    assert read() == keys.HOME
    assert read() == keys.END


def test_a_draw_requested_mid_draw_runs_once_afterwards():
    console = _console()
    calls: list[int] = []

    class _Reentrant(_Recorder):
        def update(self, renderable) -> None:
            super().update(renderable)
            if len(calls) == 0:
                calls.append(1)
                view.draw()  # what a SIGWINCH arriving mid-draw does

    rec = _Reentrant(console)
    view = Viewport(rec, console)
    view.update(_page(60))
    assert len(rec.frames) == 2


def test_attach_yields_wrapped_pair_and_restores_a_frozen_console_size(monkeypatch):
    rec = _Recorder(_console(80, 24))
    before = signal.getsignal(signal.SIGWINCH)
    with Viewport.attach(rec, rec.console, iter([keys.PGDN, "q"]).__next__) as (view, read):
        # A console frozen at 80x24 (COLUMNS/LINES exported) inside a 100x30 terminal.
        monkeypatch.setattr(view, "_live_size", lambda: (100, 30))
        view.update(_page(60))
        assert len(rec.last) == 30 and len(rec.last[0]) == 100
        assert read() == "q"
        assert signal.getsignal(signal.SIGWINCH) != before
    assert signal.getsignal(signal.SIGWINCH) == before
    assert tuple(rec.console.size) == (80, 24)
