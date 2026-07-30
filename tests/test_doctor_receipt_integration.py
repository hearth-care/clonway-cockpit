from __future__ import annotations

from dataclasses import replace

import pytest
from rich.console import Console

from clonway_cockpit import keys, render, shell
from clonway_cockpit.doctor import (
    DoctorActionResult,
    DoctorClosure,
    DoctorRemedyReceipt,
    Fix,
    Probe,
    fixes_for,
)
from clonway_cockpit.registry import (
    CapabilitySpec,
    WizardContext,
    clear_capabilities,
    register_capability,
)
from clonway_cockpit.state import CockpitState


class _Screen:
    def update(self, frame) -> None:  # noqa: ANN001
        pass


class _Usage:
    def record(self, key: str, action: str = "open") -> None:
        pass

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


def _probe(
    fix: Fix | None,
    *,
    revision: str = "rev-1",
    probe_id: str = "probe.health",
    level: str = "error",
) -> Probe:
    return Probe("Health", level, "Safe detail", fix, probe_id, revision)


def _host(
    build_probes,
    receipts: list[DoctorRemedyReceipt],
    *,
    build_report=lambda: object(),
    agent_mode: bool = False,
) -> shell.Host:
    return shell.Host(
        capture_state=lambda: CockpitState(tenant_name="Clonway"),
        build_walk_ctx=_ctx,
        activate_pill=lambda *args: None,
        doctor_build_report=build_report,
        doctor_build_probes=build_probes,
        doctor_fixes_for=fixes_for,
        doctor_unconfigured_renderable=lambda: render.render_note("Doctor", "Unavailable"),
        usage=_Usage(),
        on_open=lambda: None,
        agent_mode=agent_mode,
        doctor_on_receipt=receipts.append,
    )


@pytest.fixture(autouse=True)
def _registry_guard():
    clear_capabilities()
    yield
    clear_capabilities()


def test_callback_receipt_reports_resolved_once() -> None:
    receipts = []
    resolved = False

    def run() -> str:
        nonlocal resolved
        resolved = True
        return "done"

    fix = Fix(
        "Repair",
        "worker repair",
        run=run,
        remedy_id="remedy.health",
        probe_id="probe.health",
    )
    host = _host(lambda report: [] if resolved else [_probe(fix)], receipts)

    shell._doctor(host, _Screen(), _keys([keys.ENTER, "dismiss", "q"]))

    assert len(receipts) == 1
    assert receipts[0].action_result is DoctorActionResult.RAN
    assert receipts[0].closure is DoctorClosure.RESOLVED


@pytest.mark.parametrize(
    ("after_revision", "after_level", "closure"),
    [
        ("rev-1", "error", DoctorClosure.STILL_PRESENT),
        ("rev-2", "error", DoctorClosure.CHANGED),
        ("rev-1", "warn", DoctorClosure.CHANGED),
    ],
)
def test_capability_receipt_compares_after_nested_return(
    after_revision: str,
    after_level: str,
    closure: DoctorClosure,
) -> None:
    receipts = []
    opened = False
    order = []

    def handler(ctx: WizardContext) -> None:
        nonlocal opened
        order.append("capability")
        opened = True

    register_capability(
        CapabilitySpec("review", "C", "Review", "Review", "worker review", run=handler)
    )
    fix = Fix(
        "Review",
        "worker review",
        remedy_id="remedy.health",
        probe_id="probe.health",
        capability_key="review",
        focus="health",
    )

    def probes(report) -> list[Probe]:  # noqa: ANN001
        if opened:
            order.append("rebuild")
            return [_probe(fix, revision=after_revision, level=after_level)]
        return [_probe(fix)]

    shell._doctor(_host(probes, receipts), _Screen(), _keys([keys.ENTER, "q"]))

    assert order == ["capability", "rebuild"]
    assert len(receipts) == 1
    assert receipts[0].action_result is DoctorActionResult.OPENED
    assert receipts[0].closure is closure


def test_capability_receipt_reports_resolved_only_after_reprobe() -> None:
    receipts = []
    resolved = False

    def handler(ctx: WizardContext) -> None:
        nonlocal resolved
        resolved = True

    register_capability(
        CapabilitySpec("review", "C", "Review", "Review", "worker review", run=handler)
    )
    fix = Fix(
        "Review",
        "worker review",
        remedy_id="remedy.health",
        probe_id="probe.health",
        capability_key="review",
    )
    host = _host(lambda report: [] if resolved else [_probe(fix)], receipts)

    shell._doctor(host, _Screen(), _keys([keys.ENTER, "q"]))

    assert len(receipts) == 1
    assert receipts[0].action_result is DoctorActionResult.OPENED
    assert receipts[0].closure is DoctorClosure.RESOLVED


