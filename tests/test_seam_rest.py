"""Emit tests for the M1-rest draw sites: drive the real shell/walk path with scripted
keys and a no-op screen, then assert the new model lands in the recorded stream."""

from __future__ import annotations

from rich.console import Console

from clonway_cockpit import render, shell, usage
from clonway_cockpit.agent import CockpitDriver
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
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


# --- Task 4: remedy confirm emit -----------------------------------------------


def test_remedy_confirm_emitted_in_preflight():
    from clonway_cockpit.registry import BlastRadius
    from clonway_cockpit.walk import Precondition, Remedy, preflight

    captured: list[ScreenModel] = []
    remedy = Remedy(key="u", label="clear the stale apply lock", action=lambda: "cleared")
    preconds = [Precondition("No stale lock", False, "lock held", remedy=remedy)]
    ctx = WizardContext(
        state={},
        client=None,
        console=Console(),
        input_fn=lambda prompt, default: "",
        confirm_fn=lambda prompt: False,
        present=lambda frame: None,
        # press the remedy key, then cancel the confirm with a non-y key
        read_key=iter(["u", "n"]).__next__,
        on_screen=captured.append,
    )
    preflight(
        ctx,
        title="Schedule bills",
        blast_radius=BlastRadius(summary="posts a batch"),
        preconditions=preconds,
        equivalent_cli="xbook bills",
        recheck=lambda: preconds,
    )
    confirms = [m for m in captured if m.kind == "confirm"]
    assert confirms, f"no remedy confirm emitted; saw {[m.kind for m in captured]}"
    assert confirms[0].meta["confirm_of"] == "remedy"


# --- Task 5: doctor emit -------------------------------------------------------


def test_doctor_emitted_when_opening_doctor():
    from clonway_cockpit.doctor import Probe

    probes = [Probe("Xero auth", "ok", "token fresh", None)]
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="doctor", shelf="G", title="Doctor", summary="health", equivalent_cli="x"
        )
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_report=lambda: object(),
        doctor_build_probes=lambda rep: probes,
        doctor_fixes_for=lambda p: [],
    )
    # Shelf G has one spec (doctor) → opens directly; q exits doctor, q quits home.
    driver = CockpitDriver(host, keys=["g", "q", "q"])
    stream = driver.run()
    clear_capabilities()
    docs = [m for m in stream if m.kind == "doctor"]
    assert docs, f"no doctor model emitted; saw {_kinds(stream)}"
    assert docs[0].meta["ok"] is True


# --- Task 6: filter emit -------------------------------------------------------


def test_filter_emitted_on_slash():
    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="sb", shelf="C", title="Schedule bills", summary="plan", equivalent_cli="x"
        )
    )
    state = CockpitState(tenant_name="Clonway")
    # / opens the filter; type "s"; esc closes filter; q quits home.
    driver = CockpitDriver(_host(state), keys=["/", "s", "esc", "q"])
    stream = driver.run()
    clear_capabilities()
    filters = [m for m in stream if m.kind == "filter"]
    assert filters, f"no filter emitted; saw {_kinds(stream)}"
    # After typing 's', the registered capability matched.
    assert any(row.label == "Schedule bills" for f in filters for row in f.regions[0].rows)
