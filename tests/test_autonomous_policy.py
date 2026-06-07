"""WS-B — the autonomous AllowlistPolicy at the write gate, driven over the real shell.

Proves the full threading: shell._open_capability tags the gate with the capability's key +
money_movement class; walk.confirm_apply hands that proposal to the injected policy;
serve_stdio(policy=...) auto-decides WITHOUT a human round-trip and fires on_apply (audit).
"""

from __future__ import annotations

import io
import json

from rich.console import Console

from clonway_cockpit import approval, render, shell, usage, walk
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.registry import (
    BlastRadius,
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState


class _MockClient:
    def __init__(self) -> None:
        self.posts = 0

    def post(self) -> None:
        self.posts += 1


def _host(client, *, money_movement=False):  # noqa: ANN001
    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=client,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    def handler(ctx) -> None:
        if walk.confirm_apply(ctx, equivalent_cli="x post"):
            client.post()

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="x post",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
            money_movement=money_movement,
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


def _drive(host, messages, *, policy=None, on_apply=None):  # noqa: ANN001
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out, policy=policy, on_apply=on_apply)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _gate(frames, status):
    return [
        f
        for f in frames
        if f.get("kind") == "walk.gate" and f.get("meta", {}).get("status") == status
    ]


def test_allowlisted_reversible_capability_auto_posts_and_audits():
    client = _MockClient()
    audited: list = []
    frames = _drive(
        _host(client),
        [{"key": "c"}, {"key": "q"}],  # NO apply message — the policy decides, no human round-trip
        policy=approval.AllowlistPolicy({"sb"}),
        on_apply=audited.append,
    )
    clear_capabilities()
    assert client.posts == 1  # auto-approved without a human
    assert _gate(frames, "applied")
    assert audited and audited[0]["capability_key"] == "sb"  # the apply was audited


def test_capability_not_in_allowlist_is_declined():
    client = _MockClient()
    frames = _drive(
        _host(client), [{"key": "c"}, {"key": "q"}], policy=approval.AllowlistPolicy(set())
    )
    clear_capabilities()
    assert client.posts == 0
    assert _gate(frames, "declined")


def test_money_movement_capability_refused_even_if_allowlisted():
    client = _MockClient()
    frames = _drive(
        _host(client, money_movement=True),
        [{"key": "c"}, {"key": "q"}],
        policy=approval.AllowlistPolicy({"sb"}),  # allowlisted by key — but it moves money
    )
    clear_capabilities()
    assert client.posts == 0  # the structural money-direction exclusion wins
    assert _gate(frames, "declined")
