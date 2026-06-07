"""CockpitClient — the framework-owned driving peer of serve_stdio.

Drives a real ``serve_stdio`` over an in-process ``os.pipe`` pair (no subprocess), so the
client/server wire protocol — home frame, snapshot, the guarded-apply handshake — is pinned
without spawning a child. A real-subprocess integration test is Phase 4's job.
"""

from __future__ import annotations

import io
import os
import threading
import time

import pytest
from rich.console import Console

from clonway_cockpit import agent, render, shell, usage, walk
from clonway_cockpit.registry import (
    BlastRadius,
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState


def _pipe_text():
    r, w = os.pipe()
    return os.fdopen(r, "r"), os.fdopen(w, "w", buffering=1)


def _serve(host, stdin, stdout, *, allow_apply=False):
    def run():
        agent.serve_stdio(host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)
        stdout.close()  # EOF the client reader on quit

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _wire(host, *, allow_apply=False):
    """Spin up serve_stdio over a pipe pair, return (client, server_thread)."""
    to_app_r, to_app_w = _pipe_text()
    to_agent_r, to_agent_w = _pipe_text()
    t = _serve(host, to_app_r, to_agent_w, allow_apply=allow_apply)
    client = agent.CockpitClient.over_streams(stdin=to_agent_r, stdout=to_app_w)
    return client, t


def test_client_reads_home_and_snapshots(make_stub_host):
    client, t = _wire(make_stub_host())
    home = client.read_home()
    assert home["kind"] == "home"
    assert home["schema_version"] == "1.0"  # the versioned wire contract
    snap = client.snapshot()
    assert snap["kind"] == "home"
    client.quit()
    t.join(timeout=5)
    assert not t.is_alive()


# --- guarded-apply handshake ------------------------------------------------


class _MockClient:
    def __init__(self) -> None:
        self.posts = 0

    def post(self) -> None:
        self.posts += 1


def _posting_host(mock):
    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=mock,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    def handler(ctx) -> None:
        if walk.confirm_apply(ctx, equivalent_cli="x post"):
            mock.post()

    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="x post",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
        )
    )
    return shell.Host(
        capture_state=lambda: CockpitState(tenant_name="Clonway"),
        build_walk_ctx=build_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )


def test_apply_approve_posts_once():
    clear_capabilities()
    mock = _MockClient()
    try:
        client, t = _wire(_posting_host(mock), allow_apply=True)
        client.read_home()
        gate = client.press("c")  # open shelf C → walk → awaiting_apply gate
        assert gate["kind"] == "walk.gate"
        assert gate["meta"]["gate"] == "awaiting_apply"
        applied = client.apply(gate["meta"]["token"], approve=lambda proposal: True)
        assert applied["meta"]["status"] == "applied"
        assert mock.posts == 1
        client.quit()
        t.join(timeout=5)
    finally:
        clear_capabilities()


def test_quit_escalates_terminate_then_kill_for_a_stuck_child():
    """FBA hardening: a child that ignores quit/EOF must not be orphaned — quit() escalates
    terminate → kill. Uses a fake proc so the test is fast and asserts the escalation path."""
    import subprocess

    class _StuckProc:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False

        def wait(self, timeout=None):  # noqa: ANN001
            if not self.killed:
                raise subprocess.TimeoutExpired("stuck", timeout)  # ignores quit + terminate
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def poll(self):
            return 0 if self.killed else None

    proc = _StuckProc()
    client = agent.CockpitClient(stdin=io.StringIO(""), stdout=io.StringIO(), proc=proc)
    client.quit()
    assert proc.terminated is True
    assert proc.killed is True  # escalated all the way — never orphaned


def test_apply_decline_zero_posts():
    clear_capabilities()
    mock = _MockClient()
    try:
        client, t = _wire(_posting_host(mock), allow_apply=True)
        client.read_home()
        gate = client.press("c")
        assert gate["meta"]["gate"] == "awaiting_apply"
        declined = client.apply(gate["meta"]["token"], approve=lambda proposal: False)
        assert declined["meta"]["status"] == "declined"
        assert mock.posts == 0
        client.quit()
        t.join(timeout=5)
    finally:
        clear_capabilities()


# --- FBA round-2 hardening: robustness of the driving client --------------


def test_send_broken_pipe_raises_cockpit_closed():
    """A broken peer (worker exited) surfaces as CockpitClosed on send, not a raw
    BrokenPipeError the caller (drive_argv) doesn't catch."""

    class _BrokenOut:
        def write(self, _s: str) -> int:
            raise BrokenPipeError("peer gone")

        def flush(self) -> None:
            pass

    client = agent.CockpitClient(stdin=io.StringIO(""), stdout=_BrokenOut())
    with pytest.raises(agent.CockpitClosed):
        client.press("x")


def test_drain_preserves_eof_sentinel():
    """drain() that swallows EOF must re-enqueue the sentinel, so the NEXT read reports a
    clean close immediately instead of stalling for the full timeout."""
    client = agent.CockpitClient(stdin=io.StringIO(""), stdout=io.StringIO())
    client.drain(idle=0.3)  # consumes frames; hits EOF and re-enqueues it
    with pytest.raises(agent.CockpitClosed, match="stream closed"):
        client._next(timeout=0.3)  # sees the preserved _EOF → "closed", not "timed out"


def test_custom_timeout_is_honored():
    """A configured timeout is used (not the 30s default) — a worker that never emits trips a
    close promptly rather than hanging."""
    r, w = os.pipe()
    rf, wf = os.fdopen(r, "r"), os.fdopen(w, "w")  # wf stays open → reader blocks, no EOF
    try:
        client = agent.CockpitClient(stdin=rf, stdout=io.StringIO(), timeout=0.3)
        t0 = time.monotonic()
        with pytest.raises(agent.CockpitClosed, match="timed out"):
            client.read_home()
        assert time.monotonic() - t0 < 5  # honored 0.3s, not the 30s default
    finally:
        wf.close()
        rf.close()
