from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell, walk
from clonway_cockpit.agent import serve_stdio
from clonway_cockpit.doctor import DoctorClosure, Fix, Probe, fixes_for, pair_remedies
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


def test_focus_matched_clears_once_the_focused_probe_resolves_mid_session() -> None:
    """Finding 5: focus_matched must be recomputed against the CURRENT remedy list
    on every frame, not cached from the first match. Open the focused capability
    remedy, resolve its probe while it's open (as the nested handler would after a
    real fix), and assert the refreshed Doctor frame reports focus_matched=None
    rather than continuing to claim a match on a remedy that is no longer there."""
    models = []
    fix_a = Fix("Open A", "worker a", remedy_id="remedy.a", probe_id="probe.a", capability_key="a")
    fix_b = Fix("Open B", "worker b", remedy_id="remedy.b", probe_id="probe.b", capability_key="b")
    probe_a = Probe("A", "warn", "a", fix_a, "probe.a", "rev-1")
    probe_b = Probe("B", "error", "b", fix_b, "probe.b", "rev-1")
    probes_holder = {"list": [probe_a, probe_b]}

    def handler(ctx: WizardContext) -> None:
        probes_holder["list"] = [probe_a]  # probe.b resolved while its remedy was open
        ctx.on_screen(render.model_note("Nested", "resolved"))

    register_capability(
        CapabilitySpec(key="a", shelf="C", title="A", summary="a", equivalent_cli="worker a")
    )
    register_capability(
        CapabilitySpec(
            key="b", shelf="C", title="B", summary="b", equivalent_cli="worker b", run=handler
        )
    )
    host = replace(
        _host([]),
        doctor_build_probes=lambda report: probes_holder["list"],
        on_screen=models.append,
    )

    shell._doctor(host, _Screen(), _keys([keys.ENTER]), focus="probe.b")

    doctor_models = [m for m in models if m.kind == "doctor"]
    assert doctor_models[0].meta["focus_matched"] == "probe.b"
    assert doctor_models[0].selection == "fix:1"

    final = doctor_models[-1]
    assert final.meta["focus_requested"] == "probe.b"
    assert final.meta["focus_matched"] is None
    assert final.selection == "fix:0"  # only A remains — not the stale probe.b row


def test_focus_matched_stays_set_when_the_focused_remedy_survives_rebuild() -> None:
    models = []
    fix_a = Fix("Open A", "worker a", remedy_id="remedy.a", probe_id="probe.a", capability_key="a")
    fix_b = Fix("Open B", "worker b", remedy_id="remedy.b", probe_id="probe.b", capability_key="b")
    probe_a = Probe("A", "warn", "a", fix_a, "probe.a", "rev-1")
    probe_b = Probe("B", "error", "b", fix_b, "probe.b", "rev-1")
    probes_holder = {"list": [probe_a, probe_b]}

    def handler(ctx: WizardContext) -> None:
        ctx.on_screen(render.model_note("Nested", "still open"))

    register_capability(
        CapabilitySpec(key="a", shelf="C", title="A", summary="a", equivalent_cli="worker a")
    )
    register_capability(
        CapabilitySpec(
            key="b", shelf="C", title="B", summary="b", equivalent_cli="worker b", run=handler
        )
    )
    host = replace(
        _host([]),
        doctor_build_probes=lambda report: probes_holder["list"],
        on_screen=models.append,
    )

    shell._doctor(host, _Screen(), _keys([keys.ENTER]), focus="probe.b")

    final = [m for m in models if m.kind == "doctor"][-1]
    assert final.meta["focus_matched"] == "probe.b"
    assert final.selection == "fix:1"


def _row_field(row, name: str) -> str:  # noqa: ANN001
    return next(field.value for field in row.fields if field.label == name)


def _resolved_focus_row(model, focus_identity: str, focus: str) -> str | None:  # noqa: ANN001
    """Independently derive the row a focus resolves to, from the emitted frame.

    Deliberately re-derived from the modeled remedy rows rather than read out of
    ``meta['focus_row']`` — the point is to catch the framework agreeing with
    itself while disagreeing with what it rendered."""
    rows = next(region.rows for region in model.regions if region.role == "fixes")
    runnable = [row for row in rows if row.enabled]
    if focus_identity in {"unique_probe_id", "multiple_remedies_one_probe"}:
        key = "probe_id"
    elif focus_identity == "unique_remedy_id":
        key = "remedy_id"
    else:  # duplicate identities and unknown focus resolve to no row at all
        return None
    return next((row.id for row in runnable if _row_field(row, key) == focus), None)


