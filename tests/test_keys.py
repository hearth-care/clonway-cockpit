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
    restored once. ``tcgetattr`` returns a fresh copy of ``sentinel`` (the saved
    cooked attrs — a real 7-element termios list, so the OPOST re-enable can
    subscript it). ``tcsetattr`` is recorded as a teardown ``restore`` only for
    ``TCSAFLUSH``; the entry-side OPOST re-apply (``TCSANOW``) is recorded as
    ``set`` so the two stay distinguishable."""

    def _set(fd, when, attrs):
        kind = "restore" if when == keys.termios.TCSAFLUSH else "set"
        calls.append((kind, fd, attrs))

    monkeypatch.setattr(
        keys.sys,
        "stdin",
        type("S", (), {"fileno": staticmethod(lambda: 0), "isatty": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(keys.termios, "tcgetattr", lambda fd: list(sentinel))
    monkeypatch.setattr(keys.tty, "setraw", lambda fd: calls.append(("raw", fd)))
    monkeypatch.setattr(keys.termios, "tcsetattr", _set)
    monkeypatch.setattr(keys.signal, "getsignal", lambda s: None)
    monkeypatch.setattr(keys.signal, "signal", lambda s, h: None)
    monkeypatch.setattr(
        keys.select, "select", lambda r, w, x, t: ([0], [], []) if select_ready else ([], [], [])
    )


def _cooked_attrs():
    """A realistic saved-cooked termios attr list: index 1 (OFLAG) already carries
    OPOST so the round-trip is a no-op in value terms, and it is subscriptable so
    the production OPOST re-enable works against the stub."""
    return [0, keys.termios.OPOST | keys.termios.ONLCR, 0, 0, 0, 0, [b"\x00"] * 32]


def test_raw_mode_enters_raw_once_and_restores_once(monkeypatch):
    calls: list = []
    sentinel = _cooked_attrs()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with keys.raw_mode():
        # Entry sets raw and re-enables OPOST (a TCSANOW "set"); no teardown yet.
        assert ("raw", 0) in calls
        assert not any(c[0] == "restore" for c in calls)
    # Restored exactly once, with the saved cooked attrs.
    assert [c for c in calls if c[0] == "restore"] == [("restore", 0, sentinel)]


def test_read_key_while_held_does_not_toggle_terminal(monkeypatch):
    """Inside a held session ``read_key`` reads the already-raw fd — it must NOT
    re-run tcgetattr/setraw/tcsetattr per keypress (the old per-key toggle that
    let escape sequences echo between keys)."""
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=_cooked_attrs())
    monkeypatch.setattr(keys.os, "read", lambda fd, n: b"a")
    with keys.raw_mode():
        calls.clear()  # ignore the one-time entry toggle
        assert keys.read_key() == "a"
        assert calls == []  # no mode change during the read


def test_raw_mode_restores_on_exception(monkeypatch):
    calls: list = []
    sentinel = _cooked_attrs()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with pytest.raises(RuntimeError, match="boom"), keys.raw_mode():
        raise RuntimeError("boom")
    assert ("restore", 0, sentinel) in calls  # restored despite the exception


def test_cooked_mode_restores_cooked_then_reenters_raw(monkeypatch):
    """The escape hatch for a line read mid-session: drop to cooked, then re-arm raw."""
    calls: list = []
    sentinel = _cooked_attrs()
    _patch_session(monkeypatch, calls, sentinel=sentinel)
    with keys.raw_mode():
        calls.clear()
        with keys.cooked_mode():
            assert calls == [("restore", 0, sentinel)]  # dropped to cooked
        # Re-armed raw keeping OPOST on: setraw + the TCSANOW OPOST re-apply.
        assert calls == [("restore", 0, sentinel), ("raw", 0), ("set", 0, sentinel)]


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
    _patch_session(monkeypatch, calls, sentinel=_cooked_attrs(), select_ready=True)
    with keys.raw_mode():
        assert keys.pending() is True
    assert keys.pending() is False  # back to inert once the session ends


def test_pending_false_when_select_not_ready(monkeypatch):
    calls: list = []
    _patch_session(monkeypatch, calls, sentinel=_cooked_attrs(), select_ready=False)
    with keys.raw_mode():
        assert keys.pending() is False


def test_raw_mode_keeps_output_post_processing_on(monkeypatch):
    """Regression for the "double-spaced then black" cockpit: while raw mode is
    held, the terminal must keep OUTPUT post-processing (OPOST) on so Rich's bare
    ``\\n`` frame separators still translate to ``\\r\\n``. ``tty.setraw`` clears
    OPOST, which staircases/wraps every rendered line. Driven against a REAL pty
    (not the monkeypatched stubs above) because the bug is purely in the terminal
    flags — a stubbed termios can't observe it."""
    import os
    import pty
    import termios
    import tty

    master, slave = pty.openpty()
    monkeypatch.setattr(
        keys.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: True), "fileno": staticmethod(lambda: slave)})()
    )
    try:
        with keys.raw_mode():
            mode = termios.tcgetattr(slave)
            assert mode[tty.OFLAG] & termios.OPOST, "OPOST off → Rich frames lose \\n→\\r\\n and the alt-screen garbles"
            # The input side must still be raw: canonical + echo off so read_key
            # gets single keypresses with no echo.
            assert not (mode[tty.LFLAG] & termios.ICANON)
            assert not (mode[tty.LFLAG] & termios.ECHO)
    finally:
        os.close(master)
        os.close(slave)
