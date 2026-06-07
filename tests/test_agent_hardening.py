"""Agent-mode hardening: side-effect gating (no pulse sync / Doctor fix runs while an
agent drives) + the serve_stdio on_apply audit hook (worker-bound obs for applied gates).
"""

from __future__ import annotations

import io
import json

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver, serve_stdio
from clonway_cockpit.doctor import Fix, Probe
from clonway_cockpit.registry import (
    BlastRadius,
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, Pill


def _host(state, **over):
    base = dict(
        capture_state=lambda: state,
        build_walk_ctx=lambda *a, **k: None,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )
    base.update(over)
    return shell.Host(**base)


def test_agent_mode_skips_pulse_sync():
    calls: list = []
    state = CockpitState(tenant_name="Clonway", pills=(Pill("Xero", "stale", "", "warn", "xero"),))
    host = _host(state, activate_pill=lambda *a, **k: calls.append(1), agent_mode=True)
    stream = CockpitDriver(host, keys=["enter", "q"]).run()  # ⏎ on the (only) pill
    assert calls == [], "activate_pill ran in agent mode"
    assert any(m.kind == "note" and "skipped" in m.title.lower() for m in stream)


def test_human_mode_still_syncs_the_pill():
    calls: list = []
    state = CockpitState(tenant_name="Clonway", pills=(Pill("Xero", "stale", "", "warn", "xero"),))
    host = _host(state, activate_pill=lambda *a, **k: calls.append(1))  # agent_mode=False (default)
    CockpitDriver(host, keys=["enter", "q"]).run()
    assert calls == [1], "human cockpit must still sync the pill"


def test_agent_mode_skips_doctor_fix():
    ran: list = []
    fix = Fix(title="Remove lock", cmd="x", run=lambda: ran.append(1) or "done")
    probes = [Probe("Lock", "warn", "stale", fix)]
    clear_capabilities()
    register_capability(
        CapabilitySpec(key="doctor", shelf="G", title="Doctor", summary="h", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_probes=lambda rep: probes,
        doctor_fixes_for=lambda p: [fix],
        agent_mode=True,
    )
    # open shelf G (doctor) → ⏎ runs the selected fix → q exits doctor → q quits
    stream = CockpitDriver(host, keys=["g", "enter", "q", "q"]).run()
    clear_capabilities()
    assert ran == [], "Doctor fix ran in agent mode"
    assert any(m.kind == "note" and "skipped" in m.title.lower() for m in stream)


def test_on_apply_hook_fires_on_authorized_apply():
    import clonway_cockpit.walk as walk

    posts: list = []
    applied: list = []

    def handler(ctx) -> None:
        if walk.confirm_apply(ctx, equivalent_cli="xbook bills schedule"):
            posts.append(1)

    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda p, d: "",
            confirm_fn=lambda p: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="xbook bills schedule",
            run=handler,
            blast_radius=BlastRadius(summary="posts"),
        )
    )
    walk._reset_gate_seq()
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO(
        "".join(
            json.dumps(m) + "\n"
            for m in [{"key": "c"}, {"apply": True, "token": "gate-1"}, {"key": "q"}]
        )
    )
    serve_stdio(
        _host(state, build_walk_ctx=build_ctx),
        stdin=inp,
        stdout=io.StringIO(),
        allow_apply=True,
        on_apply=lambda proposal: applied.append(proposal),
    )
    clear_capabilities()
    assert posts == [1], "the authorized apply should post"
    assert applied and applied[0]["equivalent_cli"] == "xbook bills schedule"


def test_on_apply_hook_not_fired_when_declined():
    applied: list = []

    def handler(ctx) -> None:
        import clonway_cockpit.walk as walk

        walk.confirm_apply(ctx, equivalent_cli="x")

    def build_ctx(screen, read_key, *, focus=None):
        return WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda p, d: "",
            confirm_fn=lambda p: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="X",
            summary="s",
            equivalent_cli="x",
            run=handler,
            blast_radius=BlastRadius(summary="p"),
        )
    )
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO(
        "".join(
            json.dumps(m) + "\n"
            for m in [{"key": "c"}, {"apply": True, "token": "wrong"}, {"key": "q"}]
        )
    )
    serve_stdio(
        _host(state, build_walk_ctx=build_ctx),
        stdin=inp,
        stdout=io.StringIO(),
        allow_apply=True,
        on_apply=lambda proposal: applied.append(proposal),
    )
    clear_capabilities()
    assert applied == [], "on_apply must not fire on a declined/wrong-token apply"
