"""Terminal-mode hardening, driven against a REAL pseudo-terminal.

Three defects surfaced while a worker built its first walk that asks for typed answers:

* ``keys.raw_mode`` entered twice saved the already-raw terminal as the "cooked" state, so
  an inner ``cooked_mode`` could never restore echo and the first exit left the session
  half-released.
* ``prompts.make_clean_input_fn`` did not open a cooked window itself, so a typed prompt
  read in raw mode and every worker had to remember to wrap it.
* ``walk.confirm_apply`` read the gate key without discarding keys buffered earlier, so a
  keypress made before the review page was drawn could confirm a write.

A stubbed termios cannot show any of these (they are about what the kernel's line
discipline is doing), so each test opens a pty and reads the real flags back.
"""

from __future__ import annotations

import os
import pty
import termios
from collections.abc import Iterator

import pytest
from rich.console import Console

from clonway_cockpit import keys, prompts, walk
from clonway_cockpit.registry import WizardContext


@pytest.fixture
def pty_pair(monkeypatch) -> Iterator[tuple[int, int]]:
    """A pty whose slave end stands in for the cockpit's stdin (cooked, echoing)."""
    master, slave = pty.openpty()
    monkeypatch.setattr(
        keys.sys,
        "stdin",
        type(
            "S", (), {"isatty": staticmethod(lambda: True), "fileno": staticmethod(lambda: slave)}
        )(),
    )
    try:
        yield master, slave
    finally:
        os.close(master)
        os.close(slave)


def _is_cooked(fd: int) -> bool:
    lflag = termios.tcgetattr(fd)[3]
    return bool(lflag & termios.ICANON) and bool(lflag & termios.ECHO)


def _is_raw(fd: int) -> bool:
    lflag = termios.tcgetattr(fd)[3]
    return not (lflag & termios.ICANON) and not (lflag & termios.ECHO)


# --- 1. raw_mode is safe to enter twice --------------------------------------


def test_nested_raw_mode_keeps_the_outer_session_and_its_cooked_baseline(pty_pair):
    _master, slave = pty_pair
    assert _is_cooked(slave)

    with keys.raw_mode():
        assert _is_raw(slave)
        with keys.raw_mode():
            assert keys._session_fd() == slave
            # The inner entry must not have recorded the raw terminal as "cooked": a
            # cooked window opened now has to give the operator echo and line editing.
            with keys.cooked_mode():
                assert _is_cooked(slave)
            assert _is_raw(slave)
        # Leaving the inner block releases nothing: the outer session is still held.
        assert keys._session_fd() == slave
        assert _is_raw(slave)

    assert keys._session_fd() is None
    assert _is_cooked(slave)


def test_nested_raw_mode_is_a_noop_when_stdin_is_not_a_tty(monkeypatch):
    monkeypatch.setattr(
        keys.sys,
        "stdin",
        type("S", (), {"isatty": staticmethod(lambda: False)})(),
    )
    with keys.raw_mode(), keys.raw_mode():
        assert keys._session_fd() is None


# --- cooked_mode nests harmlessly --------------------------------------------


def test_nested_cooked_mode_stays_cooked_until_the_outermost_exits(pty_pair):
    _master, slave = pty_pair
    with keys.raw_mode():
        with keys.cooked_mode():
            with keys.cooked_mode():
                assert _is_cooked(slave)
            # The inner window closing must not re-arm raw under the outer one, which
            # may still have more typed prompts to read.
            assert _is_cooked(slave)
        assert _is_raw(slave)
    assert _is_cooked(slave)


# --- 2. make_clean_input_fn opens its own cooked window ----------------------


def _record_prompt_mode(monkeypatch, fd: int, answer: str) -> list[bool]:
    """Replace ``typer.prompt`` with a recorder that notes whether the terminal was
    cooked at the moment the prompt ran, then returns ``answer``."""
    import typer

    seen: list[bool] = []

    def fake_prompt(text, default="", **_kw):
        seen.append(_is_cooked(fd))
        return answer

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    return seen


