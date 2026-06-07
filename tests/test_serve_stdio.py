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


# --- Task 3: snapshot + quit ---------------------------------------------------


def test_snapshot_re_emits_current_screen_without_advancing():
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state), [{"cmd": "snapshot"}, {"key": "q"}])
    homes = [f for f in frames if f["kind"] == "home"]
    assert len(homes) >= 2, [f["kind"] for f in frames]
    assert homes[0] == homes[1]


def test_quit_command_unwinds_like_q():
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state), [{"cmd": "quit"}])
    assert frames and frames[0]["kind"] == "home"


# --- Task 4: protocol errors + EOF ---------------------------------------------


def test_bad_json_yields_error_then_recovers():
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO('not json\n{"key": "q"}\n')  # garbage line, then a real quit
    out = io.StringIO()
    serve_stdio(_host(state), stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("error") == "invalid json" for f in frames)
    assert any(f.get("kind") == "home" for f in frames)


def test_non_object_and_unknown_command_error():
    state = CockpitState(tenant_name="Clonway")
    inp = io.StringIO('[1,2,3]\n{"cmd": "frob"}\n{"key": "q"}\n')
    out = io.StringIO()
    serve_stdio(_host(state), stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("error") == "expected a JSON object" for f in frames)
    assert any("unknown message" in str(f.get("error", "")) for f in frames)


def test_eof_unwinds_without_a_quit_message():
    state = CockpitState(tenant_name="Clonway")
    out = io.StringIO()
    serve_stdio(_host(state), stdin=io.StringIO(""), stdout=out)  # empty stdin = immediate EOF
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert frames and frames[0]["kind"] == "home"
