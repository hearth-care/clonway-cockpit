from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState


def test_host_on_screen_defaults_to_noop():
    captured: list[ScreenModel] = []
    host = shell.Host(
        capture_state=lambda: CockpitState(tenant_name="C"),
        build_walk_ctx=lambda *a, **k: None,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
    )
    # Default observer is callable and a no-op (does not raise).
    host.on_screen(ScreenModel(kind="home"))
    assert captured == []


def test_shell_injects_on_screen_into_walk_ctx():
    """The shell must thread host.on_screen into the WizardContext it runs a walk with,
    so walk screens reach the same observer as home screens."""
    clear_capabilities()
    seen_ctx: list[WizardContext] = []

    def build_walk_ctx(screen, read_key, *, focus=None):
        ctx = WizardContext(
            state={},
            client=None,
            console=Console(),
            input_fn=lambda prompt, default: "",
            confirm_fn=lambda prompt: False,
            present=screen.update,
            read_key=read_key,
            focus=focus,
        )
        seen_ctx.append(ctx)
        return ctx

    def _run(ctx: WizardContext) -> None:
        # Capture the ctx the shell actually passed to the handler.
        seen_ctx.append(ctx)

    register_capability(
        CapabilitySpec(
            key="demo", shelf="C", title="Demo", summary="s", equivalent_cli="x", run=_run
        )
    )
    captured: list[ScreenModel] = []
    # Bind append once so the same object is stored in host.on_screen and
    # compared in the assertion — Python bound methods are not cached, so
    # `captured.append is captured.append` is False on each separate access.
    on_screen_cb = captured.append
    state = CockpitState(tenant_name="C")
    host = shell.Host(
        capture_state=lambda: state,
        build_walk_ctx=build_walk_ctx,
        activate_pill=lambda *a, **k: None,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda r: [],
        doctor_fixes_for=lambda p: [],
        doctor_unconfigured_renderable=lambda: render.render_note("x", "y"),
        usage=usage,
        on_open=lambda: None,
        on_screen=on_screen_cb,
    )

    class _Screen:
        def update(self, r):  # noqa: ANN001
            pass

    def _keys(seq):
        buf = list(seq)
        return lambda: buf.pop(0) if buf else "q"

    # Open shelf C (single spec → opens directly), which runs the handler, then quit.
    shell.run_cockpit(host, read_key=_keys(["c", "q"]), screen=_Screen())
    # The handler-received ctx (last appended) carries the host observer.
    handler_ctx = seen_ctx[-1]
    assert handler_ctx.on_screen is on_screen_cb
    clear_capabilities()
