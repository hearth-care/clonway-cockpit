"""Fit every cockpit page to the live terminal: scroll what is too tall, repaint on resize.

Pages are drawn at their natural height onto the alternate screen, and Rich's
``Screen`` crops anything taller than the window at the bottom without saying so. At
80x24 that loses a Home page's toolkit and key-help footer, and a long report loses
most of itself. :class:`Viewport` sits between the shell and the screen: a page that
fits is passed through untouched, while a taller page keeps its header and footer
pinned, shows a window of the middle with a one-line "↑ n above · ↓ n below" note,
and scrolls with PgUp/PgDn (Home/End jump to either end).

It also repaints when the terminal is resized. The shell loop blocks waiting for a
keypress, so without a SIGWINCH handler nothing redraws until the next key. Rich's
``Console.size`` is re-read from the terminal on every call, except when ``COLUMNS``
or ``LINES`` is in the environment, which freezes it at those values for the life of
the console; the viewport reads the size from the console's own terminal each draw so
that case follows the window too.

Agent mode never sees any of this: agents read ``ScreenModel`` frames, not rendered
text. Without a real terminal (tests, pipes) the console's configured size is used,
so rendering stays deterministic.

Typical worker wiring::

    with console.screen() as scr, keys.raw_mode():
        with Viewport.attach(scr, console, read_key) as (view, view_keys):
            shell.run_home(host, view, view_keys)
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.control import Control
from rich.segment import Segment
from rich.text import Text

from clonway_cockpit import keys
from clonway_cockpit.render_chrome import DIM

# The design system's selected-row marker (U+276F); a body line carrying it is kept
# on screen when the selection moves.
_CURSOR = "❯"
# The page frame's side border (``box.ROUNDED``); used to draw the scroll note inside
# the frame rather than across it.
_BORDER = "│"
# The fewest body lines worth showing between the pins before the pins give way.
_MIN_BODY = 3
_DIGITS = re.compile(r"\d")


class _Target(Protocol):
    def update(self, renderable: RenderableType) -> None: ...


class _Lines:
    """Pre-rendered lines handed to the screen as one renderable, one row each."""

    def __init__(self, lines: list[list[Segment]]) -> None:
        self.lines = lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for index, line in enumerate(self.lines):
            if index:
                yield Segment.line()
            yield from line


def _plain(line: list[Segment]) -> str:
    return "".join(segment.text for segment in line)


class Viewport:
    """A scrolling, resize-aware stand-in for the alt-screen's ``update``.

    ``top`` and ``bottom`` are how many rendered lines stay pinned when a page is too
    tall: by default the frame's top edge, padding and title, and the key-help line,
    padding and bottom edge."""

    def __init__(self, screen: _Target, console: Console, *, top: int = 4, bottom: int = 4):
        self._screen = screen
        self._console = console
        self.top = top
        self.bottom = bottom
        self._renderable: RenderableType | None = None
        self._offset = 0
        # Set by PgUp/PgDn/Home/End; stops cursor-follow from undoing a manual scroll
        # until an update moves the cursor or shows a different page.
        self._manual = False
        self._fresh = False
        self._identity: str | None = None
        self._cursor: int | None = None
        self._drawing = False
        self._dirty = False
        self._rows = 0
        self._body_len = 0
        self._overflowing = False
        self._restore_size: tuple[Any, Any] | None = None

    @classmethod
    @contextlib.contextmanager
    def attach(
        cls,
        screen: _Target,
        console: Console,
        read_key: Callable[[], str] = keys.read_key,
        *,
        top: int = 4,
        bottom: int = 4,
    ) -> Iterator[tuple[Viewport, Callable[[], str]]]:
        """Wrap an open screen for its lifetime: yields ``(viewport, read_key)`` to pass
        to the shell in place of the screen and key reader, and removes the resize
        handler on exit. Enter it inside ``console.screen()`` and leave it before any
        shell-out child runs, so a resize never paints over the child's terminal."""
        view = cls(screen, console, top=top, bottom=bottom)
        uninstall = view.install_resize_handler()
        try:
            yield view, view.wrap_read_key(read_key)
        finally:
            uninstall()
            view._release_console_size()

    @property
    def overflowing(self) -> bool:
        """True when the last drawn page was taller than the terminal."""
        return self._overflowing

    def update(self, renderable: RenderableType) -> None:
        self._renderable = renderable
        self._fresh = True
        self.draw()

    def draw(self) -> None:
        """Redraw the current page at the terminal's current size. Re-entrant calls
        (a resize arriving mid-draw) are folded into one more pass afterwards."""
        if self._drawing:
            self._dirty = True
            return
        self._drawing = True
        try:
            self._dirty = True
            while self._dirty:
                self._dirty = False
                self._draw_once()
        finally:
            self._drawing = False

    def scroll_page(self, direction: int) -> None:
        step = max(1, self._rows - 1)
        self._scroll_to(self._offset + (step if direction > 0 else -step))

    def scroll_to_start(self) -> None:
        self._scroll_to(0)

    def scroll_to_end(self) -> None:
        self._scroll_to(self._body_len)

    def wrap_read_key(self, read_key: Callable[[], str]) -> Callable[[], str]:
        """A key reader that handles scrolling itself and passes every other key on.
        PgUp/PgDn always scroll; Home/End scroll only on a page that overflows, so a
        screen that fits can still give them a meaning of its own."""

        def _read() -> str:
            while True:
                key = read_key()
                if key == keys.PGDN:
                    self.scroll_page(1)
                elif key == keys.PGUP:
                    self.scroll_page(-1)
                elif key == keys.HOME and self._overflowing:
                    self.scroll_to_start()
                elif key == keys.END and self._overflowing:
                    self.scroll_to_end()
                else:
                    return key

        return _read

    def install_resize_handler(self) -> Callable[[], None]:
        """Repaint the current page whenever the terminal is resized. Returns a
        callable that puts the previous SIGWINCH handler back. A no-op where SIGWINCH
        does not exist or off the main thread (where handlers cannot be set)."""
        sig = getattr(signal, "SIGWINCH", None)
        if sig is None:
            return lambda: None
        previous = signal.getsignal(sig)

        def _on_resize(signum: int, frame: Any) -> None:
            if callable(previous):
                previous(signum, frame)
            if self._renderable is not None:
                self.draw()

        try:
            signal.signal(sig, _on_resize)
        except ValueError:
            return lambda: None

        def _uninstall() -> None:
            with contextlib.suppress(ValueError, TypeError):
                signal.signal(sig, previous)

        return _uninstall

    def _scroll_to(self, offset: int) -> None:
        self._offset = max(0, min(offset, self._body_len - self._rows))
        self._manual = True
        self.draw()

    def _live_size(self) -> tuple[int, int]:
        size = self._console.size
        # io.UnsupportedOperation (a StringIO under test) is both OSError and ValueError.
        with contextlib.suppress(AttributeError, OSError, ValueError):
            fd = self._console.file.fileno()
            if os.isatty(fd):
                live = os.get_terminal_size(fd)
                if live.columns > 0 and live.lines > 0:
                    return live.columns, live.lines
        return size.width, size.height

    def _hold_console_size(self, width: int, height: int) -> None:
        # Only reached when the console's size is frozen (COLUMNS/LINES exported) and
        # disagrees with the terminal: the screen renders at console.size, so it must
        # match. The original setting is put back when the viewport is released.
        if self._restore_size is None:
            self._restore_size = (self._console._width, self._console._height)
        self._console.size = (width, height)

    def _release_console_size(self) -> None:
        if self._restore_size is not None:
            self._console._width, self._console._height = self._restore_size
            self._restore_size = None

    def _pins(self, height: int) -> tuple[int, int]:
        """Header and footer pins for a terminal ``height`` rows tall, shrunk in turn
        (never below the footer's last line) until the body keeps ``_MIN_BODY`` rows
        and the scroll note fits."""
        top, bottom = self.top, max(1, self.bottom)
        while top + bottom + 1 + _MIN_BODY > height and (top > 0 or bottom > 1):
            if top > 0 and (top >= bottom or bottom <= 1):
                top -= 1
            else:
                bottom -= 1
        return top, bottom

    def _find_cursor(self, lines: list[list[Segment]]) -> int | None:
        for index in range(self.top, len(lines) - self.bottom):
            if _CURSOR in _plain(lines[index]):
                return index
        return None

    def _draw_once(self) -> None:
        renderable = self._renderable
        if renderable is None:
            return
        width, height = self._live_size()
        if (width, height) != tuple(self._console.size):
            self._hold_console_size(width, height)
        lines = self._console.render_lines(
            renderable, self._console.options.update_width(width), pad=True
        )
        if self._console.is_alt_screen:
            # Rich writes each full-screen frame from wherever the cursor was left, and
            # relies on the previous frame having left it on the last row. A resize
            # moves the cursor as the terminal reflows, so the first frame at the new
            # size would start mid-line; start every frame from the top-left instead.
            self._console.control(Control.home())
        identity = _DIGITS.sub("#", "\n".join(_plain(line) for line in lines[: self.top]))
        cursor = self._find_cursor(lines)
        if self._fresh:
            self._fresh = False
            # Digits are masked so the Home clock ticking over is not a "new page".
            if identity != self._identity:
                self._offset = 0
                self._manual = False
            elif cursor != self._cursor:
                self._manual = False
        self._identity, self._cursor = identity, cursor

        if len(lines) <= height or height <= 0:
            self._overflowing = False
            self._rows = self._body_len = 0
            self._screen.update(renderable)
            return

        self._overflowing = True
        top, bottom = self._pins(height)
        body = lines[top : len(lines) - bottom]
        note = 1 if height - top - bottom >= 2 else 0
        rows = height - top - bottom - note
        self._rows, self._body_len = rows, len(body)
        if not self._manual and cursor is not None:
            self._follow(cursor - top, rows)
        self._offset = max(0, min(self._offset, len(body) - rows))
        visible = body[self._offset : self._offset + rows]
        out = lines[:top] + visible
        if note:
            above = self._offset
            below = len(body) - self._offset - rows
            out.append(self._note(lines, top, bottom, width, above, below))
        out += lines[len(lines) - bottom :]
        self._screen.update(_Lines(out))

    def _follow(self, cursor: int, rows: int) -> None:
        """Move the window the least distance that shows body line ``cursor``, with a
        line of context either side where the window is tall enough."""
        context = 1 if rows >= 3 else 0
        if cursor < self._offset + context:
            self._offset = cursor - context
        elif cursor > self._offset + rows - 1 - context:
            self._offset = cursor - rows + 1 + context

    def _note(
        self,
        lines: list[list[Segment]],
        top: int,
        bottom: int,
        width: int,
        above: int,
        below: int,
    ) -> list[Segment]:
        parts = []
        if above:
            parts.append(f"↑ {above} above")
        if below:
            parts.append(f"↓ {below} below")
        parts.append("PgUp/PgDn scroll")
        text = Text(
            " · ".join(parts), style=DIM, justify="center", no_wrap=True, overflow="ellipsis"
        )
        # Borrow the frame's side borders from a pinned line so the note sits inside
        # the page frame; fall back to a bare full-width line for an unframed page.
        pinned = lines[len(lines) - bottom :] + lines[:top]
        frame = next((line for line in pinned if _plain(line).count(_BORDER) >= 2), None)
        if frame is None:
            return self._render_one(text, width)
        plain = _plain(frame)
        left = cell_len(plain[: plain.index(_BORDER) + 1])
        right = cell_len(plain[: plain.rindex(_BORDER)])
        prefix, _, suffix = Segment.divide(frame, [left, right, width])
        return [*prefix, *self._render_one(text, right - left), *suffix]

    def _render_one(self, text: Text, width: int) -> list[Segment]:
        if width <= 0:
            return []
        return self._console.render_lines(
            text, self._console.options.update_width(width), pad=True
        )[0]
