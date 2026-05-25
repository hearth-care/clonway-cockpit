"""Raw single-keypress reader for the cockpit — arrow keys, Enter, Esc and
plain characters — via stdlib ``termios``/``tty`` (no dependency). POSIX only;
the cockpit is interactive-only, and the non-interactive paths (pipes, Cloud
Run) never reach here. Each call puts the terminal in raw mode for exactly one
keypress and restores it, so ordinary line reads (e.g. the filter prompt) still
work between calls."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty

UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
ENTER = "enter"
ESC = "esc"
BACKSPACE = "backspace"

_ARROWS = {"[A": UP, "[B": DOWN, "[C": RIGHT, "[D": LEFT}


def read_key() -> str:
    """Block for one keypress and return a semantic token: ``up``/``down``/
    ``left``/``right``/``enter``/``esc``/``backspace`` or the literal character
    (``"a"``, ``"1"``, ``"/"``…). Ctrl-C raises ``KeyboardInterrupt``."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
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
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
