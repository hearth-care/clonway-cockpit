"""M4 apply-authorization handshake — the opt-in, token-gated guarded apply.

Default agent mode stays pure dry-run (never posts). With guarded apply enabled, a
walk posts ONLY when an explicit {"apply":true,"token":<emitted token>} is echoed back;
any other input (wrong/missing token, a plain key, EOF) declines. Exercised end-to-end
over serve_stdio against a mock posting walk. Tokens are a deterministic monotonic nonce
(``gate-<n>``); ``walk._reset_gate_seq()`` makes the first gate of a drive ``gate-1`` so
a preloaded-stdin test can echo it without a mid-stream read.
"""

from __future__ import annotations

import io
import json

from rich.console import Console

from clonway_cockpit import render, shell, usage, walk
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


def _host(state, client):
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
        if walk.confirm_apply(ctx, equivalent_cli="xbook bills schedule"):
            client.post()

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="xbook bills schedule",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
        )
    )
    return shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=build_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )


def _drive(host, messages, *, allow_apply=False):
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out, allow_apply=allow_apply)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _gate(frames, value, key="status"):
    return [
        f for f in frames if f.get("kind") == "walk.gate" and f.get("meta", {}).get(key) == value
    ]


def test_default_dry_run_never_posts_even_with_apply_message():
    client = _MockClient()
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(
        _host(state, client),
        [{"key": "c"}, {"apply": True, "token": "gate-1"}, {"key": "q"}],
        allow_apply=False,  # opt-in OFF → pure dry-run
    )
    clear_capabilities()
    assert client.posts == 0
    assert _gate(frames, "declined")
    assert not _gate(frames, "awaiting_apply", key="gate")  # no handshake offered


def test_guarded_apply_with_correct_token_posts_once():
    client = _MockClient()
    walk._reset_gate_seq()  # first gate of this drive → token "gate-1"
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(
        _host(state, client),
        [{"key": "c"}, {"apply": True, "token": "gate-1"}, {"key": "q"}],
        allow_apply=True,
    )
    clear_capabilities()
    assert client.posts == 1, [f["meta"] for f in frames if f.get("kind") == "walk.gate"]
    assert _gate(frames, "awaiting_apply", key="gate")
    assert _gate(frames, "applied")


def test_guarded_apply_wrong_token_declines():
    client = _MockClient()
    walk._reset_gate_seq()
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(
        _host(state, client),
        [{"key": "c"}, {"apply": True, "token": "wrong"}, {"key": "q"}],
        allow_apply=True,
    )
    clear_capabilities()
    assert client.posts == 0
    assert _gate(frames, "declined")


def test_guarded_apply_non_apply_message_declines():
    client = _MockClient()
    walk._reset_gate_seq()
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(
        _host(state, client),
        [{"key": "c"}, {"key": "n"}, {"key": "q"}],
        allow_apply=True,
    )
    clear_capabilities()
    assert client.posts == 0
    assert _gate(frames, "declined")


def test_human_confirm_apply_still_posts_on_apply_key():
    ctx = WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        read_key=lambda: "a",
    )
    assert walk.confirm_apply(ctx, equivalent_cli="x") is True
