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
    expected_focus_match = focus if focus_survives else None
    assert final.meta["focus_matched"] == expected_focus_match
    if focus_survives:
        expected_state = "matched"
    elif focus_identity.startswith("duplicate"):
        expected_state = "ambiguous"
    else:
        expected_state = "unknown"
    assert final.meta["focus_state"] == expected_state


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


@pytest.mark.parametrize(
    "after_shape", ["recovered_no_fix", "display_only", "absent", "duplicated"]
)
@pytest.mark.parametrize("selection_source", ["focused_enter", "manual_digit"])
def test_focus_verdict_stays_honest_across_a_rebuild(
    after_shape: str,
    selection_source: str,
) -> None:
    """The verdict tracks the CURRENT snapshot; the cursor stays the operator's.

    After a remedy runs, the focus target may have recovered, degraded to a
    display-only remedy, vanished or duplicated. Each is a different verdict, and
    none of them may report a probe Doctor is still rendering as "not found".
    """
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
    else:
        after = [auth, replace(auth, name="Auth twin", fix=None), lock]
        expected_state = "ambiguous"
    holder["list"] = before

    models: list = []
    screen = _Screen()
    host = replace(
        _host(before),
        doctor_build_probes=lambda report: holder["list"],
        on_screen=models.append,
    )
    # Row 1 is auth's remedy (the focus target); row 2 is the unrelated lock remedy.
    ran_title, sequence = (
        ("Repair auth", [keys.ENTER])
        if selection_source == "focused_enter"
        else ("Remove stale lock", ["2"])
    )

    shell._doctor(host, screen, _keys([*sequence, "dismiss", "q"]), focus="p.auth")

    doctor_models = [frame for frame in models if frame.kind == "doctor"]
    assert doctor_models[0].meta["focus_state"] == "matched"
    assert doctor_models[0].meta["focus_matched"] == "p.auth"
    assert doctor_models[0].selection == "fix:0"
    assert ran == ["auth" if selection_source == "focused_enter" else "lock"]
    final = doctor_models[-1]
    assert final.meta["focus_state"] == expected_state
    assert final.meta["focus_matched"] is None
    # The operator's remedy keeps the cursor while it survives; when it doesn't,
    # fail closed to the documented visible first row.
    surviving = [fix.title for fix in fixes_for(after) if fix.run is not None or fix.capability_key]
    expected_title = ran_title if ran_title in surviving else surviving[0]
    rows = next(region.rows for region in final.regions if region.role == "fixes")
    assert next(row for row in rows if row.id == final.selection).label == expected_title
    text = " ".join(_doctor_frame_text(screen.frames).split())
    assert _FOCUS_VERDICT_LINES[expected_state].format(focus="p.auth") in text
