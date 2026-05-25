"""Tests for the raw single-keypress reader. ``read_key`` puts the terminal in
raw mode and reads from stdin, so the byte source + termios/tty/select calls are
monkeypatched to drive it deterministically (the scripted-reader behaviour)."""

from __future__ import annotations

import pytest

from clonway_cockpit import keys


def _patch_terminal(monkeypatch, byte_chunks, *, select_ready=True):
    """Stub the termios/tty/select/os surface ``read_key`` touches so a scripted
    sequence of byte chunks drives one call. ``byte_chunks`` is the queue of
    ``bytes`` that successive ``os.read`` calls return."""
    chunks = list(byte_chunks)

    monkeypatch.setattr(keys.sys, "stdin", type("S", (), {"fileno": staticmethod(lambda: 0)})())
    monkeypatch.setattr(keys.termios, "tcgetattr", lambda fd: object())
    monkeypatch.setattr(keys.termios, "tcsetattr", lambda fd, when, old: None)
    monkeypatch.setattr(keys.tty, "setraw", lambda fd: None)
    monkeypatch.setattr(keys.os, "read", lambda fd, n: chunks.pop(0))
    monkeypatch.setattr(
        keys.select, "select", lambda r, w, x, t: ([0], [], []) if select_ready else ([], [], [])
    )


@pytest.mark.parametrize(
    "byte_chunks,expected",
    [
        ([b"a"], "a"),
        ([b"1"], "1"),
        ([b"/"], "/"),
        ([b"\r"], keys.ENTER),
        ([b"\n"], keys.ENTER),
        ([b"\x7f"], keys.BACKSPACE),
    ],
)
def test_read_key_plain_and_control_chars(monkeypatch, byte_chunks, expected):
    _patch_terminal(monkeypatch, byte_chunks)
    assert keys.read_key() == expected


@pytest.mark.parametrize(
    "seq,expected",
    [
        (b"[A", keys.UP),
        (b"[B", keys.DOWN),
        (b"[C", keys.RIGHT),
        (b"[D", keys.LEFT),
    ],
)
def test_read_key_arrow_sequences(monkeypatch, seq, expected):
    # Esc byte first, then select reports ready, then the 2-byte CSI tail.
    _patch_terminal(monkeypatch, [b"\x1b", seq], select_ready=True)
    assert keys.read_key() == expected


def test_read_key_lone_esc_when_no_followup(monkeypatch):
    _patch_terminal(monkeypatch, [b"\x1b"], select_ready=False)
    assert keys.read_key() == keys.ESC


def test_read_key_ctrl_c_raises_keyboard_interrupt(monkeypatch):
    _patch_terminal(monkeypatch, [b"\x03"])
    with pytest.raises(KeyboardInterrupt):
        keys.read_key()