@pytest.mark.parametrize("selection_source", ["focused", "manual"])
@pytest.mark.parametrize(
    "focus_identity",
    [
        "unique_probe_id",
        "multiple_remedies_one_probe",
        "duplicate_probe_id",
        "unique_remedy_id",
        "duplicate_remedy_id",
        "unknown",
    ],
)
@pytest.mark.parametrize(
    "rebuild_shape",
    [
        "unchanged",
        "predecessor_removed",
        "predecessor_inserted",
        "reordered",
        "target_removed",
    ],
)
def test_doctor_preserves_selected_remedy_identity_across_rebuild_matrix(
    selection_source: str,
    focus_identity: str,
    rebuild_shape: str,
) -> None:
    """A rebuild may change every positional index around the selected remedy.

    Preserve the selected stable identity when it survives. Manual movement is
    authoritative after the initial focus jump, so it must preserve the remedy
    the operator selected rather than snapping back to the requested focus.
    """
    models = []
    opened: list[str] = []

    def remedy(name: str) -> tuple[Fix, Probe]:
        fix = Fix(
            f"Open {name.upper()}",
            f"worker {name}",
            remedy_id=f"remedy.{name}",
            probe_id=f"probe.{name}",
            capability_key=name,
        )
        return fix, Probe(name.upper(), "warn", name, fix, f"probe.{name}", "rev-1")

    _, probe_a = remedy("a")
    _, probe_b = remedy("b")
    _, probe_c = remedy("c")
    _, probe_x = remedy("x")
    alternate_c = Fix(
        "Open C another way",
        "worker x",
        remedy_id="remedy.c.alternate",
        probe_id="probe.c",
        capability_key="x",
    )
    initial = [probe_a, probe_b, probe_c]
    if focus_identity == "duplicate_probe_id":
        probe_x = replace(
            probe_x,
            probe_id="probe.c",
            fix=replace(probe_x.fix, probe_id="probe.c"),
        )
        initial.append(probe_x)
        focus = "probe.c"
    elif focus_identity == "duplicate_remedy_id":
        probe_x = replace(
            probe_x,
            fix=replace(probe_x.fix, remedy_id="remedy.c"),
        )
        initial.append(probe_x)
        focus = "remedy.c"
    elif focus_identity == "unique_remedy_id":
        focus = "remedy.c"
    elif focus_identity == "unknown":
        focus = "probe.missing"
    else:
        focus = "probe.c"

    focus_is_unique = focus_identity in {
        "unique_probe_id",
        "multiple_remedies_one_probe",
        "unique_remedy_id",
    }
    target_probe = (
        probe_b if selection_source == "manual" else (probe_c if focus_is_unique else probe_a)
    )
    target = target_probe.name.lower()
    if rebuild_shape == "unchanged":
        after = initial
    elif rebuild_shape == "predecessor_removed":
        removable = next((probe for probe in initial if probe is not target_probe), None)
        after = [probe for probe in initial if probe is not removable]
    elif rebuild_shape == "predecessor_inserted":
        after = [probe_x, *initial]
    elif rebuild_shape == "reordered":
        after = list(reversed(initial))
    else:
        after = [probe for probe in initial if probe is not target_probe]

    probes_holder = {"list": initial}

    def handler(name: str):
        def run(ctx: WizardContext) -> None:
            opened.append(name)
            if len(opened) == 1:
                probes_holder["list"] = after
            assert ctx.on_screen is not None
            ctx.on_screen(render.model_note("Nested", name))

        return run

    for name in ("a", "b", "c", "x"):
        register_capability(
            CapabilitySpec(
                key=name,
                shelf="C",
                title=name.upper(),
                summary=name,
                equivalent_cli=f"worker {name}",
                run=handler(name),
            )
        )
    host = replace(
        _host([]),
        doctor_build_probes=lambda report: probes_holder["list"],
        doctor_fixes_for=lambda current_probes: [
            *fixes_for(current_probes),
            *(
                [alternate_c]
                if focus_identity == "multiple_remedies_one_probe" and probe_c in current_probes
                else []
            ),
        ],
        on_screen=models.append,
    )
    sequence = []
    if selection_source == "manual":
        sequence.append("2")
    else:
        sequence.append(keys.ENTER)
    if rebuild_shape != "target_removed":
        sequence.append(keys.ENTER)
    sequence.append("q")

    shell._doctor(host, _Screen(), _keys(sequence), focus=focus)

    final = [model for model in models if model.kind == "doctor"][-1]
    assert opened == ([target] if rebuild_shape == "target_removed" else [target, target])
    if rebuild_shape != "target_removed":
        target_index = next(index for index, probe in enumerate(after) if probe is target_probe)
        assert final.selection == f"fix:{target_index}"
    else:
        # The selected remedy went away: fail closed to the documented visible
        # first row, not to whatever now occupies its stale numeric index.
        assert final.selection == "fix:0"
    focus_survives = focus_is_unique and probe_c in after
    if focus_survives:
        expected_state = "matched"
    elif focus_identity.startswith("duplicate"):
        expected_state = "ambiguous"
    else:
        expected_state = "unknown"
    assert final.meta["focus_state"] == expected_state
    # Resolution and cursor position are two separate facts. The focus keeps
    # resolving to its own remedy row (``focus_row``), but ``focus_matched`` — "the
    # SELECTED row is the one you asked for" — is only set while the cursor is
    # actually on it. A manual selection moved it away, so a frame that still
    # claimed a match would tell a driving agent that ⏎ runs its target when ⏎ runs
    # somebody else's remedy.
    expected_focus_row = _resolved_focus_row(final, focus_identity, focus)
    assert (expected_focus_row is not None) == focus_survives
    assert final.meta["focus_row"] == expected_focus_row
    assert final.meta["focus_matched"] == (
        focus if focus_survives and final.selection == expected_focus_row else None
    )
    if selection_source == "manual" and focus_survives:
        assert final.selection != expected_focus_row
        assert final.meta["focus_matched"] is None


def test_unknown_focus_starts_on_first_remedy_then_follows_its_identity() -> None:
    models = []
    opened: list[str] = []
    probes_holder: dict[str, list[Probe]] = {}

    def make_probe(name: str) -> Probe:
        fix = Fix(
            f"Open {name}",
            f"worker {name}",
            remedy_id=f"remedy.{name}",
            probe_id=f"probe.{name}",
            capability_key=name,
        )
        return Probe(name, "warn", name, fix, f"probe.{name}", "rev-1")

    probe_a, probe_b = make_probe("a"), make_probe("b")
    probes_holder["list"] = [probe_a, probe_b]

    def handler(ctx: WizardContext) -> None:
        opened.append("a")
        probes_holder["list"] = [probe_b, probe_a]
        assert ctx.on_screen is not None
        ctx.on_screen(render.model_note("Nested", "a"))

    register_capability(
        CapabilitySpec(
            key="a",
            shelf="C",
            title="A",
            summary="a",
            equivalent_cli="worker a",
            run=handler,
        )
    )
    register_capability(
        CapabilitySpec(
            key="b",
            shelf="C",
            title="B",
            summary="b",
            equivalent_cli="worker b",
            run=lambda ctx: opened.append("b"),
        )
    )
    host = replace(
        _host([]),
        doctor_build_probes=lambda report: probes_holder["list"],
        on_screen=models.append,
    )

    shell._doctor(host, _Screen(), _keys([keys.ENTER, keys.ENTER, "q"]), focus="probe.unknown")

    final = [model for model in models if model.kind == "doctor"][-1]
    assert opened == ["a", "a"]
    assert final.meta["focus_matched"] is None
    assert final.selection == "fix:1"


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


# ---------------------------------------------------------------------------
# QA round 5 — the Doctor focus verdict is four-valued, and both projections say
# the same thing. A focus that resolves to something Doctor is RENDERING must
# never be reported as "not found" (to a human) or as focus_matched=None-with-a-
# parked-cursor (to an agent). See docs/agent-screen-model.md "focus verdict".
# ---------------------------------------------------------------------------


