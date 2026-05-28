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


# --- session-held raw mode (enter once, restore once) -------------------------


def _patch_session(monkeypatch, calls, *, sentinel, select_ready=True):
    """Stub the termios/tty/signal/select surface ``raw_mode`` touches, recording
    each mode change into ``calls`` so a test can assert raw is entered once and
    restored once. ``tcgetattr`` returns ``sentinel`` (the saved cooked attrs)."""
    monkeypatch.setattr(
        keys.sys,
        "stdin",
        type("S", (), {"fileno": staticmethod(lambda: 0), "isatty": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(keys.termios, "tcgetattr", lambda fd: sentinel)
    monkeypatch.setattr(keys.tty, "setraw", lambda fd: calls.append(("raw", fd)))
    monkeypatch.setattr(
        keys.termios, "tcsetattr", lambda fd, when, old: calls.append(("restore", fd, old))
    )
    monkeypatch.setattr(keys.signal, "getsignal", lambda s: None)
    monkeypatch.setattr(keys.signal, "signal", lambda s, h: None)
    monkeypatch.setattr(
        keys.select, "select", lambda r, w, x, t: ([0], [], []) if select_ready else ([], [], [])
    )


def test_raw_mode_enters_raw_once_and_restores_once(monkeypatch):
    calls: list = []
    sentinel = object()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with keys.raw_mode():
        assert calls == [("raw", 0)]  # raw entered, not yet restored
    assert calls == [("raw", 0), ("restore", 0, sentinel)]  # restored once, with the saved attrs


def test_read_key_while_held_does_not_toggle_terminal(monkeypatch):
    """Inside a held session ``read_key`` reads the already-raw fd — it must NOT
    re-run tcgetattr/setraw/tcsetattr per keypress (the old per-key toggle that
    let escape sequences echo between keys)."""
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=object())
    monkeypatch.setattr(keys.os, "read", lambda fd, n: b"a")
    with keys.raw_mode():
        calls.clear()  # ignore the one-time entry toggle
        assert keys.read_key() == "a"
        assert calls == []  # no mode change during the read


def test_raw_mode_restores_on_exception(monkeypatch):
    calls: list = []
    sentinel = object()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with pytest.raises(RuntimeError, match="boom"), keys.raw_mode():
        raise RuntimeError("boom")
    assert ("restore", 0, sentinel) in calls  # restored despite the exception


def test_cooked_mode_restores_cooked_then_reenters_raw(monkeypatch):
    """The escape hatch for a line read mid-session: drop to cooked, then re-arm raw."""
    calls: list = []
    sentinel = object()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with keys.raw_mode():
        calls.clear()
        with keys.cooked_mode():
            assert calls == [("restore", 0, sentinel)]  # dropped to cooked
        assert calls == [("restore", 0, sentinel), ("raw", 0)]  # re-entered raw


def test_cooked_mode_is_a_noop_with_no_session(monkeypatch):
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=object())
    with keys.cooked_mode():
        pass
    assert calls == []  # nothing toggled — the terminal is already cooked


def test_pending_is_false_with_no_session():
    """Coalescing is inert outside a held session, so the loop reads one key per
    frame (every test / non-interactive path is unchanged)."""
    assert keys.pending() is False


def test_pending_reflects_select_when_held(monkeypatch):
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=object(), select_ready=True)
    with keys.raw_mode():
        assert keys.pending() is True
    assert keys.pending() is False  # back to inert once the session ends


def test_pending_false_when_select_not_ready(monkeypatch):
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=object(), select_ready=False)
    with keys.raw_mode():
        assert keys.pending() is False