@pytest.mark.parametrize("display_layout", ["absent", "interleaved"])
@pytest.mark.parametrize(
    "pairing_case",
    [
        "same_object",
        "equal_clone",
        "stable_id_clone",
        "shared_equal_values",
        "unpaired",
        "reordered_subset",
        "ambiguous_duplicate_id",
    ],
)
def test_doctor_remedy_pairing_state_matrix(
    pairing_case: str,
    display_layout: str,
) -> None:
    """Dispatch and receipt attribution share one ordered, fail-closed pairing."""
    receipts: list[DoctorRemedyReceipt] = []
    models = []
    calls: list[str] = []

    def run() -> str:
        calls.append("target")
        return "done"

    target = Fix(
        "Target",
        "worker target",
        run=run,
        remedy_id="remedy.target",
        probe_id="probe.target",
    )
    target_probe = Probe(
        "Target",
        "error",
        "Safe detail",
        target,
        "probe.target",
        "rev-target",
    )
    expected_probe_id = "probe.target"
    expected_revision = "rev-target"
    expected_closure = DoctorClosure.STILL_PRESENT

    if pairing_case == "same_object":
        probes = [target_probe]
        fixes = [target]
        target_index = 0
    elif pairing_case == "equal_clone":
        probes = [target_probe]
        fixes = [replace(target)]
        target_index = 0
    elif pairing_case == "stable_id_clone":
        probes = [target_probe]
        fixes = [replace(target, note="worker-normalized display copy")]
        target_index = 0
    elif pairing_case == "shared_equal_values":
        legacy = Fix("Target", "worker target", run=run)
        probes = [
            Probe("First", "warn", "first", legacy, "probe.first", "rev-first"),
            Probe(
                "Target",
                "error",
                "target",
                replace(legacy),
                "probe.target",
                "rev-target",
            ),
        ]
        fixes = [replace(legacy), replace(legacy)]
        target_index = 1
    elif pairing_case == "unpaired":
        probes = [Probe("Other", "warn", "other", None, "probe.other", "rev-other")]
        fixes = [target]
        target_index = 0
        expected_probe_id = ""
        expected_revision = ""
        expected_closure = DoctorClosure.UNKNOWN
    elif pairing_case == "reordered_subset":
        before = Fix(
            "Before",
            "worker before",
            run=lambda: "before",
            remedy_id="remedy.before",
            probe_id="probe.before",
        )
        after = Fix(
            "After",
            "worker after",
            run=lambda: "after",
            remedy_id="remedy.after",
            probe_id="probe.after",
        )
        probes = [
            Probe("Before", "warn", "before", before, "probe.before", "rev-before"),
            target_probe,
            Probe("After", "warn", "after", after, "probe.after", "rev-after"),
        ]
        fixes = [after, target]
        target_index = 1
    else:
        duplicate = Probe(
            "Duplicate",
            "warn",
            "duplicate",
            replace(target, note="duplicate"),
            "probe.target",
            "rev-duplicate",
        )
        probes = [target_probe, duplicate]
        fixes = [target]
        target_index = 0
        expected_probe_id = ""
        expected_revision = ""
        expected_closure = DoctorClosure.UNKNOWN

    if display_layout == "interleaved":
        display = Fix("Display only", "worker explain", note="Read the runbook")
        fixes = [display, *fixes, display]

    host = replace(
        _host(lambda report: probes, receipts),
        doctor_fixes_for=lambda current_probes: fixes,
        on_screen=models.append,
    )

    shell._doctor(
        host,
        _Screen(),
        _keys([str(target_index + 1), "dismiss", "q"]),
    )

    first_doctor = next(model for model in models if model.kind == "doctor")
    rows = next(region.rows for region in first_doctor.regions if region.role == "fixes")
    target_row = next(row for row in rows if row.id == f"fix:{target_index}")
    fields = {field.label: field.value for field in target_row.fields}
    assert target_row.enabled is True
    assert (
        fields["remedy_id"]
        == fixes[(target_index + 1) if display_layout == "interleaved" else target_index].remedy_id
    )
    assert calls == ["target"]
    assert len(receipts) == 1
    assert receipts[0].probe_id == expected_probe_id
    assert receipts[0].before_revision == expected_revision
    assert receipts[0].closure is expected_closure


@pytest.mark.parametrize(
    ("agent_mode", "raises", "keys_in", "result"),
    [
        (False, False, [keys.ENTER, "n", "q"], DoctorActionResult.DECLINED),
        (True, False, [keys.ENTER, "q"], DoctorActionResult.SKIPPED_AGENT_MODE),
        (False, True, [keys.ENTER, "dismiss", "q"], DoctorActionResult.FAILED),
    ],
)
def test_callback_non_success_results_emit_one_still_present_receipt(
    agent_mode: bool,
    raises: bool,
    keys_in: list[str],
    result: DoctorActionResult,
) -> None:
    receipts = []
    calls = []

    def run() -> str:
        calls.append(True)
        if raises:
            raise RuntimeError("worker-secret")
        return "done"

    fix = Fix(
        "Repair",
        "worker repair",
        run=run,
        confirm=result is DoctorActionResult.DECLINED,
        remedy_id="remedy.health",
        probe_id="probe.health",
    )
    builds = 0

    def build_report() -> object:
        nonlocal builds
        builds += 1
        return object()

    host = _host(
        lambda report: [_probe(fix)], receipts, build_report=build_report, agent_mode=agent_mode
    )

    shell._doctor(host, _Screen(), _keys(keys_in))

    # Plan Step 4.1: rebuild happens exactly once for an ATTEMPTED action — decline,
    # agent-mode skip and a failed callback are all attempts (the operator/agent
    # engaged the remedy), so each still rebuilds once to refresh the probe facts,
    # on top of the one build Doctor always does on entry (contrast with the
    # capability_missing branch below, which never attempted anything and stays
    # at the entry build alone).
    assert builds == 2
    assert len(receipts) == 1
    assert receipts[0].action_result is result
    assert receipts[0].closure is DoctorClosure.STILL_PRESENT
    assert calls == ([True] if raises else [])
    assert "worker-secret" not in receipts[0].safe_message