def _doctor_frame_text(frames: list) -> str:  # noqa: ANN001
    console = Console(width=120, record=True, file=io.StringIO())
    console.print(frames[-1])
    return console.export_text()


def _runnable_fix(title: str, *, probe_id: str, remedy_id: str) -> Fix:
    return Fix(
        title,
        f"worker {remedy_id}",
        remedy_id=remedy_id,
        probe_id=probe_id,
        capability_key="noop",
    )


def _display_only_fix(title: str, *, probe_id: str, remedy_id: str) -> Fix:
    return Fix(title, f"worker {remedy_id}", remedy_id=remedy_id, probe_id=probe_id)


def _unrelated_probe() -> Probe:
    """The state-changing remedy a mis-parked cursor would run by mistake."""
    return Probe(
        "Lock",
        "error",
        "stale lock",
        _runnable_fix("Remove stale lock", probe_id="p.lock", remedy_id="remedy.lock"),
        "p.lock",
        "rev-1",
    )


def _focus_case(target: str) -> tuple[list[Probe], list[Fix], str, str, str | None]:
    """(target probes, extra fixes, focus, expected state, title focus must select)."""
    auth = _runnable_fix("Open auth", probe_id="p.auth", remedy_id="remedy.auth")
    display = _display_only_fix("Re-auth in browser", probe_id="p.auth", remedy_id="remedy.auth")
    if target == "probe_one_runnable":
        return (
            [Probe("Auth", "error", "expired", auth, "p.auth", "rev-1")],
            [],
            "p.auth",
            ("matched"),
            "Open auth",
        )
    if target == "probe_many_runnable":
        alternate = _runnable_fix("Open auth another way", probe_id="p.auth", remedy_id="remedy.b")
        return (
            [Probe("Auth", "error", "expired", auth, "p.auth", "rev-1")],
            [alternate],
            "p.auth",
            "matched",
            "Open auth",
        )
    if target == "probe_display_only_fix":
        return (
            [Probe("Auth", "error", "expired", display, "p.auth", "rev-1")],
            [],
            "p.auth",
            ("present"),
            None,
        )
    if target == "probe_no_fix":
        return (
            [Probe("Auth", "ok", "Recovered", None, "p.auth", "rev-2")],
            [],
            "p.auth",
            ("present"),
            None,
        )
    if target == "duplicate_probe_id":
        twin = _runnable_fix("Open auth twin", probe_id="p.auth", remedy_id="remedy.twin")
        return (
            [
                Probe("Auth", "error", "expired", auth, "p.auth", "rev-1"),
                Probe("Auth twin", "error", "expired", twin, "p.auth", "rev-1"),
            ],
            [],
            "p.auth",
            "ambiguous",
            None,
        )
    if target == "remedy_id_runnable":
        return (
            [Probe("Auth", "error", "expired", auth, "p.auth", "rev-1")],
            [],
            "remedy.auth",
            ("matched"),
            "Open auth",
        )
    if target == "remedy_id_display_only":
        return (
            [Probe("Auth", "error", "expired", display, "p.auth", "rev-1")],
            [],
            "remedy.auth",
            ("present"),
            None,
        )
    if target == "duplicate_remedy_id":
        twin = _runnable_fix("Open auth twin", probe_id="p.twin", remedy_id="remedy.auth")
        return (
            [
                Probe("Auth", "error", "expired", auth, "p.auth", "rev-1"),
                Probe("Auth twin", "error", "expired", twin, "p.twin", "rev-1"),
            ],
            [],
            "remedy.auth",
            "ambiguous",
            None,
        )
    if target == "dangling_probe_id_runnable":
        return (
            [Probe("Host", "error", "expired", auth, "p.host", "rev-1")],
            [],
            "p.auth",
            ("matched"),
            "Open auth",
        )
    if target == "dangling_probe_id_display_only":
        return (
            [Probe("Host", "error", "expired", display, "p.host", "rev-1")],
            [],
            "p.auth",
            ("present"),
            None,
        )
    sync = _runnable_fix("Open sync", probe_id="p.sync", remedy_id="remedy.sync")
    return [Probe("Sync", "warn", "stale", sync, "p.sync", "rev-1")], [], "p.auth", "unknown", None


_FOCUS_VERDICT_LINES = {
    "matched": "{focus} matched",
    "present": "{focus} present — no runnable remedy",
    "ambiguous": "{focus} ambiguous — review selection",
    "unknown": "{focus} not found — review selection",
}


@pytest.mark.parametrize(
    "focus_target",
    [
        "probe_one_runnable",
        "probe_many_runnable",
        "probe_display_only_fix",
        "probe_no_fix",
        "duplicate_probe_id",
        "remedy_id_runnable",
        "remedy_id_display_only",
        "duplicate_remedy_id",
        "dangling_probe_id_runnable",
        "dangling_probe_id_display_only",
        "absent",
    ],
)
@pytest.mark.parametrize("target_position", ["first", "last"])
@pytest.mark.parametrize("entry", ["direct", "capability_open"])
def test_doctor_focus_verdict_matrix(
    focus_target: str,
    target_position: str,
    entry: str,
) -> None:
    """One focus decision, two projections, four honest verdicts.

    Every cell asserts the Rich line, ``meta['focus_matched']``/``meta['focus_state']``
    and ``model.selection`` TOGETHER — a verdict that is honest in one projection and
    wrong in the other is the defect this matrix exists to catch.
    """
    target_probes, extra_fixes, focus, expected_state, matched_title = _focus_case(focus_target)
    probes = (
        [*target_probes, _unrelated_probe()]
        if target_position == "first"
        else [_unrelated_probe(), *target_probes]
    )
    models: list = []
    screen = _Screen()
    host = replace(
        _host(probes),
        doctor_fixes_for=lambda current: [*fixes_for(current), *extra_fixes],
        on_screen=models.append,
    )
    # Independent derivation of the expected row: the ordinal of the remedy whose
    # TITLE focus must select, among the rows Doctor numbers (non-display-only).
    all_fixes = host.doctor_fixes_for(probes)
    runnable_titles = [
        fix.title for fix in all_fixes if fix.run is not None or fix.capability_key is not None
    ]
    if entry == "capability_open":
        register_capability(
            CapabilitySpec(
                key="doctor",
                shelf="C",
                title="Doctor",
                summary="deep health check",
                equivalent_cli="worker doctor",
            )
        )
        shell._open_capability(host, "doctor", screen, _keys([]), focus=focus)
    else:
        shell._doctor(host, screen, _keys([]), focus=focus)

    model = [frame for frame in models if frame.kind == "doctor"][-1]
    text = _doctor_frame_text(screen.frames)

    assert model.meta["focus_requested"] == focus
    assert model.meta["focus_state"] == expected_state
    if expected_state == "matched":
        assert matched_title is not None
        assert model.meta["focus_matched"] == focus
        assert model.selection == f"fix:{runnable_titles.index(matched_title)}"
    else:
        assert model.meta["focus_matched"] is None
        # Present-but-not-actionable must not park the cursor on an unrelated
        # state-changing remedy; unknown/ambiguous keep the documented visible
        # first-row fallback.
        assert model.selection == (None if expected_state == "present" else "fix:0")
    assert _FOCUS_VERDICT_LINES[expected_state].format(focus=focus) in " ".join(text.split())
    # The identity is never reported as absent while Doctor is rendering it.
    if expected_state != "unknown":
        assert f"{focus} not found" not in " ".join(text.split())


