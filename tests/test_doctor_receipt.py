from dataclasses import FrozenInstanceError

import pytest

from clonway_cockpit.doctor import (
    DoctorActionKind,
    DoctorActionResult,
    DoctorClosure,
    Fix,
    Probe,
    build_remedy_receipt,
)


def _probe(*, level: str = "error", revision: str = "rev-1", probe_id: str = "probe.gap") -> Probe:
    fix = Fix(
        "Review gap",
        "worker review",
        remedy_id="remedy.gap.review",
        probe_id=probe_id,
        capability_key="review",
        focus="gap",
    )
    return Probe("Gap", level, "Safe detail", fix, probe_id, revision)


def test_receipt_enums_have_stable_serialized_values() -> None:
    assert [member.value for member in DoctorActionResult] == [
        "opened",
        "ran",
        "declined",
        "skipped_agent_mode",
        "failed",
    ]
    assert [member.value for member in DoctorClosure] == [
        "resolved",
        "still_present",
        "changed",
        "unknown",
    ]


@pytest.mark.parametrize(
    ("after", "rebuild_available", "closure"),
    [
        (None, True, DoctorClosure.RESOLVED),
        (_probe(), True, DoctorClosure.STILL_PRESENT),
        (_probe(level="warn"), True, DoctorClosure.CHANGED),
        (_probe(revision="rev-2"), True, DoctorClosure.CHANGED),
        (None, False, DoctorClosure.UNKNOWN),
    ],
)
def test_build_receipt_compares_the_same_stable_probe(
    after: Probe | None,
    rebuild_available: bool,
    closure: DoctorClosure,
) -> None:
    before = _probe()
    receipt = build_remedy_receipt(
        fix=before.fix,
        before=before,
        after=after,
        action_result=DoctorActionResult.OPENED,
        rebuild_available=rebuild_available,
    )

    assert receipt.schema_version == 1
    assert receipt.remedy_id == "remedy.gap.review"
    assert receipt.probe_id == "probe.gap"
    assert receipt.action_kind is DoctorActionKind.OPEN_CAPABILITY
    assert receipt.action_result is DoctorActionResult.OPENED
    assert receipt.capability_key == "review"
    assert receipt.focus == "gap"
    assert receipt.before_level == "error"
    assert receipt.before_revision == "rev-1"
    assert receipt.after_level == (after.level if after is not None else None)
    assert receipt.after_revision == (after.evidence_revision if after is not None else None)
    assert receipt.closure is closure
    assert len(receipt.safe_message) <= 160


def test_receipt_with_legacy_empty_identity_is_unknown() -> None:
    before = _probe(probe_id="")
    receipt = build_remedy_receipt(
        fix=before.fix,
        before=before,
        after=None,
        action_result=DoctorActionResult.FAILED,
    )

    assert receipt.closure is DoctorClosure.UNKNOWN


def test_receipt_with_no_originating_probe_is_unknown_not_a_crash() -> None:
    """Finding 3's flip side at the receipt layer: an unpaired remedy (no probe)
    still gets a receipt — probe_id empty, closure unknown — instead of the caller
    needing to special-case a missing `before`."""
    fix = Fix("Global resync", "worker resync", run=lambda: "ok")
    receipt = build_remedy_receipt(
        fix=fix,
        before=None,
        after=None,
        action_result=DoctorActionResult.RAN,
    )

    assert receipt.probe_id == ""
    assert receipt.before_level == ""
    assert receipt.before_revision == ""
    assert receipt.closure is DoctorClosure.UNKNOWN


def test_receipt_safe_message_is_framework_generated_and_frozen() -> None:
    secret = "raw-provider-exception-with-sensitive-detail"
    fix = Fix(
        "Review gap",
        "worker review",
        remedy_id="remedy.gap.review",
        probe_id="probe.gap",
        capability_key="review",
        focus="gap",
    )
    # The secret flows in through the only worker-controlled text on a probe
    # (`detail`) — build_remedy_receipt must never fold it into safe_message.
    before = Probe("Gap", "error", secret, fix, "probe.gap", "rev-1")
    receipt = build_remedy_receipt(
        fix=before.fix,
        before=before,
        after=None,
        action_result=DoctorActionResult.FAILED,
    )

    assert secret not in receipt.safe_message
    with pytest.raises(FrozenInstanceError):
        receipt.safe_message = secret  # type: ignore[misc]
