"""Raw single-keypress reader for the cockpit — arrow keys, Enter, Esc and plain
characters — via stdlib ``termios``/``tty`` (no dependency). POSIX only; the
cockpit is interactive-only, and the non-interactive paths (pipes, Cloud Run)
never reach here.

The session holds the terminal in raw (no-echo) mode for its whole lifetime via
``raw_mode()`` — entered once, restored once (on normal exit, on exception, and
on SIGTERM). ``read_key`` then reads straight from the already-raw fd, so a slow
redraw between keys can no longer leave the terminal in cooked+echo mode where
the kernel echoes arrow-key escape sequences (``^[[A``) to the screen. A line
read that genuinely needs cooked mode (a typed prompt) opens a ``cooked_mode()``
window. Outside a held session ``read_key`` falls back to the legacy per-keypress
toggle, so direct callers and the test harness are unchanged."""

from __future__ import annotations

import os
import select
import signal
import sys
import termios
import tty
from contextlib import contextmanager, suppress
from typing import Any

UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
ENTER = "enter"
ESC = "esc"
BACKSPACE = "backspace"

_ARROWS = {"[A": UP, "[B": DOWN, "[C": RIGHT, "[D": LEFT}

# The fd + saved cooked attrs while a ``raw_mode()`` session is active; both None
# otherwise. This is what lets ``read_key`` skip the per-keypress mode toggle and
# ``pending`` know there is a raw fd to poll. ``_held_old`` is a ``termios`` attr
# list (``tcgetattr``'s return), typed for ``tcsetattr`` to accept it back.
_held_fd: int | None = None
_held_old: list[Any] | None = None


def _session_fd() -> int | None:
    """The fd of the active raw-mode session, or ``None`` when none is held."""
    return _held_fd


@contextmanager
def raw_mode():
    """Hold the terminal in raw/no-echo mode for the whole cockpit session.

    Entered once at the top of the interactive loop and restored exactly once —
    on normal exit, on any exception (``finally``), and on SIGTERM (a handler that
    restores then re-raises the default disposition, so ``kill`` can't leave the
    terminal wedged). While held, ``read_key`` reads the already-raw fd directly:
    no tcgetattr/setraw/tcsetattr per keypress, so escape sequences never echo
    between keys. Idempotent against nesting is not needed — the cockpit enters it
    exactly once per session."""
    global _held_fd, _held_old
    if not sys.stdin.isatty():
        # Non-interactive stdin (a pipe, pytest's captured stdin, Cloud Run): there
        # is no terminal to put in raw mode. Yield untouched so read_key's standalone
        # path / an injected reader still works and pending() stays inert.
        yield
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _restore() -> None:
        # TCSAFLUSH (not TCSADRAIN): apply immediately AND discard any unread input,
        # so a half-typed escape sequence captured under raw mode isn't reinterpreted
        # by the shell once the terminal is cooked again.
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)

    def _on_sigterm(_signum: int, _frame: object) -> None:
        _restore()
        signal.signal(signal.SIGTERM, prev_sigterm)
        os.kill(os.getpid(), signal.SIGTERM)  # re-raise with the original disposition

    try:
        tty.setraw(fd)
        _held_fd, _held_old = fd, old
        # Not the main thread → signal handlers can't be installed; the finally still
        # restores via the context manager, so this is best-effort.
        with suppress(ValueError):
            signal.signal(signal.SIGTERM, _on_sigterm)
        yield
    finally:
        _held_fd, _held_old = None, None
        with suppress(ValueError, TypeError):
            signal.signal(signal.SIGTERM, prev_sigterm)
        _restore()


@contextmanager
def cooked_mode():
    """Temporarily restore the pre-raw (cooked, echoing) terminal for a line read
    inside a held session, then re-arm raw mode. A no-op when no session is held
    (the terminal is already cooked). Wrap any ``input_fn``-style typed prompt a
    walk runs in this so the keystrokes echo and line-edit normally."""
    fd = _session_fd()
    if fd is None:
        yield  # no session → already cooked, nothing to toggle
        return
    assert _held_old is not None  # a held session always has saved cooked attrs
    termios.tcsetattr(fd, termios.TCSAFLUSH, _held_old)
    try:
        yield
    finally:
        tty.setraw(fd)


def pending(timeout: float = 0.0) -> bool:
    """True if a keypress is immediately available on stdin — the input-coalescing
    primitive that lets the loop drain a burst of held-arrow key-repeat and repaint
    once instead of once per byte. Only meaningful inside a held session; returns
    ``False`` otherwise, so every non-interactive / test path reads one key per
    frame and is unchanged."""
    fd = _session_fd()
    if fd is None:
        return False
    ready, _, _ = select.select([fd], [], [], timeout)
    return bool(ready)


def _read_token(fd: int) -> str:
    """Read one semantic key from a fd that is already in raw mode."""
    ch = os.read(fd, 1).decode(errors="ignore")
    if ch == "\x03":  # Ctrl-C
        raise KeyboardInterrupt
    if ch in ("\r", "\n"):
        return ENTER
    if ch == "\x7f":
        return BACKSPACE
    if ch == "\x1b":
        # Esc alone, or the start of a CSI arrow sequence (Esc [ A/B/C/D).
        # A short select() distinguishes a lone Esc from an arrow without
        # blocking forever on the follow-up bytes.
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return ESC
        seq = os.read(fd, 2).decode(errors="ignore")
        return _ARROWS.get(seq, ESC)
    return ch


def read_key() -> str:
    """Block for one keypress and return a semantic token: ``up``/``down``/
    ``left``/``right``/``enter``/``esc``/``backspace`` or the literal character
    (``"a"``, ``"1"``, ``"/"``…). Ctrl-C raises ``KeyboardInterrupt``.

    Inside a ``raw_mode()`` session the fd is already raw, so this just reads it.
    Standalone (no session held) it toggles raw for exactly one keypress and
    restores with TCSANOW — the legacy path direct callers and tests still use."""
    fd = _session_fd()
    if fd is not None:
        return _read_token(fd)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return _read_token(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)