def _lock_probe(ran: list[str]) -> Probe:
    """The unrelated state-changing remedy a mis-parked cursor would run."""
    return Probe(
        "Lock",
        "error",
        "stale lock",
        Fix(
            "Remove stale lock",
            "worker unlock",
            remedy_id="remedy.lock",
            probe_id="p.lock",
            run=lambda: ran.append("lock") or "done",
        ),
        "p.lock",
        "rev-1",
    )


def test_present_focus_runs_nothing_on_a_single_enter() -> None:
    """A PRESENT focus pre-selects nothing, so ⏎ must reveal, not run.

    The hazard this closes: the operator asked for p.auth, whose only remedy is
    display-only, and the one runnable row belongs to an unrelated probe. If the
    cursor were parked there, a single ⏎ on a screen the operator believes shows
    their target runs somebody else's state-changing remedy."""
    ran: list[str] = []
    probes = [
        Probe(
            "Auth",
            "error",
            "expired",
            _display_only_fix("Re-auth in browser", probe_id="p.auth", remedy_id="remedy.auth"),
            "p.auth",
            "rev-1",
        ),
        _lock_probe(ran),
    ]
    models: list = []
    host = replace(_host(probes), on_screen=models.append)

    shell._doctor(host, _Screen(), _keys([keys.ENTER, "q"]), focus="p.auth")

    assert ran == []
    doctor_models = [frame for frame in models if frame.kind == "doctor"]
    assert doctor_models[0].meta["focus_state"] == "present"
    assert doctor_models[0].selection is None
    # The reveal frame shows the fallback cursor and has still run nothing.
    assert doctor_models[-1].selection == "fix:0"
    assert doctor_models[-1].meta["focus_state"] == "present"


@pytest.mark.parametrize("reveal_key", [keys.UP, keys.DOWN, keys.ENTER])
def test_any_reveal_key_uncovers_the_fallback_without_running_it(reveal_key: str) -> None:
    ran: list[str] = []
    probes = [
        Probe("Auth", "ok", "Recovered", None, "p.auth", "rev-2"),
        _lock_probe(ran),
    ]
    models: list = []
    host = replace(_host(probes), on_screen=models.append)

    shell._doctor(host, _Screen(), _keys([reveal_key, "q"]), focus="p.auth")

    assert ran == []
    doctor_models = [frame for frame in models if frame.kind == "doctor"]
    assert doctor_models[0].selection is None
    assert doctor_models[-1].selection == "fix:0"


def test_present_focus_still_runs_an_explicitly_numbered_remedy() -> None:
    """A digit is an unambiguous choice — it needs no reveal step."""
    ran: list[str] = []
    probes = [Probe("Auth", "ok", "Recovered", None, "p.auth", "rev-2"), _lock_probe(ran)]
    models: list = []
    host = replace(_host(probes), on_screen=models.append)

    shell._doctor(host, _Screen(), _keys(["1", "dismiss", "q"]), focus="p.auth")

    assert ran == ["lock"]


@pytest.mark.parametrize("focus", [None, ""])
def test_falsy_focus_is_no_focus_not_a_focus_on_the_empty_identity(focus: str | None) -> None:
    """``NeedsItem.focus`` is an unvalidated ``str | None``, so "" reaches Doctor.

    Legacy probes all carry an empty ``probe_id``, so an empty focus used to
    "match" one and render ``focus  ✓  matched`` with a blank identifier."""
    probes = [_lock_probe([])]
    models: list = []
    screen = _Screen()
    host = replace(_host(probes), on_screen=models.append)

    shell._doctor(host, screen, _keys([]), focus=focus)

    model = [frame for frame in models if frame.kind == "doctor"][-1]
    assert model.meta["focus_requested"] is None
    assert model.meta["focus_matched"] is None
    assert model.meta["focus_state"] is None
    assert model.selection == "fix:0"
    assert "focus" not in _doctor_frame_text(screen.frames)


def _cursored_lines(text: str) -> list[str]:
    """The rendered rows carrying the ❯ cursor — the human half of "what is armed"."""
    return [" ".join(line.split()) for line in text.splitlines() if "❯" in line]


def _doctor_frame_texts(frames: list) -> list[str]:  # noqa: ANN001
    """Every DOCTOR screen the human saw, in order — the Rich twin of the ``doctor``
    ScreenModel frames, so cursor and ``selection`` can be compared frame for frame
    rather than only at the end."""
    texts = []
    for frame in frames:
        console = Console(width=120, record=True, file=io.StringIO())
        console.print(frame)
        text = console.export_text()
        if "deep health check" in text:
            texts.append(text)
    return texts


