"""Shared test fixtures for the framework suite.

``make_stub_host`` builds a minimal-but-real :class:`clonway_cockpit.shell.Host` that the
contract-gate and cockpit-client tests drive headlessly. It carries a single Doctor
capability on shelf G whose status report raises (the unconfigured path) — so driving into
``g`` deliberately emits a ``model_unstructured`` setup hint, giving the dynamic gate and the
client tests a real positive control without needing a configured worker.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from clonway_cockpit import render, shell, usage
from clonway_cockpit.doctor import fixes_for
from clonway_cockpit.registry import CapabilitySpec
from clonway_cockpit.state import CockpitState, NeedsItem, Pill

_DOCTOR = CapabilitySpec(
    key="doctor",
    shelf="G",
    title="Doctor",
    summary="Deep health check — auth, freshness, config.",
    equivalent_cli="x doctor",
    run=None,  # the shell's Doctor loop handles this key specially
)


def _build_stub_host() -> shell.Host:
    def capture_state() -> CockpitState:
        return CockpitState(
            tenant_name="Test Worker",
            app_label="x",
            date_label="Mon 01 Jun 2026",
            time_label="07:00",
            pills=(Pill(label="x", status="ok", detail="", level="ok"),),
            needs=(
                NeedsItem(title="A need", detail="do a thing", level="warn", capability_key=None),
            ),
            shelves={"A": "Capabilities", "G": "Diagnostics"},
            toolkit_label="toolkit",
        )

    def doctor_build_report() -> object:
        raise RuntimeError("unconfigured")  # → Doctor degrades to the unstructured setup hint

    return shell.Host(
        capture_state=capture_state,
        build_walk_ctx=lambda screen, read_key, focus=None: None,
        activate_pill=lambda *a: None,
        doctor_build_report=doctor_build_report,
        doctor_build_probes=lambda report: [],
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=lambda: render.render_note(
            "x doctor", "Worker not configured yet."
        ),
        usage=usage,
        on_open=lambda: None,
        app_label="x",
        get_capabilities=lambda: [_DOCTOR],
        get_capability=lambda key: _DOCTOR if key == "doctor" else None,
    )


@pytest.fixture
def make_stub_host() -> Callable[[], shell.Host]:
    """Return a factory that builds a fresh stub Host on each call."""
    return _build_stub_host
