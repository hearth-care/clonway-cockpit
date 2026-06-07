"""Emit tests for the M1-rest draw sites: drive the real shell/walk path with scripted
keys and a no-op screen, then assert the new model lands in the recorded stream."""

from __future__ import annotations

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import (
    CapabilitySpec,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState, NeedsItem


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


def _kinds(stream: list[ScreenModel]) -> list[str]:
    return [m.kind for m in stream]


# --- Task 1: note emit ---------------------------------------------------------


def test_note_emitted_when_opening_a_plain_need():
    # A need with no capability_key drills to a note (its title/detail). Land the
    # cursor on it (it is the only actionable row) and press enter.
    state = CockpitState(
        tenant_name="Clonway",
        needs=(NeedsItem("Read me", "just a note", "warn", ""),),
    )
    driver = CockpitDriver(_host(state), keys=["enter", "x", "q"])  # enter need → any key → quit
    stream = driver.run()
    notes = [m for m in stream if m.kind == "note"]
    assert notes, f"no note emitted; saw {_kinds(stream)}"
    assert notes[0].title == "Read me"


# --- Task 2: capability card emit ----------------------------------------------


def test_capability_card_emitted_for_reference_only_spec():
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="loans",
            shelf="F",
            title="Term loans",
            summary="Review the loan schedule",
            equivalent_cli="xbook loans review",
        )  # run=None → reference-only card
    )
    state = CockpitState(tenant_name="Clonway")
    # Shelf F has one spec → opens directly into the card; any key returns; quit.
    driver = CockpitDriver(_host(state), keys=["f", "x", "q"])
    stream = driver.run()
    clear_capabilities()
    cards = [m for m in stream if m.kind == "card"]
    assert cards, f"no card emitted; saw {_kinds(stream)}"
    assert cards[0].title == "Term loans"


# --- Task 3: help emit ---------------------------------------------------------


def test_help_emitted_on_question_key():
    state = CockpitState(tenant_name="Clonway")
    driver = CockpitDriver(_host(state), keys=["?", "x", "q"])
    stream = driver.run()
    helps = [m for m in stream if m.kind == "help"]
    assert helps, f"no help emitted; saw {_kinds(stream)}"
    assert helps[0].title == "Keys"