@pytest.mark.parametrize(
    "after_shape",
    ["recovered_no_fix", "display_only", "absent", "duplicated", "still_runnable"],
)
@pytest.mark.parametrize("selection_source", ["focused_enter", "manual_arrow", "manual_digit"])
def test_focus_verdict_stays_honest_across_a_rebuild(
    after_shape: str,
    selection_source: str,
) -> None:
    """The verdict AND the cursor track the CURRENT snapshot, on every rebuild.

    After a remedy runs, the focus target may have recovered, degraded to a
    display-only remedy, vanished, duplicated or survived intact. Each is a
    different verdict, none of them may report a probe Doctor is still rendering as
    "not found", and the two that leave the target present-but-not-actionable must
    re-hide the cursor: otherwise the remedy the operator just ran silently arms an
    unrelated one, and the next ⏎ runs it.

    Selection visibility is therefore derived from the current focus decision after
    EVERY rebuild, not just on entry. An explicit manual choice is authoritative
    only under the snapshot it was made in; a rebuild is a new snapshot, so the
    verdict governs again rather than the operator's stale intent."""
    ran: list[str] = []
    holder: dict[str, list[Probe]] = {}

    def runner(name: str):
        def run() -> str:
            ran.append(name)
            holder["list"] = after
            return "done"

        return run

    auth_fix = Fix(
        "Repair auth",
        "worker auth",
        remedy_id="remedy.auth",
        probe_id="p.auth",
        run=runner("auth"),
    )
    lock_fix = Fix(
        "Remove stale lock",
        "worker unlock",
        remedy_id="remedy.lock",
        probe_id="p.lock",
        run=runner("lock"),
    )
    auth = Probe("Auth", "error", "expired", auth_fix, "p.auth", "rev-1")
    lock = Probe("Lock", "error", "stale lock", lock_fix, "p.lock", "rev-1")
    before = [auth, lock]
    if after_shape == "recovered_no_fix":
        after = [replace(auth, level="ok", detail="Recovered", fix=None), lock]
        expected_state = "present"
    elif after_shape == "display_only":
        after = [
            replace(
                auth,
                fix=_display_only_fix(
                    "Re-auth in browser", probe_id="p.auth", remedy_id="remedy.auth"
                ),
            ),
            lock,
        ]
        expected_state = "present"
    elif after_shape == "absent":
        after = [lock]
        expected_state = "unknown"
    elif after_shape == "duplicated":
        after = [auth, replace(auth, name="Auth twin", fix=None), lock]
        expected_state = "ambiguous"
    else:
        after = [auth, lock]
        expected_state = "matched"
    holder["list"] = before

    models: list = []
    screen = _Screen()
    host = replace(
        _host(before),
        doctor_build_probes=lambda report: holder["list"],
        on_screen=models.append,
    )
    # Row 1 is auth's remedy (the focus target); row 2 is the unrelated lock remedy.
    ran_title, sequence = {
        "focused_enter": ("Repair auth", [keys.ENTER]),
        "manual_arrow": ("Remove stale lock", [keys.DOWN, keys.ENTER]),
        "manual_digit": ("Remove stale lock", ["2"]),
    }[selection_source]
    first = "auth" if selection_source == "focused_enter" else "lock"
    # After the rebuild, one more ⏎ — the exact keypress that used to run an
    # unrelated remedy the operator never selected.
    shell._doctor(
        host, screen, _keys([*sequence, "dismiss", keys.ENTER, "dismiss", "q"]), focus="p.auth"
    )

    doctor_models = [frame for frame in models if frame.kind == "doctor"]
    doctor_texts = _doctor_frame_texts(screen.frames)
    # Entry: the focus is resolved AND the cursor is on it, so all three facts agree.
    assert doctor_models[0].meta["focus_state"] == "matched"
    assert doctor_models[0].meta["focus_matched"] == "p.auth"
    assert doctor_models[0].meta["focus_row"] == "fix:0"
    assert doctor_models[0].selection == "fix:0"
    if selection_source == "manual_arrow":
        # ↓ moved the cursor off the focused remedy without acting. The focus still
        # RESOLVES there (focus_state/focus_row), but the frame may no longer claim
        # the selected row is the requested one.
        moved = doctor_models[1]
        assert moved.meta["focus_state"] == "matched"
        assert moved.meta["focus_row"] == "fix:0"
        assert moved.meta["focus_matched"] is None
        assert moved.selection == "fix:1"

    # The refreshed frame, BEFORE the follow-up ⏎ — human and model side by side.
    rebuilt_index = 2 if selection_source == "manual_arrow" else 1
    rebuilt = doctor_models[rebuilt_index]
    rebuilt_text = doctor_texts[rebuilt_index]
    assert rebuilt.meta["focus_state"] == expected_state
    surviving = [fix.title for fix in fixes_for(after) if fix.run is not None or fix.capability_key]
    if expected_state == "present":
        # Present-but-not-actionable: nothing is armed, in EITHER projection, and
        # the follow-up ⏎ therefore reveals rather than runs.
        assert rebuilt.selection is None
        assert _cursored_lines(rebuilt_text) == []
        assert ran == [first]
    else:
        expected_title = ran_title if ran_title in surviving else surviving[0]
        rows = next(region.rows for region in rebuilt.regions if region.role == "fixes")
        assert next(row for row in rows if row.id == rebuilt.selection).label == expected_title
        assert any(expected_title in line for line in _cursored_lines(rebuilt_text))
        assert ran == [first, "auth" if expected_title == "Repair auth" else "lock"]
    # ``focus_matched`` is non-null in exactly one situation: the focus resolved AND
    # the cursor is sitting on the row it resolved to. Never on the strength of the
    # verdict alone, and never with no cursor at all.
    assert rebuilt.meta["focus_matched"] == (
        "p.auth"
        if expected_state == "matched" and rebuilt.selection == rebuilt.meta["focus_row"]
        else None
    )

    final = doctor_models[-1]
    assert final.meta["focus_state"] == expected_state
    text = " ".join(_doctor_frame_text(screen.frames).split())
    assert _FOCUS_VERDICT_LINES[expected_state].format(focus="p.auth") in text


