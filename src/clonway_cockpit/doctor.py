"""Doctor framework types — the data shapes a worker's deep health check builds.

The framework spine carries the ``Probe``/``Fix`` records plus the generic
``verdict()``/``fixes_for()`` helpers; a worker supplies the probe/fix builders
that inspect its own auth, state freshness, config and locks. Nothing
auto-applies (P4) — the cockpit prints the command to run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
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


class DoctorFocusState(StrEnum):
    """What Doctor decided about a requested focus — the SAME verdict in both
    projections (the Rich ``focus`` line and ``meta.focus_state``).

    The verdict answers "did the identity resolve, and is it actionable?" — two
    independent questions that a two-valued matched/not-found signal conflates.
    An identity Doctor is currently RENDERING is never ``unknown``: saying "not
    found" about a probe on screen is false to the operator and sends a driving
    agent down an escalation path for a target that is fine."""

    MATCHED = "matched"
    """Resolved to exactly one runnable remedy, and the cursor is on it."""
    PRESENT = "present"
    """Resolved to exactly one rendered target that has no runnable remedy (a
    display-only fix, or a probe carrying none). No row is pre-selected — the
    cursor must not be parked on an unrelated state-changing remedy."""
    AMBIGUOUS = "ambiguous"
    """Claimed by two or more targets. Fails closed: the visible first-row
    fallback is selected, but the focus did NOT authorize it."""
    UNKNOWN = "unknown"
    """Nothing Doctor renders claims the identity — the only honest "not found"."""


def _validate_identity(value: str, field_name: str, *, allow_empty: bool = True) -> None:
    if not value and allow_empty:
        return
    if (
        not value
        or value != value.strip()
        or any(char.isspace() or not char.isprintable() for char in value)
    ):
        raise ValueError(f"{field_name} must be a non-whitespace, non-control identifier")


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
        # Legacy positional construction (title, cmd, note, run, confirm) predates
        # remedy_id/probe_id/capability_key and must keep constructing unchanged —
        # confirm=True with run=None was inert-but-legal on main. Only reject the
        # combination for fixes that opt into the new identity contract, where a
        # confirm with nothing to run is an author mistake, not a legacy shape.
        newly_identified = bool(self.remedy_id or self.probe_id or self.capability_key)
        if self.confirm and self.run is None and newly_identified:
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
    before: Probe | None,
    after: Probe | None,
    action_result: DoctorActionResult,
    rebuild_available: bool = True,
) -> DoctorRemedyReceipt:
    """Compare stable before/after probe facts without clocks, I/O or worker text.

    ``before`` is ``None`` for a remedy that has no originating probe (a global,
    probe-independent fix) — the receipt still gets delivered, just with an
    ``unknown`` closure and no probe identity to report."""
    stable_identity = before is not None and bool(before.probe_id)
    if not rebuild_available or not stable_identity or before is None:
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
        probe_id=before.probe_id if before is not None else "",
        action_kind=action_kind(fix),
        action_result=action_result,
        capability_key=fix.capability_key,
        focus=fix.focus,
        before_level=before.level if before is not None else "",
        before_revision=before.evidence_revision if before is not None else "",
        after_level=after.level if after is not None else None,
        after_revision=after.evidence_revision if after is not None else None,
        closure=closure,
        safe_message=safe_message,
    )


@dataclass(frozen=True)
class DoctorRemedyRow:
    """One rendered Doctor fix row — the single record every Doctor projection reads.

    ``row_id`` is the stable id both ``render_doctor`` (as the ``N.`` ordinal) and
    ``model_doctor`` (as ``MRow.id``) number this fix with, and ``run_index`` is the
    index the shell dispatches on. Carrying all three together is what keeps the
    numbered row, the executed remedy and the receipt's probe from ever drifting
    apart."""

    fix: Fix
    probe: Probe | None
    probe_index: int | None
    row_id: str
    kind: DoctorActionKind
    run_index: int | None

    @property
    def runnable(self) -> bool:
        return self.kind is not DoctorActionKind.DISPLAY_ONLY


def _unique_match[T](candidates: list[T], predicate: Callable[[T], bool]) -> T | None:
    """Return the sole matching candidate; fail closed on zero or many matches."""
    matches = [candidate for candidate in candidates if predicate(candidate)]
    return matches[0] if len(matches) == 1 else None


def _probe_id_matches(indexed: tuple[int, Probe], *, probe_id: str) -> bool:
    return indexed[1].probe_id == probe_id


def pair_remedies(probes: list[Probe], fixes: list[Fix]) -> list[DoctorRemedyRow]:
    """Pair EVERY rendered fix with its originating probe, in ``fixes`` order.

    This is the one pairing decision in the framework: the shell dispatches from
    it, the receipt attributes from it, and both projections number and
    cross-reference rows from it. Deriving any of those independently is what let
    the executed remedy, the numbered row and the receipt's probe disagree.

    Never drop an entry: a fix with no (or no longer resolvable) originating probe
    keeps its row with ``probe=None`` and, if it is not display-only, stays
    runnable.

    An explicit ``Fix.probe_id`` resolves uniquely against the full probe snapshot
    and is intentionally not consumed: one probe may offer many typed remedies.
    Missing or duplicate explicit identities fail closed and never fall back to a
    different probe. Legacy fixes with no declared probe ID use identity/equality
    against a shrinking pool so equal legacy values still resolve deterministically
    without collapsing onto the same probe."""
    available = list(enumerate(probes))
    rows: list[DoctorRemedyRow] = []
    run_index = 0
    for index, fix in enumerate(fixes):
        kind = action_kind(fix)
        if fix.probe_id:
            matched = _unique_match(
                list(enumerate(probes)),
                partial(_probe_id_matches, probe_id=fix.probe_id),
            )
        else:
            matched = None
            for position, candidate in enumerate(available):
                if candidate[1].fix is fix:
                    matched = available.pop(position)
                    break
            else:
                for position, candidate in enumerate(available):
                    if candidate[1].fix == fix:
                        matched = available.pop(position)
                        break
        if kind is DoctorActionKind.DISPLAY_ONLY:
            row_id, row_run_index = f"fix:display:{index}", None
        else:
            row_id, row_run_index = f"fix:{run_index}", run_index
            run_index += 1
        rows.append(
            DoctorRemedyRow(
                fix=fix,
                probe=matched[1] if matched is not None else None,
                probe_index=matched[0] if matched is not None else None,
                row_id=row_id,
                kind=kind,
                run_index=row_run_index,
            )
        )
    return rows


def probe_fix_links(probes: list[Probe], rows: list[DoctorRemedyRow]) -> dict[int, str]:
    """Map each paired probe position to its first rendered remedy ``row_id``.

    The flat agent-facing probe/fix regions lose the ``Probe.fix`` adjacency the Rich
    table shows by layout, so every probe row carries it back as a ``fix_id``
    cross-reference. ``DoctorRemedyRow.probe_index`` is the authoritative relationship
    already used by dispatch and receipts: object identity may help ``pair_remedies``
    choose that relationship, but it must never override a failed, ambiguous or
    different pairing here. A probe with no paired row carries no link rather than a
    guessed one; a probe with multiple remedies links to its first rendered row."""
    links: dict[int, str] = {}
    for row in rows:
        if row.probe_index is not None:
            links.setdefault(row.probe_index, row.row_id)
    return links


def verdict(probes: list[Probe]) -> tuple[int, int]:
    """Return (warnings, errors)."""
    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    return warns, errs


def fixes_for(probes: list[Probe]) -> list[Fix]:
    """The named fixes carried by the probes, in probe order."""
    return [p.fix for p in probes if p.fix is not None]
