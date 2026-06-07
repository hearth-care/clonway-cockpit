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


# --- Task 5: gate-safety (the safety test) -------------------------------------


def test_gate_safety_no_post_over_stdio():
    from rich.console import Console

    from clonway_cockpit.registry import BlastRadius, WizardContext
    from clonway_cockpit.walk import confirm_apply

    class _MockXero:
        def __init__(self) -> None:
            self.posts = 0

        def post_batch(self) -> None:
            self.posts += 1

    client = _MockXero()

    def handler(ctx) -> None:
        if confirm_apply(ctx, equivalent_cli="xbook bills"):
            ctx.client.post_batch()  # only reached if the gate confirms

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

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="xbook bills",
            run=handler,
            blast_radius=BlastRadius(summary="posts a batch"),
        )
    )
    state = CockpitState(tenant_name="Clonway")
    # Open shelf C (single spec → handler), press the apply key "a", then quit.
    frames = _drive(
        _host(state, build_walk_ctx=build_ctx), [{"key": "c"}, {"key": "a"}, {"key": "q"}]
    )
    clear_capabilities()
    assert client.posts == 0, "walk posted to Xero despite agent dry-run gate"
    # the decline is observable on the wire (not just via the in-process mock)
    assert any(
        f.get("kind") == "walk.gate" and f["meta"]["status"] == "declined" for f in frames
    ), [f.get("kind") for f in frames]


# --- Audit fixes: regression tests --------------------------------------------


def test_doctor_unconfigured_over_stdio_does_not_corrupt_the_channel():
    """Audit #1: model_unstructured must not print its Rich panel to the real stdout
    (the agent's JSON channel). Capture real stdout and assert nothing leaked."""
    import contextlib

    from clonway_cockpit.doctor import Probe  # noqa: F401  (kept for parity with doctor path)

    def boom():
        raise RuntimeError("not configured")

    clear_capabilities()
    register_capability(
        CapabilitySpec(key="doctor", shelf="G", title="Doctor", summary="h", equivalent_cli="x")
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_report=boom,
        doctor_unconfigured_renderable=lambda: render.render_note("Setup", "run init"),
    )
    inp = io.StringIO(
        "".join(json.dumps(m) + "\n" for m in [{"key": "g"}, {"key": "x"}, {"key": "q"}])
    )
    out = io.StringIO()
    real = io.StringIO()
    with contextlib.redirect_stdout(real):
        serve_stdio(host, stdin=inp, stdout=out)
    clear_capabilities()
    assert real.getvalue() == "", f"leaked to real stdout: {real.getvalue()[:200]!r}"
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("kind") == "unstructured" for f in frames)


def test_shellout_capability_surfaces_as_note_not_crash():
    """Audit #2: a ShellOut from a capability must surface as a note frame, not crash."""
    from clonway_cockpit import shellout
    from clonway_cockpit.registry import WizardContext

    def shell_out_run(ctx) -> None:
        raise shellout.ShellOut("ls -la")

    def build_ctx(screen, read_key, *, focus=None):
        from rich.console import Console

        return WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="so",
            shelf="C",
            title="Shell out",
            summary="s",
            equivalent_cli="x",
            run=shell_out_run,
        )
    )
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state, build_walk_ctx=build_ctx), [{"key": "c"}])  # open → ShellOut
    clear_capabilities()
    assert any(f.get("kind") == "note" and f.get("meta", {}).get("shellout") for f in frames), [
        f.get("kind") for f in frames
    ]


def test_deeply_nested_json_does_not_crash():
    """Audit #3: deeply-nested JSON (RecursionError) degrades to an error, not a crash.
    Nested objects at depth 120k (~720KB, under the 1MB line cap) reliably exceed the
    JSON parser's recursion limit on CPython."""
    state = CockpitState(tenant_name="Clonway")
    deep = '{"a":' * 120_000 + "1" + "}" * 120_000
    inp = io.StringIO(deep + "\n" + json.dumps({"key": "q"}) + "\n")
    out = io.StringIO()
    serve_stdio(_host(state), stdin=inp, stdout=out)
    frames = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert any(f.get("error") == "invalid json" for f in frames)
    assert any(f.get("kind") == "home" for f in frames)


def test_non_string_key_rejected():
    """Audit #5: a non-string key is rejected, not silently coerced into a keystroke."""
    state = CockpitState(tenant_name="Clonway")
    frames = _drive(_host(state), [{"key": 5}, {"key": "q"}])
    assert any(f.get("error") == "key must be a string" for f in frames)
    assert any(f.get("kind") == "home" for f in frames)