# ---------------------------------------------------------------------------
# QA round 6 — the doctor-remedy-state-coherence class, closed as a state space
# rather than cell by cell. Six rounds of findings were all the same defect in
# different clothes: Doctor derived "which remedy is armed", "where did the focus
# resolve" and "which probe owns this remedy" in more than one place, so a frame
# could claim one thing while ⏎ did another. These matrices assert the Rich
# projection, the ScreenModel projection and the executed callback TOGETHER, so a
# divergence cannot be green in any one of them.
# ---------------------------------------------------------------------------


def _linked_fix_id(row) -> str | None:  # noqa: ANN001
    return next((field.value for field in row.fields if field.label == "fix_id"), None)


def _coherence_probes(focus_shape: str, ran: list[str]) -> list[Probe]:
    """The probe snapshot for one ``focus_shape``.

    ``Sync`` leads and ``Lock`` trails, so every cell has at least two numbered
    rows whatever the focus target is (keeping the ``cursor_action`` axis
    independent of it) and — crucially — the focus NEVER resolves to row 1. Row 1
    is the documented fail-closed fallback, so a matrix that put the target there
    could not tell "the focus selected this" from "we fell back to row one"."""

    def callback(title: str) -> Fix:
        slug = title.lower().replace(" ", "-")
        return Fix(
            title,
            f"worker {slug}",
            remedy_id=f"remedy.{slug}",
            probe_id=f"p.{slug.split('-')[-1]}",
            run=lambda: ran.append(title) or "done",
        )

    head = Probe("Sync", "warn", "stale", callback("Sync now"), "p.now", "rev-1")
    tail = Probe("Lock", "error", "stale lock", callback("Remove stale lock"), "p.lock", "rev-1")
    auth = replace(callback("Repair auth"), probe_id="p.auth")
    if focus_shape == "matched_runnable":
        target = [Probe("Auth", "error", "expired", auth, "p.auth", "rev-1")]
    elif focus_shape == "present_display_only":
        display = _display_only_fix("Re-auth in browser", probe_id="p.auth", remedy_id="remedy.web")
        target = [Probe("Auth", "error", "expired", display, "p.auth", "rev-1")]
    elif focus_shape == "present_no_fix":
        target = [Probe("Auth", "ok", "Recovered", None, "p.auth", "rev-2")]
    elif focus_shape == "ambiguous":
        twin = replace(callback("Repair auth twin"), probe_id="p.auth")
        target = [
            Probe("Auth", "error", "expired", auth, "p.auth", "rev-1"),
            Probe("Auth twin", "error", "expired", twin, "p.auth", "rev-1"),
        ]
    else:
        target = []  # "unknown" — nothing Doctor renders claims p.auth
    return [head, *target, tail]


_COHERENCE_STATES = {
    "matched_runnable": "matched",
    "present_display_only": "present",
    "present_no_fix": "present",
    "ambiguous": "ambiguous",
    "unknown": "unknown",
}


@pytest.mark.parametrize(
    "focus_shape",
    ["matched_runnable", "present_display_only", "present_no_fix", "ambiguous", "unknown"],
)
@pytest.mark.parametrize("cursor_action", ["none", "up", "down", "digit"])
@pytest.mark.parametrize("remedy_pairing", ["same_object", "stable_id_clone", "unpaired_global"])
def test_doctor_remedy_state_coherence_matrix(
    focus_shape: str,
    cursor_action: str,
    remedy_pairing: str,
) -> None:
    """One armed remedy, one focus resolution, one probe->remedy relation.

    Every cell asserts, on the SAME frame: the Rich ❯ cursor, ``ScreenModel``
    ``selection``/``focus_state``/``focus_row``/``focus_matched``, the probe rows'
    ``fix_id`` cross-reference, and — for the ``digit`` cell — which callback
    actually ran. A frame may never claim a match for a row the cursor is not on,
    may never arm a row while reporting a ``present`` focus, and may never execute
    a remedy other than the one it numbered.
    """
    ran: list[str] = []
    probes = _coherence_probes(focus_shape, ran)
    resync = Fix("Global resync", "worker resync", run=lambda: ran.append("Global resync") or "ok")

    def fixes_for_pairing(current: list[Probe]) -> list[Fix]:
        own = fixes_for(current)
        if remedy_pairing == "same_object":
            return own
        if remedy_pairing == "stable_id_clone":
            # A worker that normalizes its fix list but preserves stable IDs — a
            # supported shape the pairing must still resolve.
            return [replace(fix, note="normalized copy") for fix in own]
        return [*own, resync]  # a probe-independent global remedy

    models: list = []
    screen = _Screen()
    host = replace(
        _host(probes),
        doctor_fixes_for=fixes_for_pairing,
        on_screen=models.append,
    )
    rendered = fixes_for_pairing(probes)
    runnable_titles = [fix.title for fix in rendered if fix.run is not None or fix.capability_key]
    total = len(runnable_titles)
    expected_state = _COHERENCE_STATES[focus_shape]
    # Independently derived: the row the focus resolves to is the numbered row
    # carrying p.auth, and only when exactly one does.
    resolved = [index for index, title in enumerate(runnable_titles) if title == "Repair auth"]
    focus_row = f"fix:{resolved[0]}" if expected_state == "matched" else None
    assert focus_row != "fix:0"  # never the fail-closed fallback row, by construction
    # Digit 1 is deliberately NOT the focus row: an explicit choice must win over
    # the focus, and the receipt/anchor must bring the cursor back to it.
    sequence = {
        "none": [],
        "up": [keys.UP],
        "down": [keys.DOWN],
        "digit": ["1", "dismiss"],
    }[cursor_action]

    shell._doctor(host, screen, _keys([*sequence, "q"]), focus="p.auth")

    final = [frame for frame in models if frame.kind == "doctor"][-1]
    final_text = _doctor_frame_texts(screen.frames)[-1]

    # --- the focus verdict is the RESOLUTION, and it never moves with the cursor
    assert final.meta["focus_requested"] == "p.auth"
    assert final.meta["focus_state"] == expected_state
    assert final.meta["focus_row"] == focus_row

    # --- what is armed, agreed by both projections
    #     present + no explicit choice under THIS snapshot => nothing armed. The
    #     digit cell rebuilds, which starts a new snapshot, so it re-hides too.
    start = resolved[0] if expected_state == "matched" else 0
    expected_index: int | None = {
        "none": None if expected_state == "present" else start,
        # A reveal keypress uncovers the fallback WITHOUT moving it.
        "up": 0 if expected_state == "present" else (start - 1) % total,
        "down": 0 if expected_state == "present" else (start + 1) % total,
        "digit": None if expected_state == "present" else 0,
    }[cursor_action]
    if expected_index is None:
        assert final.selection is None
        assert _cursored_lines(final_text) == []
    else:
        assert final.selection == f"fix:{expected_index}"
        assert any(runnable_titles[expected_index] in line for line in _cursored_lines(final_text))

    # --- "the selected row is the one you asked for", and nothing weaker
    assert final.meta["focus_matched"] == (
        "p.auth" if focus_row is not None and final.selection == focus_row else None
    )

    # --- the numbered row is the row that ran
    assert ran == ([runnable_titles[0]] if cursor_action == "digit" else [])

    # --- one probe->remedy relation, shared with dispatch and receipts
    paired = shell._runnable_remedies(probes, rendered)
    probe_rows = next(region.rows for region in final.regions if region.role == "probes")
    fix_rows = next(region.rows for region in final.regions if region.role == "fixes")
    labels = {row.id: row.label for row in fix_rows}
    for index, probe in enumerate(probes):
        link = _linked_fix_id(probe_rows[index])
        ambiguous_relationship = focus_shape == "ambiguous" and probe.probe_id == "p.auth"
        if probe.fix is None or ambiguous_relationship:
            # No fix, or an identity two probes claim: fail closed rather than
            # cross-referencing a guess.
            assert link is None
        else:
            assert labels[link] == probe.fix.title
    # The dispatch list attributes the same probes the projection cross-references.
    for row_index, (probe, fix) in enumerate(paired):
        if probe is not None:
            assert _linked_fix_id(probe_rows[probes.index(probe)]) in (None, f"fix:{row_index}")
        assert labels[f"fix:{row_index}"] == fix.title


