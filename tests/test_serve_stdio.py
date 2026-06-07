"""The subprocess stdio JSON protocol (M2): agent.serve_stdio drives the real cockpit
over line-delimited JSON. Tested in-process with io pipes (serve_stdio takes a Python
host; an OS subprocess spawn is a consumer concern)."""

from __future__ import annotations

import io
import json

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.registry import (
    CapabilitySpec,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, Pill


def _host(state: CockpitState, **over) -> shell.Host:
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


def _drive(host: shell.Host, messages: list[dict]) -> list[dict]:
    """Feed JSON messages on stdin, return the parsed JSON frames written to stdout."""
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_serve_stdio_emits_home_then_quits():
    state = CockpitState(
        tenant_name="Clonway", pills=(Pill("Xero", "synced", "06:45", "ok", "xero"),)
    )
    frames = _drive(_host(state), [{"key": "q"}])
    assert frames, "no frames emitted"
    assert frames[0]["kind"] == "home"


def test_serve_stdio_drives_into_a_shelf_menu():
    clear_capabilities()
    register_capability(
        CapabilitySpec(key="a1", shelf="C", title="Cap one", summary="s", equivalent_cli="x")
    )
    register_capability(
        CapabilitySpec(key="a2", shelf="C", title="Cap two", summary="s", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    # Shelf C has two specs → a shelf_menu; open C, then quit out.
    frames = _drive(_host(state), [{"key": "c"}, {"key": "q"}, {"key": "q"}])
    clear_capabilities()
    kinds = [f["kind"] for f in frames]
    assert "home" in kinds and "shelf_menu" in kinds, kinds