def test_missing_capability_receipt_is_failed_unknown_without_rebuild() -> None:
    receipts = []
    builds = 0
    fix = Fix(
        "Missing",
        "worker missing",
        remedy_id="remedy.health",
        probe_id="probe.health",
        capability_key="missing",
    )

    def build_report() -> object:
        nonlocal builds
        builds += 1
        return object()

    host = _host(lambda report: [_probe(fix)], receipts, build_report=build_report)
    shell._doctor(host, _Screen(), _keys([keys.ENTER, "dismiss", "q"]))

    assert builds == 1
    assert len(receipts) == 1
    assert receipts[0].action_result is DoctorActionResult.FAILED
    assert receipts[0].closure is DoctorClosure.UNKNOWN


def test_rebuild_failure_classification_makes_closure_unknown() -> None:
    receipts = []
    builds = 0
    fix = Fix(
        "Repair",
        "worker repair",
        run=lambda: "done",
        remedy_id="remedy.health",
        probe_id="probe.health",
    )

    def build_report() -> object:
        nonlocal builds
        builds += 1
        if builds == 2:
            raise RuntimeError("rebuild-secret")
        return object()

    host = replace(
        _host(lambda report: [_probe(fix)], receipts, build_report=build_report),
        doctor_classify_report_failure=lambda exc: Probe(
            "Rebuild",
            "error",
            "Safe rebuild failure",
            None,
            "probe.rebuild",
            "rev-2",
        ),
    )
    shell._doctor(host, _Screen(), _keys([keys.ENTER, "dismiss", "q"]))

    assert len(receipts) == 1
    assert receipts[0].closure is DoctorClosure.UNKNOWN


def test_rebuild_classifier_failure_makes_closure_unknown() -> None:
    receipts = []
    builds = 0
    fix = Fix(
        "Repair",
        "worker repair",
        run=lambda: "done",
        remedy_id="remedy.health",
        probe_id="probe.health",
    )

    def build_report() -> object:
        nonlocal builds
        builds += 1
        if builds == 2:
            raise RuntimeError("rebuild-secret")
        return object()

    def classifier(exc: Exception) -> Probe:
        raise LookupError("classifier-secret")

    host = replace(
        _host(lambda report: [_probe(fix)], receipts, build_report=build_report),
        doctor_classify_report_failure=classifier,
    )
    shell._doctor(host, _Screen(), _keys([keys.ENTER, "dismiss", "q"]))

    assert len(receipts) == 1
    assert receipts[0].closure is DoctorClosure.UNKNOWN
    assert "secret" not in receipts[0].safe_message


def test_repeat_attempts_use_each_new_before_revision() -> None:
    receipts = []
    revision = 1

    def run() -> str:
        nonlocal revision
        revision += 1
        return "done"

    fix = Fix(
        "Repair",
        "worker repair",
        run=run,
        remedy_id="remedy.health",
        probe_id="probe.health",
    )
    host = _host(lambda report: [_probe(fix, revision=f"rev-{revision}")], receipts)

    shell._doctor(
        host,
        _Screen(),
        _keys([keys.ENTER, "dismiss", keys.ENTER, "dismiss", "q"]),
    )

    assert [(r.before_revision, r.after_revision) for r in receipts] == [
        ("rev-1", "rev-2"),
        ("rev-2", "rev-3"),
    ]
    assert all(receipt.closure is DoctorClosure.CHANGED for receipt in receipts)


def test_receipt_callback_failure_does_not_change_doctor_outcome(caplog) -> None:
    delivered = []
    fix = Fix(
        "Repair",
        "worker repair",
        run=lambda: "done",
        remedy_id="remedy.health",
        probe_id="probe.health",
    )

    def fail_delivery(receipt: DoctorRemedyReceipt) -> None:
        delivered.append(receipt)
        raise RuntimeError("observability-secret")

    host = replace(
        _host(lambda report: [_probe(fix)], []),
        doctor_on_receipt=fail_delivery,
    )

    with caplog.at_level("WARNING", logger="clonway_cockpit.shell"):
        shell._doctor(host, _Screen(), _keys([keys.ENTER, "dismiss", "q"]))

    # A broken receipt sink must not go silently unobserved (nit: zero signal on a
    # permanently-broken sink) — but the log carries only IDs/result/closure and the
    # exception CLASS, never the raw exception text (which may hold worker detail).
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "remedy.health" in message
    assert "probe.health" in message
    assert "RuntimeError" in message
    assert "observability-secret" not in message

    assert len(delivered) == 1