@pytest.mark.parametrize(
    "focus_identity", ["unique_probe_id", "one_probe_many_remedies", "unique_remedy_id"]
)
@pytest.mark.parametrize("movement", [keys.UP, keys.DOWN])
def test_moving_the_cursor_off_a_focused_remedy_stops_claiming_a_match(
    focus_identity: str,
    movement: str,
) -> None:
    """A no-action cursor move must not leave two fields disagreeing.

    ``focus_state``/``focus_row`` describe RESOLUTION and stay put; ``focus_matched``
    describes the SELECTION and must clear the moment the cursor leaves the resolved
    row. An agent that read a non-null ``focus_matched`` as "⏎ runs my target" would
    otherwise run whatever row it had just navigated to."""
    ran: list[str] = []

    def callback(title: str, *, probe_id: str, remedy_id: str) -> Fix:
        return Fix(
            title,
            f"worker {remedy_id}",
            remedy_id=remedy_id,
            probe_id=probe_id,
            run=lambda: ran.append(title) or "done",
        )

    auth = callback("Repair auth", probe_id="p.auth", remedy_id="remedy.auth")
    extra: list[Fix] = []
    focus = "p.auth"
    if focus_identity == "one_probe_many_remedies":
        # One probe legitimately offering two typed remedies: the focus resolves to
        # the FIRST runnable one, and the second must not be mistaken for it.
        extra = [callback("Repair auth another way", probe_id="p.auth", remedy_id="remedy.alt")]
    elif focus_identity == "unique_remedy_id":
        focus = "remedy.auth"
    probes = [
        Probe("Sync", "warn", "stale", callback("Sync now", probe_id="p.now", remedy_id="r.now")),
        Probe("Auth", "error", "expired", auth, "p.auth", "rev-1"),
        Probe(
            "Lock",
            "error",
            "stale lock",
            callback("Remove stale lock", probe_id="p.lock", remedy_id="r.lock"),
        ),
    ]
    models: list = []
    screen = _Screen()
    host = replace(
        _host(probes),
        doctor_fixes_for=lambda current: [*fixes_for(current), *extra],
        on_screen=models.append,
    )
    titles = [fix.title for fix in host.doctor_fixes_for(probes)]

    shell._doctor(host, screen, _keys([movement, "q"]), focus=focus)

    doctor_models = [frame for frame in models if frame.kind == "doctor"]
    resolved_row = f"fix:{titles.index('Repair auth')}"
    entry, moved = doctor_models[0], doctor_models[-1]
    assert entry.meta["focus_state"] == "matched"
    assert entry.meta["focus_row"] == resolved_row
    assert entry.meta["focus_matched"] == focus
    assert entry.selection == resolved_row

    step = -1 if movement == keys.UP else 1
    expected_index = (titles.index("Repair auth") + step) % len(titles)
    assert moved.selection == f"fix:{expected_index}"
    assert moved.selection != resolved_row
    # Resolution is unchanged; only the "is the cursor on it" fact flipped.
    assert moved.meta["focus_state"] == "matched"
    assert moved.meta["focus_row"] == resolved_row
    assert moved.meta["focus_matched"] is None
    assert ran == []
    # The human projection says the same thing: no bare ✓ next to a cursor that has
    # moved on to somebody else's remedy.
    text = " ".join(_doctor_frame_texts(screen.frames)[-1].split())
    assert f"⚠ {focus} matched — cursor on row {titles.index('Repair auth') + 1}" in text
    assert f"✓ {focus} matched" not in text
    assert any(
        titles[expected_index] in line
        for line in _cursored_lines(_doctor_frame_texts(screen.frames)[-1])
    )


