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
    initial = [probe_a, probe_b, probe_c]
    target = "c" if selection_source == "focused" else "b"
    target_probe = probe_c if target == "c" else probe_b
    if rebuild_shape == "unchanged":
        after = initial
    elif rebuild_shape == "predecessor_removed":
        after = [target_probe, probe_c] if target == "b" else [probe_b, probe_c]
    elif rebuild_shape == "predecessor_inserted":
        after = [probe_x, *initial]
    elif rebuild_shape == "reordered":
        after = [probe_c, probe_b, probe_a]
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
        on_screen=models.append,
    )
    sequence = []
    if selection_source == "manual":
        sequence.append(keys.UP)
    sequence.append(keys.ENTER)
    if rebuild_shape != "target_removed":
        sequence.append(keys.ENTER)
    sequence.append("q")

    shell._doctor(host, _Screen(), _keys(sequence), focus="probe.c")

    final = [model for model in models if model.kind == "doctor"][-1]
    assert opened == ([target] if rebuild_shape == "target_removed" else [target, target])
    if rebuild_shape != "target_removed":
        target_index = next(
            index for index, probe in enumerate(after) if probe.probe_id == f"probe.{target}"
        )
        assert final.selection == f"fix:{target_index}"
    if selection_source == "focused":
        assert final.meta["focus_matched"] == (
            None if rebuild_shape == "target_removed" else "probe.c"
        )


def test_unknown_focus_keeps_first_remedy_selected_after_rebuild() -> None:
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
