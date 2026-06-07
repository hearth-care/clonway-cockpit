"""The framework-enforced agent dry-run write gate (M2).

In agent mode, walk.confirm_apply must ALWAYS decline — an agent can press the apply
key and see it refused, but no walk ever posts. The flag rides WizardContext.dry_run,
threaded from Host.agent_mode at the shell's open-capability chokepoint.
"""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import walk
from clonway_cockpit.registry import WizardContext


def _ctx(*, dry_run: bool, key: str) -> WizardContext:
    return WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        read_key=lambda: key,
        dry_run=dry_run,
    )


def test_confirm_apply_declines_in_dry_run_even_on_apply_key():
    for key in ("a", "A", "enter"):
        assert walk.confirm_apply(_ctx(dry_run=True, key=key), equivalent_cli="x") is False


def test_confirm_apply_applies_normally_when_not_dry_run():
    assert walk.confirm_apply(_ctx(dry_run=False, key="a"), equivalent_cli="x") is True
    assert walk.confirm_apply(_ctx(dry_run=False, key="n"), equivalent_cli="x") is False


def test_agent_mode_threads_dry_run_into_a_driven_walk():
    from clonway_cockpit import render, shell, usage
    from clonway_cockpit.agent import CockpitDriver
    from clonway_cockpit.registry import (
        BlastRadius,
        CapabilitySpec,
        clear_capabilities,
        register_capability,
    )
    from clonway_cockpit.state import CockpitState
    from clonway_cockpit.walk import confirm_apply

    posted: list[bool] = []

    def handler(ctx) -> None:  # a walk that "posts" only if the gate confirms
        if confirm_apply(ctx, equivalent_cli="xbook bills"):
            posted.append(True)

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

    def build_ctx(screen, read_key, *, focus=None):
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

    host = shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=build_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
        agent_mode=True,  # <-- the dry-run switch
    )
    # Open shelf C (single spec → opens directly into the handler); the handler hits
    # the gate, presses "a", but dry_run declines → never posts. "q" quits.
    CockpitDriver(host, keys=["c", "a", "q"]).run()
    clear_capabilities()
    assert posted == [], "agent-mode walk posted despite dry-run"
