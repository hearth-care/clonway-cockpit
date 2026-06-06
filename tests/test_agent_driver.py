"""Integration tests for the in-process CockpitDriver: drive the real shell loop with
scripted keys and assert against the recorded ScreenModel stream."""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, Pill
from clonway_cockpit.walk import BlastRadius, Precondition, make_walk_handler

_PILLS = (Pill("Xero", "synced", "06:45", "ok", "xero"),)


def _walk_ctx(screen, read_key, *, focus=None):  # noqa: ANN001, ANN202
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


def _host(state: CockpitState) -> shell.Host:
    return shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )


def test_driver_records_home_model():
    d = CockpitDriver(_host(CockpitState(tenant_name="Clonway", pills=_PILLS)), keys=["q"])
    stream = d.run()
    assert stream, "no screens captured"
    assert stream[0].kind == "home"
    assert d.last.kind == "home"


def test_driver_drives_into_a_walk_preflight():
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="demo",
            shelf="C",
            title="Demo walk",
            summary="s",
            equivalent_cli="x",
            run=make_walk_handler(
                title="Demo",
                steps=[],
                blast_radius=BlastRadius("does a thing"),
                preconditions_fn=lambda ctx: [Precondition("ready", True)],
                equivalent_cli="x",
            ),
        )
    )
    # Open shelf C (single spec → opens the walk directly), cancel the preflight, quit.
    d = CockpitDriver(_host(CockpitState(tenant_name="Clonway")), keys=["c", "n", "q"])
    stream = d.run()
    kinds = [s.kind for s in stream]
    assert "walk.preflight" in kinds, kinds
    pre = next(s for s in stream if s.kind == "walk.preflight")
    assert pre.title == "Demo"
    assert pre.to_dict()["kind"] == "walk.preflight"  # JSON-serialisable
    clear_capabilities()
