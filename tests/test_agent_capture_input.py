"""Agent-drivable capture: a walk that PROMPTS for typed input is drivable over the stdio protocol
(input_request → input, confirm_request → confirm), not just from a human terminal — and a walk that
crashes with an empty-str exception still surfaces a non-empty error frame. Regression for the audit's
#9 (a capture walk dumped an empty ``… hit an error — `` frame and leaked the prompt to stdout because
``ctx.input_fn`` was the terminal ``typer.prompt`` even in agent mode)."""

from __future__ import annotations

import io
import json

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.registry import (
    BlastRadius,
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState
from clonway_cockpit.walk import Step, StepResult, make_walk_handler


def _drive(host: shell.Host, messages: list[dict]) -> list[dict]:
    inp = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _host_with_walk(handler) -> shell.Host:  # noqa: ANN001
    state = CockpitState(tenant_name="Clonway")
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="nj",
            shelf="C",
            title="New joiner",
            summary="s",
            equivalent_cli="x onboarding",
            run=handler,
            blast_radius=BlastRadius(summary="prep a hire"),
        )
    )

    def build_ctx(screen, read_key, *, focus=None):  # noqa: ANN001, ANN202
        return WizardContext(
            state={},
            client=None,
            console=Console(),
            # Terminal prompt fns — agent mode must SWAP these for the protocol fns, or capture
            # would block on stdin. If they're ever used in this test, the sentinel surfaces.
            input_fn=lambda prompt, default="": "TERMINAL-PROMPT-LEAKED",
            confirm_fn=lambda prompt: True,
            present=screen.update,
            read_key=read_key,
            focus=focus,
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


def test_agent_drives_a_capture_walk_via_input_requests():
    def _capture(ctx, bag):  # noqa: ANN001, ANN202
        first = ctx.input_fn("First name", "")
        last = ctx.input_fn("Surname", "")
        return StepResult(ok=True, data={"summary": f"{first} {last}"})

    handler = make_walk_handler(
        title="New joiner",
        steps=[Step("Details", _capture)],
        blast_radius=BlastRadius(summary="prep a hire"),
        preconditions_fn=lambda ctx: [],
        equivalent_cli="x onboarding",
    )
    # c → open the single-spec shelf; y → proceed past pre-flight; two input replies; q → quit.
    frames = _drive(
        _host_with_walk(handler),
        [{"key": "c"}, {"key": "y"}, {"input": "Alice"}, {"input": "Ng"}, {"key": "q"}],
    )
    clear_capabilities()

    reqs = [f["input_request"]["prompt"] for f in frames if "input_request" in f]
    assert reqs == ["First name", "Surname"], reqs
    blob = json.dumps(frames)
    assert "Alice Ng" in blob  # the protocol-supplied values drove the walk's result
    assert "TERMINAL-PROMPT-LEAKED" not in blob  # the terminal prompt fn was NOT used in agent mode


def test_agent_drives_a_confirm_request():
    def _capture(ctx, bag):  # noqa: ANN001, ANN202
        ok = ctx.confirm_fn("Proceed?")
        return StepResult(ok=True, data={"summary": f"confirmed={ok}"})

    handler = make_walk_handler(
        title="New joiner",
        steps=[Step("Details", _capture)],
        blast_radius=BlastRadius(summary="prep a hire"),
        preconditions_fn=lambda ctx: [],
        equivalent_cli="x onboarding",
    )
    frames = _drive(
        _host_with_walk(handler),
        [{"key": "c"}, {"key": "y"}, {"confirm": True}, {"key": "q"}],
    )
    clear_capabilities()

    assert any("confirm_request" in f for f in frames)
    assert "confirmed=True" in json.dumps(frames)


def test_crash_guard_message_is_never_empty_on_empty_str_exception():
    def _capture(ctx, bag):  # noqa: ANN001, ANN202
        raise RuntimeError("")  # str(e) == "" — used to render a dangling "… hit an error — "

    handler = make_walk_handler(
        title="New joiner",
        steps=[Step("Details", _capture)],
        blast_radius=BlastRadius(summary="prep a hire"),
        preconditions_fn=lambda ctx: [],
        equivalent_cli="x onboarding",
    )
    frames = _drive(_host_with_walk(handler), [{"key": "c"}, {"key": "y"}, {"key": "q"}])
    clear_capabilities()

    blob = json.dumps(frames)
    # json.dumps escapes the em-dash, so assert on ascii substrings: the fallback names the
    # exception type instead of leaving a dangling "hit an error — " with nothing after it.
    assert "hit an error" in blob and "RuntimeError" in blob
