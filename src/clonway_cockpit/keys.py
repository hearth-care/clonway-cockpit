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

import contextlib
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
PGUP = "pgup"
PGDN = "pgdn"
HOME = "home"
END = "end"

# Complete escape sequences (the bytes after ESC) mapped to semantic keys. Terminals
# disagree on Home/End (xterm sends ``[H``/``[F`` or ``OH``/``OF``; the VT220 family
# and tmux send ``[1~``/``[4~`` or ``[7~``/``[8~``), so every common spelling maps.
_SEQUENCES = {
    "[A": UP,
    "[B": DOWN,
    "[C": RIGHT,
    "[D": LEFT,
    "OA": UP,
    "OB": DOWN,
    "OC": RIGHT,
    "OD": LEFT,
    "[5~": PGUP,
    "[6~": PGDN,
    "[H": HOME,
    "[1~": HOME,
    "[7~": HOME,
    "OH": HOME,
    "[F": END,
    "[4~": END,
    "[8~": END,
    "OF": END,
}
# Kept for callers that imported the old arrow-only table.
_ARROWS = {seq: key for seq, key in _SEQUENCES.items() if key in (UP, DOWN, LEFT, RIGHT)}

# A recognised-but-unmapped escape sequence (F-keys, Shift-arrows, Insert, Delete…).
# ``_read_token`` returns it so the whole sequence is consumed; ``read_key`` skips it
# rather than handing screens an ESC (which they treat as "back") plus stray bytes.
_IGNORED = "\x00ignored"
# A CSI sequence is ESC [ params… final; the longest this reader expects is a
# modified function key such as ``[15;2~``. The bound stops a malformed stream from
# swallowing ordinary keypresses.
_MAX_SEQUENCE = 8
# How long to wait for each follow-up byte of a sequence. Terminals emit a sequence
# in one write, so the bytes are normally already buffered; the wait only matters
# for a lone Esc, which must still come back promptly.
_SEQUENCE_WAIT = 0.05

# The fd + saved cooked attrs while a ``raw_mode()`` session is active; both None
# otherwise. This is what lets ``read_key`` skip the per-keypress mode toggle and
# ``pending`` know there is a raw fd to poll. ``_held_old`` is a ``termios`` attr
# list (``tcgetattr``'s return), typed for ``tcsetattr`` to accept it back.
_held_fd: int | None = None
_held_old: list[Any] | None = None


def _session_fd() -> int | None:
    """The fd of the active raw-mode session, or ``None`` when none is held."""
    return _held_fd


def _enter_raw(fd: int) -> None:
    """Put ``fd`` in raw INPUT mode but keep OUTPUT post-processing (OPOST) ON.

    ``tty.setraw`` clears OPOST — *all* output post-processing, including the
    ONLCR ``\\n`` -> ``\\r\\n`` translation. Rich renders each frame as full-width
    lines joined by bare ``\\n`` and relies on the terminal to add the carriage
    return; with OPOST off every line drops a row without returning to column 0,
    so the frame staircases/wraps and the alt-screen decays to garble (the
    cockpit's "double-spaced then black"). So we re-enable OPOST after setraw: raw
    INPUT (no echo, no canonical, ISIG off so read_key's ``\\x03`` handling stands)
    but cooked OUTPUT. Used on initial ``raw_mode`` entry and whenever
    ``cooked_mode`` re-arms raw after a typed prompt."""
    tty.setraw(fd)
    mode = termios.tcgetattr(fd)
    mode[tty.OFLAG] |= termios.OPOST
    termios.tcsetattr(fd, termios.TCSANOW, mode)


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
        _enter_raw(fd)
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
        # Re-arm raw the same way the session entered it — keeping OPOST on — so a
        # render after a typed prompt isn't garbled by a bare setraw dropping OPOST.
        _enter_raw(fd)


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


def discard_pending() -> None:
    """Drop keypresses typed while the cockpit was busy.

    Re-capturing Home can take seconds on a real tenant. Keys pressed during that
    wait were meant for a screen that looked frozen (usually a repeated ``q``); read
    later they would act on the fresh Home instead, and a stray ``q`` there quits.
    A no-op outside a held raw session (tests, pipes, agent stdio).
    """
    fd = _session_fd()
    if fd is None:
        return
    with contextlib.suppress(termios.error, OSError):
        termios.tcflush(fd, termios.TCIFLUSH)


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
        return _read_escape(fd)
    return ch


def _read_escape(fd: int) -> str:
    """Resolve what follows an ESC byte: a lone Esc, or a whole CSI (``ESC [``) /
    SS3 (``ESC O``) sequence read up to and including its final byte (0x40-0x7E).

    Reading the full sequence matters because PageUp is ``ESC [ 5 ~``: the old
    two-byte read saw ``[5``, called it Esc (which screens treat as "back") and left
    ``~`` behind as a phantom keypress. A short select() per byte keeps a lone Esc
    prompt without blocking on bytes that are not coming."""
    ready, _, _ = select.select([fd], [], [], _SEQUENCE_WAIT)
    if not ready:
        return ESC
    seq = os.read(fd, 1).decode(errors="ignore")
    if not seq.startswith(("[", "O")):
        # Esc followed by an ordinary byte (an Alt-chord): Esc, as before.
        return ESC
    while not _sequence_complete(seq) and len(seq) < _MAX_SEQUENCE:
        ready, _, _ = select.select([fd], [], [], _SEQUENCE_WAIT)
        if not ready:
            break
        seq += os.read(fd, 1).decode(errors="ignore")
    return _SEQUENCES.get(seq, _IGNORED)


def _sequence_complete(seq: str) -> bool:
    """True once ``seq`` (the bytes after ESC) holds its final byte. SS3 is always
    ``O`` plus one character; CSI ends at the first byte in 0x40-0x7E after ``[``."""
    body = seq[1:]
    if not body:
        return False
    if seq[0] == "O":
        return True
    return any(0x40 <= ord(c) <= 0x7E for c in body)


def read_key() -> str:
    """Block for one keypress and return a semantic token: ``up``/``down``/
    ``left``/``right``/``enter``/``esc``/``backspace``/``pgup``/``pgdn``/``home``/
    ``end`` or the literal character (``"a"``, ``"1"``, ``"/"``…). Other escape
    sequences (F-keys, Shift-arrows) are consumed whole and skipped. Ctrl-C raises
    ``KeyboardInterrupt``.

    Inside a ``raw_mode()`` session the fd is already raw, so this just reads it.
    Standalone (no session held) it toggles raw for exactly one keypress and
    restores with TCSANOW — the legacy path direct callers and tests still use."""
    fd = _session_fd()
    if fd is not None:
        return _next_key(fd)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return _next_key(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)


def _next_key(fd: int) -> str:
    """The next meaningful key, skipping escape sequences the cockpit has no use for."""
    while (token := _read_token(fd)) == _IGNORED:
        pass
    return token
