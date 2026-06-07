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


# --- Task 8: progress emit -----------------------------------------------------


class _NullScreenForTest:
    def update(self, frame) -> None:  # noqa: ANN001
        return None


def test_staged_progress_emits_one_model_per_stage_change():
    from clonway_cockpit import walk

    emitted: list[ScreenModel] = []

    def fn(reporter):
        reporter.start("fetch")
        reporter.done("fetch")
        reporter.start("post")
        reporter.done("post")
        return "done"

    walk.animate_staged(
        present=lambda frame: None,
        label="Schedule bills",
        fn=fn,
        stages=[("fetch", "Fetch data"), ("post", "Post batch")],
        emit=emitted.append,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        tick=0.0,
    )
    assert emitted, "no progress models emitted"
    assert all(m.kind == "walk.progress" for m in emitted)
    sigs = [tuple((s["key"], s["status"]) for s in m.meta["stages"]) for m in emitted]
    assert all(a != b for a, b in zip(sigs, sigs[1:], strict=False)), f"duplicate emits: {sigs}"


def test_sync_progress_emits_through_run_with_progress():
    emitted: list[ScreenModel] = []
    shell.run_with_progress(
        screen=_NullScreenForTest(),
        label="Syncing",
        fn=lambda: "ok",
        emit=emitted.append,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        tick=0.0,
    )
    syncs = [m for m in emitted if m.kind == "walk.progress"]
    assert syncs, "no sync progress model emitted"
    assert syncs[0].meta["label"] == "Syncing"


def test_staged_progress_emits_terminal_snapshot():
    # The worker can flip the last stage to done inside the final join window, after
    # the loop's emit — the post-loop emit must still surface the all-done snapshot.
    from clonway_cockpit import walk

    emitted: list[ScreenModel] = []

    def fn(reporter):
        reporter.start("fetch")
        reporter.done("fetch")
        reporter.start("post")
        reporter.done("post")
        return "done"

    walk.animate_staged(
        present=lambda frame: None,
        label="L",
        fn=fn,
        stages=[("fetch", "Fetch"), ("post", "Post")],
        emit=emitted.append,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        tick=0.0,
    )
    assert emitted, "no progress models emitted"
    assert all(s["status"] == "done" for s in emitted[-1].meta["stages"]), emitted[-1].meta[
        "stages"
    ]


# --- Audit fix #1: a raising observer never crashes the cockpit ----------------


def _scripted(seq):  # noqa: ANN001, ANN202 — returns "q" once the script is exhausted
    buf = list(seq)
    return lambda: buf.pop(0) if buf else "q"


def _boom(model) -> None:  # noqa: ANN001
    raise RuntimeError("observer blew up")


def test_raising_observer_does_not_crash_the_cockpit():
    state = CockpitState(
        tenant_name="Clonway",
        needs=(NeedsItem("Read me", "just a note", "warn", ""),),
    )
    host = _host(state, on_screen=_boom)
    # Drive home (emits) → open the note (emits) → any key → quit. Must not raise.
    shell.run_cockpit(host, read_key=_scripted(["enter", "x", "q"]), screen=_NullScreenForTest())


def test_raising_observer_does_not_defeat_the_walk_crash_guard():
    def crashing_run(ctx) -> None:  # noqa: ANN001
        raise ValueError("walk exploded")

    def build_ctx(screen, read_key, *, focus=None):  # noqa: ANN001, ANN202
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
            key="sb",
            shelf="C",
            title="Schedule bills",
            summary="s",
            equivalent_cli="x",
            run=crashing_run,
        )
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(state, on_screen=_boom, build_walk_ctx=build_ctx)
    # Open shelf C (single spec) → walk crashes → crash guard re-emits a result model
    # (which raises in the observer) → must still be swallowed; any key → quit.
    shell.run_cockpit(host, read_key=_scripted(["c", "x", "q"]), screen=_NullScreenForTest())
    clear_capabilities()


# --- Task 9: unstructured emit -------------------------------------------------


def test_unstructured_emitted_when_doctor_unconfigured():
    def boom():
        raise RuntimeError("not configured")

    clear_capabilities()
    register_capability(
        CapabilitySpec(
            key="doctor", shelf="G", title="Doctor", summary="health", equivalent_cli="x"
        )
    )
    state = CockpitState(tenant_name="Clonway")
    host = _host(
        state,
        doctor_build_report=boom,
        doctor_unconfigured_renderable=lambda: render.render_note("Setup", "run init"),
    )
    driver = CockpitDriver(host, keys=["g", "x", "q"])  # open doctor → any key → quit
    stream = driver.run()
    clear_capabilities()
    unstr = [m for m in stream if m.kind == "unstructured"]
    assert unstr, f"no unstructured model emitted; saw {_kinds(stream)}"