def _relationship_case(
    relationship: str,
    ran: list[str],
) -> tuple[list[Probe], list[Fix], dict[int, str | None], list[int | None], int]:
    """Build one complete probe/remedy relationship state.

    Returns probes, rendered remedies, expected modeled links, expected authoritative
    probe indices for each runnable remedy, and the remedy row the drive selects.
    """

    def callback(title: str, *, remedy_id: str = "", probe_id: str = "") -> Fix:
        return Fix(
            title,
            f"worker {title.lower().replace(' ', '-')}",
            run=lambda: ran.append(title) or "done",
            remedy_id=remedy_id,
            probe_id=probe_id,
        )

    if relationship == "unique_direct":
        fix = callback("Unique", remedy_id="r.unique", probe_id="p.unique")
        return (
            [Probe("Unique", "error", "detail", fix, "p.unique", "rev-unique")],
            [fix],
            {0: "fix:0"},
            [0],
            0,
        )
    if relationship == "equal_legacy_clone":
        fix = callback("Legacy equal")
        return (
            [Probe("Legacy", "warn", "detail", fix)],
            [replace(fix)],
            {0: "fix:0"},
            [0],
            0,
        )
    if relationship == "stable_id_clone":
        fix = callback("Stable clone", remedy_id="r.stable", probe_id="p.stable")
        return (
            [Probe("Stable", "error", "detail", fix, "p.stable", "rev-stable")],
            [replace(fix, note="normalized")],
            {0: "fix:0"},
            [0],
            0,
        )
    if relationship in {"duplicate_id_direct", "duplicate_id_clone"}:
        first = callback("Duplicate A", remedy_id="r.duplicate.a", probe_id="p.duplicate")
        second = callback("Duplicate B", remedy_id="r.duplicate.b", probe_id="p.duplicate")
        remedies = [first, second]
        if relationship == "duplicate_id_clone":
            remedies = [replace(first, note="normalized A"), replace(second, note="normalized B")]
        return (
            [
                Probe("Duplicate A", "error", "detail", first, "p.duplicate", "rev-a"),
                Probe("Duplicate B", "error", "detail", second, "p.duplicate", "rev-b"),
            ],
            remedies,
            {0: None, 1: None},
            [None, None],
            1,
        )
    if relationship == "shared_repeated_legacy_instance":
        shared = callback("Shared legacy")
        return (
            [
                Probe("Shared A", "warn", "detail", shared),
                Probe("Shared B", "error", "detail", shared),
            ],
            [shared, shared],
            {0: "fix:0", 1: "fix:1"},
            [0, 1],
            1,
        )
    if relationship == "conflicting_explicit_owner":
        fix = callback("Conflicting owner", remedy_id="r.conflict", probe_id="p.actual")
        return (
            [
                Probe("Direct owner", "error", "detail", fix, "p.direct", "rev-direct"),
                Probe("Explicit owner", "warn", "detail", None, "p.actual", "rev-actual"),
            ],
            [fix],
            {0: None, 1: "fix:0"},
            [1],
            0,
        )
    if relationship == "unresolvable_explicit_owner":
        fix = callback("Missing owner", remedy_id="r.missing", probe_id="p.missing")
        return (
            [Probe("Direct owner", "error", "detail", fix, "p.direct", "rev-direct")],
            [fix],
            {0: None},
            [None],
            0,
        )
    global_fix = callback("Global resync")
    return (
        [Probe("Recovered", "ok", "detail", None, "p.recovered", "rev-recovered")],
        [global_fix],
        {0: None},
        [None],
        0,
    )


@pytest.mark.parametrize(
    "relationship",
    [
        "unique_direct",
        "equal_legacy_clone",
        "stable_id_clone",
        "duplicate_id_direct",
        "duplicate_id_clone",
        "shared_repeated_legacy_instance",
        "conflicting_explicit_owner",
        "unresolvable_explicit_owner",
        "unpaired_global",
    ],
)
@pytest.mark.parametrize("display_layout", ["absent", "interleaved"])
def test_doctor_relationship_layout_state_coherence_matrix(
    relationship: str,
    display_layout: str,
) -> None:
    """Model link, dispatch, selected callback and receipt share ONE relationship."""
    ran: list[str] = []
    receipts = []
    probes, remedies, expected_links, expected_pairing, target = _relationship_case(
        relationship, ran
    )
    if display_layout == "interleaved":
        # Display-only rows are numbered separately (``fix:display:<i>``), so they
        # must not shift the runnable row ids the shell dispatches on.
        fixes: list[Fix] = []
        for index, fix in enumerate(remedies):
            fixes.append(Fix(f"Read the runbook {index}", f"worker docs {index}"))
            fixes.append(fix)
    else:
        fixes = list(remedies)

    model = render.model_doctor(probes, fixes)
    probe_rows = next(region.rows for region in model.regions if region.role == "probes")
    fix_rows = next(region.rows for region in model.regions if region.role == "fixes")
    runnable_rows = [row for row in fix_rows if row.enabled]
    display_rows = [row for row in fix_rows if not row.enabled]

    # Row ids: runnable rows stay consecutively numbered whatever the layout.
    assert [row.id for row in runnable_rows] == [f"fix:{i}" for i in range(len(remedies))]
    assert [row.label for row in runnable_rows] == [fix.title for fix in remedies]
    if display_layout == "interleaved":
        assert [row.id for row in display_rows] == [
            f"fix:display:{i * 2}" for i in range(len(remedies))
        ]

    # The link the agent reads is the pairing the shell dispatches from.
    assert {i: _linked_fix_id(row) for i, row in enumerate(probe_rows)} == expected_links
    rows = [row for row in pair_remedies(probes, fixes) if row.runnable]
    assert [row.probe_index for row in rows] == expected_pairing
    paired = shell._runnable_remedies(probes, fixes)
    assert [fix.title for _, fix in paired] == [fix.title for fix in remedies]
    assert [
        None
        if probe is None
        else next(i for i, candidate in enumerate(probes) if candidate is probe)
        for probe, _ in paired
    ] == expected_pairing

    host = replace(
        _host(probes),
        doctor_fixes_for=lambda current: fixes,
        doctor_on_receipt=receipts.append,
    )
    shell._doctor(host, _Screen(), _keys([str(target + 1), "dismiss", "q"]))

    assert ran == [remedies[target].title]
    assert len(receipts) == 1
    paired_index = expected_pairing[target]
    if paired_index is None:
        assert receipts[0].probe_id == ""
        assert receipts[0].before_revision == ""
        assert receipts[0].closure is DoctorClosure.UNKNOWN
    else:
        paired_probe = probes[paired_index]
        assert receipts[0].probe_id == paired_probe.probe_id
        assert receipts[0].before_revision == paired_probe.evidence_revision
        assert receipts[0].closure is (
            DoctorClosure.STILL_PRESENT if paired_probe.probe_id else DoctorClosure.UNKNOWN
        )
