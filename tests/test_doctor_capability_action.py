from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell, walk
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.doctor import Fix, Probe, fixes_for
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, NeedsItem


class _Screen:
    def __init__(self) -> None:
        self.frames = []

    def update(self, frame) -> None:  # noqa: ANN001
        self.frames.append(frame)


class _Usage:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def record(self, key: str, action: str = "open") -> None:
        self.events.append((key, action))

    def load(self) -> dict:
        return {}


def _keys(sequence: list[str]):
    remaining = list(sequence)
    return lambda: remaining.pop(0) if remaining else "q"


def _ctx(screen, read_key, *, focus=None) -> WizardContext:  # noqa: ANN001
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


def _host(
    probes: list[Probe],
    *,
    usage: _Usage | None = None,
    state: CockpitState | None = None,
) -> shell.Host:
    return shell.Host(
        capture_state=lambda: state or CockpitState(tenant_name="Clonway"),
        build_walk_ctx=_ctx,
        activate_pill=lambda *args: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda report: probes,
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Unavailable"),
        usage=usage or _Usage(),
        on_open=lambda: None,
    )


@pytest.fixture(autouse=True)
def _registry_guard():
    clear_capabilities()
    yield
    clear_capabilities()


def test_mixed_action_rows_select_only_callback_and_capability() -> None:
    probes = [
        Probe("Display", "warn", "display", Fix("Explain", "worker explain")),
        Probe("Callback", "warn", "callback", Fix("Repair", "worker repair", run=lambda: "ok")),
        Probe(
            "Capability",
            "error",
            "capability",
            Fix(
                "Review",
                "worker review",
                remedy_id="remedy.review",
                probe_id="probe.review",
                capability_key="review",
                focus="row.1",
            ),
            "probe.review",
            "rev-1",
        ),
    ]
    model = render.model_doctor(probes, fixes_for(probes), selected=1)
    rows = next(region.rows for region in model.regions if region.role == "fixes")

    assert [row.enabled for row in rows] == [False, True, True]
    assert [row.id for row in rows] == ["fix:display:0", "fix:0", "fix:1"]
    assert model.selection == "fix:1"


def test_capability_remedy_uses_normal_router_once_with_exact_focus() -> None:
    opened = []
    callback_calls = []
    audit = []
    models = []
    usage = _Usage()

    def handler(ctx: WizardContext) -> None:
        opened.append(ctx.focus)
        assert ctx.on_screen is not None
        ctx.on_screen(render.model_note("Nested review", "Structured read"))

    register_capability(
        CapabilitySpec(
            key="review",
            shelf="C",
            title="Review",
            summary="Review rows",
            equivalent_cli="worker review",
            run=handler,
        )
    )
    fix = Fix(
        "Review",
        "worker review",
        remedy_id="remedy.review",
        probe_id="probe.review",
        capability_key="review",
        focus="row.1",
    )
    probe = Probe("Review", "error", "Needed", fix, "probe.review", "rev-1")
    probes = [
        Probe("Display", "warn", "display", Fix("Explain", "worker explain")),
        Probe(
            "Callback",
            "warn",
            "callback",
            Fix("Repair", "worker repair", run=lambda: callback_calls.append(True) or "ok"),
        ),
        probe,
    ]
    host = replace(_host(probes, usage=usage), on_screen=models.append, audit_sink=audit.append)

    shell._doctor(host, _Screen(), _keys([keys.DOWN, keys.ENTER, "q"]))

    assert opened == ["row.1"]
    assert callback_calls == []
    assert usage.events.count(("review", "open")) == 1
    assert [event.capability_key for event in audit] == ["review"]
    assert "note" in [model.kind for model in models]
    assert [model.kind for model in models].count("doctor") == 3


def test_missing_capability_is_safe_and_never_runs_a_command() -> None:
    models = []
    fix = Fix(
        "Missing",
        "touch must-not-run",
        remedy_id="remedy.missing",
        probe_id="probe.missing",
        capability_key="missing",
    )
    probe = Probe("Missing", "error", "Needed", fix, "probe.missing", "rev-1")
    host = replace(_host([probe]), on_screen=models.append)

    shell._doctor(host, _Screen(), _keys([keys.ENTER, "x", "q"]))

    result = next(model for model in models if model.kind == "walk.result")
    assert result.meta["ok"] is False
    assert result.meta["message"] == "Doctor capability is unavailable."


def _agent_frames(host: shell.Host, messages: list[dict]) -> list[dict]:
    inp = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    out = io.StringIO()
    serve_stdio(host, stdin=inp, stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _agent_host(fix: Fix) -> shell.Host:
    probe = Probe("Agent probe", "error", "Needs action", fix, "probe.agent", "rev-1")
    state = CockpitState(
        tenant_name="Clonway",
        needs=(NeedsItem("Agent probe", "Needs action", "error", "doctor", "probe.agent"),),
    )
    register_capability(
        CapabilitySpec(
            key="doctor",
            shelf="G",
            title="Doctor",
            summary="Health",
            equivalent_cli="worker doctor",
        )
    )
    return _host([probe], state=state)


def test_agent_capability_reaches_nested_write_gate_and_declines() -> None:
    posts = []

    def handler(ctx: WizardContext) -> None:
        assert ctx.on_screen is not None
        ctx.on_screen(render.model_note("Nested", "Structured read"))
        if walk.confirm_apply(ctx, equivalent_cli="worker post"):
            posts.append("posted")

    register_capability(
        CapabilitySpec(
            key="review",
            shelf="C",
            title="Review",
            summary="Review",
            equivalent_cli="worker review",
            run=handler,
        )
    )
    host = _agent_host(
        Fix(
            "Review",
            "worker review",
            remedy_id="remedy.agent",
            probe_id="probe.agent",
            capability_key="review",
            focus="row.agent",
        )
    )
    frames = _agent_frames(
        host,
        [
            {"key": keys.ENTER},
            {"key": keys.ENTER},
            {"key": "x"},
            {"key": "q"},
            {"cmd": "quit"},
        ],
    )

    assert posts == []
    assert any(frame.get("kind") == "note" for frame in frames)
    gate = next(frame for frame in frames if frame.get("kind") == "walk.gate")
    assert gate["meta"]["status"] == "declined"
    assert all(frame.get("kind") != "unstructured" for frame in frames)


def test_agent_callback_is_skipped_without_calling_worker_code() -> None:
    called = []
    host = _agent_host(
        Fix(
            "Opaque callback",
            "worker callback",
            remedy_id="remedy.agent",
            probe_id="probe.agent",
            run=lambda: called.append(True) or "ran",
        )
    )
    frames = _agent_frames(
        host,
        [
            {"key": keys.ENTER},
            {"key": keys.ENTER},
            {"key": "q"},
            {"cmd": "quit"},
        ],
    )

    assert called == []
    assert any(
        frame.get("kind") == "note" and frame.get("title") == "Fix skipped" for frame in frames
    )
    assert all(frame.get("kind") != "unstructured" for frame in frames)
