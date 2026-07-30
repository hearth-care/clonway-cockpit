"""Doctor framework types — the data shapes a worker's deep health check builds.

The framework spine carries the ``Probe``/``Fix`` records plus the generic
``verdict()``/``fixes_for()`` helpers; a worker supplies the probe/fix builders
that inspect its own auth, state freshness, config and locks. Nothing
auto-applies (P4) — the cockpit prints the command to run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class DoctorActionKind(StrEnum):
    DISPLAY_ONLY = "display_only"
    CALLBACK = "callback"
    OPEN_CAPABILITY = "open_capability"


class DoctorActionResult(StrEnum):
    OPENED = "opened"
    RAN = "ran"
    DECLINED = "declined"
    SKIPPED_AGENT_MODE = "skipped_agent_mode"
    FAILED = "failed"


class DoctorClosure(StrEnum):
    RESOLVED = "resolved"
    STILL_PRESENT = "still_present"
    CHANGED = "changed"
    UNKNOWN = "unknown"


def _validate_identity(value: str, field_name: str, *, allow_empty: bool = True) -> None:
    if not value and allow_empty:
        return
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError(f"{field_name} must be a non-whitespace identifier")


@dataclass(frozen=True)
class Fix:
    title: str
    cmd: str
    note: str = ""
    run: Callable[[], str] | None = None  # None => display-only (e.g. browser auth)
    confirm: bool = False  # ask one key before running (state-changing fixes)
    remedy_id: str = ""
    probe_id: str = ""
    capability_key: str | None = None
    focus: str | None = None

    def __post_init__(self) -> None:
        if self.run is not None and self.capability_key is not None:
            raise ValueError("run and capability_key are mutually exclusive")
        if self.focus is not None and self.capability_key is None:
            raise ValueError("focus requires capability_key")
        if self.confirm and self.run is None:
            raise ValueError("confirm applies only to callback fixes")
        _validate_identity(self.remedy_id, "remedy_id")
        _validate_identity(self.probe_id, "probe_id")
        if self.capability_key is not None:
            _validate_identity(self.capability_key, "capability_key", allow_empty=False)
        if self.focus is not None:
            _validate_identity(self.focus, "focus", allow_empty=False)


@dataclass(frozen=True)
class Probe:
    name: str
    level: str  # "ok" | "warn" | "error"
    detail: str
    fix: Fix | None
    probe_id: str = ""
    evidence_revision: str = ""

    def __post_init__(self) -> None:
        _validate_identity(self.probe_id, "probe_id")
        _validate_identity(self.evidence_revision, "evidence_revision")


@dataclass(frozen=True)
class DoctorRemedyReceipt:
    schema_version: Literal[1]
    remedy_id: str
    probe_id: str
    action_kind: DoctorActionKind
    action_result: DoctorActionResult
    capability_key: str | None
    focus: str | None
    before_level: str
    before_revision: str
    after_level: str | None
    after_revision: str | None
    closure: DoctorClosure
    safe_message: str


def action_kind(fix: Fix) -> DoctorActionKind:
    if fix.capability_key is not None:
        return DoctorActionKind.OPEN_CAPABILITY
    if fix.run is not None:
        return DoctorActionKind.CALLBACK
    return DoctorActionKind.DISPLAY_ONLY


def build_remedy_receipt(
    *,
    fix: Fix,
    before: Probe,
    after: Probe | None,
    action_result: DoctorActionResult,
    rebuild_available: bool = True,
) -> DoctorRemedyReceipt:
    """Compare stable before/after probe facts without clocks, I/O or worker text."""
    stable_identity = bool(before.probe_id)
    if not rebuild_available or not stable_identity:
        closure = DoctorClosure.UNKNOWN
    elif after is None:
        closure = DoctorClosure.RESOLVED
    elif after.probe_id != before.probe_id:
        closure = DoctorClosure.UNKNOWN
    elif (after.level, after.evidence_revision) == (
        before.level,
        before.evidence_revision,
    ):
        closure = DoctorClosure.STILL_PRESENT
    else:
        closure = DoctorClosure.CHANGED

    safe_message = f"Doctor remedy {action_result.value}; probe closure {closure.value}."
    return DoctorRemedyReceipt(
        schema_version=1,
        remedy_id=fix.remedy_id,
        probe_id=before.probe_id,
        action_kind=action_kind(fix),
        action_result=action_result,
        capability_key=fix.capability_key,
        focus=fix.focus,
        before_level=before.level,
        before_revision=before.evidence_revision,
        after_level=after.level if after is not None else None,
        after_revision=after.evidence_revision if after is not None else None,
        closure=closure,
        safe_message=safe_message,
    )


def verdict(probes: list[Probe]) -> tuple[int, int]:
    """Return (warnings, errors)."""
    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    return warns, errs


def fixes_for(probes: list[Probe]) -> list[Fix]:
    """The named fixes carried by the probes, in probe order."""
    return [p.fix for p in probes if p.fix is not None]
