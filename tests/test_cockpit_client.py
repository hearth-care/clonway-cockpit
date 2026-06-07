"""CockpitClient — the framework-owned driving peer of serve_stdio.

Drives a real ``serve_stdio`` over an in-process ``os.pipe`` pair (no subprocess), so the
client/server wire protocol — home frame, snapshot, the guarded-apply handshake — is pinned
without spawning a child. A real-subprocess integration test is Phase 4's job.
"""

from __future__ import annotations

import os
import threading

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