def test_clean_input_fn_reads_in_cooked_mode_and_re_arms_raw(pty_pair, monkeypatch):
    _master, slave = pty_pair
    seen = _record_prompt_mode(monkeypatch, slave, "42 Acacia Road")
    ask = prompts.make_clean_input_fn()

    with keys.raw_mode():
        assert ask("▸ ", "") == "42 Acacia Road"
        assert _is_raw(slave)

    assert seen == [True], "the typed prompt ran while the terminal was still raw"


def test_clean_input_fn_still_works_when_the_worker_wraps_it_in_cooked_mode(pty_pair, monkeypatch):
    # Existing workers (auto-admissions) wrap the factory's fn in cooked_mode themselves.
    _master, slave = pty_pair
    seen = _record_prompt_mode(monkeypatch, slave, "typed")
    ask = prompts.make_clean_input_fn()

    with keys.raw_mode():
        with keys.cooked_mode():
            assert ask("▸ ", "") == "typed"
            assert _is_cooked(slave)
        assert _is_raw(slave)

    assert seen == [True]


def test_clean_input_fn_outside_a_session_just_prompts(monkeypatch):
    import typer

    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "plain")
    assert keys._session_fd() is None
    assert prompts.make_clean_input_fn()("▸ ", "") == "plain"


# --- 3. confirm_apply discards keys typed before the gate --------------------


def _human_ctx(read_key, *, dry_run: bool = False) -> WizardContext:
    return WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        read_key=read_key,
        dry_run=dry_run,
    )


def test_a_key_buffered_before_the_gate_cannot_confirm_the_write(pty_pair):
    master, slave = pty_pair

    def operator_declines() -> str:
        os.write(master, b"n")  # the deliberate answer, given once the gate is on screen
        return keys.read_key()

    with keys.raw_mode():
        # Written inside the session: a cooked pty echoes input back to its master,
        # which nothing reads here, and macOS then blocks the next mode change.
        os.write(master, b"a")  # pressed while the review page was still being drawn
        assert walk.confirm_apply(_human_ctx(operator_declines), equivalent_cli="x") is False


def test_the_deliberate_key_after_the_drain_is_honoured(pty_pair):
    master, slave = pty_pair

    def operator_applies() -> str:
        os.write(master, b"a")
        return keys.read_key()

    with keys.raw_mode():
        os.write(master, b"nnn")  # stray typeahead, all of it discarded
        assert walk.confirm_apply(_human_ctx(operator_applies), equivalent_cli="x") is True


def test_drain_does_nothing_without_a_held_session(monkeypatch):
    monkeypatch.setattr(keys, "_held_fd", None)

    def no_flush(*_a, **_k):
        raise AssertionError("tcflush called with no raw session held")

    monkeypatch.setattr(keys.termios, "tcflush", no_flush)
    assert walk.confirm_apply(_human_ctx(lambda: "a"), equivalent_cli="x") is True


def test_drain_failure_never_blocks_the_gate(monkeypatch):
    # A stale fd (terminal gone) makes tcflush raise; the gate must still read its key.
    monkeypatch.setattr(keys, "_held_fd", 987654)
    assert walk.confirm_apply(_human_ctx(lambda: "a"), equivalent_cli="x") is True
    assert walk.confirm_apply(_human_ctx(lambda: "n"), equivalent_cli="x") is False


def test_dry_run_gate_leaves_the_terminal_queue_alone(pty_pair):
    master, slave = pty_pair
    ctx = _human_ctx(lambda: "a", dry_run=True)
    with keys.raw_mode():
        os.write(master, b"a")
        assert walk.confirm_apply(ctx, equivalent_cli="x") is False
        assert keys.pending(0.2), "agent mode must not touch the human terminal queue"
