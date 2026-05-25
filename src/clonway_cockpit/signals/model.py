"""Signal — the shared, forward-looking "what needs you, by when" record.

Promotes the cockpit ``NeedsItem`` to the family Signal contract. A Signal is a
superset of NeedsItem: the same human fields plus the worker, a coarse kind +
urgency, a stable dedup key, a lifecycle ``state``, and a ``due_at`` slot. A
worker builds Signals FROM its NeedsItems and emits them; NeedsItem and the
cockpit render stay untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as Date
from uuid import NAMESPACE_URL, uuid5

from clonway_cockpit.state import NeedsItem

SIGNAL_KINDS = frozenset(
    {
        "deadline.approaching",
        "action.required",
        "anomaly.detected",
        "approval.pending",
        "credential.expiring",
    }
)

# Fixed namespace so dedup keys are stable across processes and cycles.
_SIGNAL_NS = uuid5(NAMESPACE_URL, "clonway.signals")

# Exact-title → kind. The closed set the cockpit needs-you ranking produces; an
# unknown title falls back to action.required (a future needs item still emits,
# never crashes).
_TITLE_KIND: dict[str, str] = {
    "Set up xbook": "action.required",
    "Re-authenticate Xero": "credential.expiring",
    "Sync the books": "action.required",
    "Sync is stale": "action.required",
    "Bills overdue": "action.required",
    "Bills due this week": "deadline.approaching",
    "Unmatched bank lines": "action.required",
    "DRAFT bills need approval": "approval.pending",
    "DD amount anomalies": "anomaly.detected",
    "Pay run needs finishing": "action.required",
    "Pay run due to post": "deadline.approaching",
    "HMRC payment coming up": "deadline.approaching",
    "Pension payment coming up": "deadline.approaching",
    "Cash getting tight": "deadline.approaching",
    "Next month loss-making": "deadline.approaching",
    "Cash outlook worsened": "anomaly.detected",
    "Profit outlook worsened": "anomaly.detected",
    # Forward sources outside needs_you(): one title per domain so an item
    # crossing due_soon→overdue keeps its dedup_key (urgency carries the
    # escalation), not a re-raise.
    "Insurance renewal due": "deadline.approaching",
    "Compliance filing due": "deadline.approaching",
}

_LEVEL_URGENCY: dict[str, str] = {"ok": "info", "warn": "soon", "error": "due"}


def _kind_for(title: str) -> str:
    return _TITLE_KIND.get(title, "action.required")


def _urgency_for(level: str) -> str:
    return _LEVEL_URGENCY.get(level, "info")


# Urgency day-thresholds — urgency sharpens once a real due_at exists.
_URGENCY_DUE_DAYS = 1  # 0..1 days out → "due"
_URGENCY_SOON_DAYS = 7  # 2..7 days out → "soon"; beyond → "info"


def _urgency_from_due_at(due_at: Date | None, level: str, now: datetime) -> str:
    """Coarse human-scale urgency. With a real ``due_at`` it's a function of
    (due_at − now): past → overdue, today/tomorrow → due, within a week → soon,
    further → info. Date-less items fall back to the ``level`` alias so
    nothing regresses. Reference date is ``now``'s UTC date (matches emit)."""
    if due_at is None:
        return _urgency_for(level)
    days_until = (due_at - now.astimezone(UTC).date()).days
    if days_until < 0:
        return "overdue"
    if days_until <= _URGENCY_DUE_DAYS:
        return "due"
    if days_until <= _URGENCY_SOON_DAYS:
        return "soon"
    return "info"


def _dedup_key(
    worker: str, title: str, capability_key: str | None, focus: str | None, source_id: str | None
) -> str:
    # ``detail`` excluded (stable as a signal escalates). ``source_id`` folded in
    # so two concurrent same-title instances (two pay cycles) get distinct keys,
    # while the same instance keeps its key across cycles/escalation.
    return str(uuid5(_SIGNAL_NS, f"{worker}|{title}|{capability_key}|{focus}|{source_id}"))


@dataclass(frozen=True)
class Signal:
    worker: str
    kind: str
    title: str
    detail: str
    level: str  # carried verbatim from NeedsItem; the authoritative sort/severity key
    urgency: str  # coarse human-scale alias of level (info/soon/due) until due_at lands
    capability_key: str | None
    focus: str | None
    dedup_key: str
    emitted_at: datetime
    due_at: Date | None = None  # None when no structured deadline is plumbed
    state: str = "open"  # only open signals are built here
    source_ref: str | None = None
    source_id: str | None = None  # stable per-instance business id

    def to_wire(self) -> dict:
        return {
            "worker": self.worker,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "urgency": self.urgency,
            "level": self.level,
            "capability_key": self.capability_key,
            "focus": self.focus,
            "dedup_key": self.dedup_key,
            "state": self.state,
            "source_ref": self.source_ref,
            "source_id": self.source_id,
            "emitted_at": self.emitted_at.isoformat(),
        }

    @classmethod
    def from_wire(cls, d: dict) -> Signal:
        """Reconstruct a Signal from a ``to_wire()`` dict.

        Tolerant of slightly-old/partial wire lines: ``state``, ``source_ref``,
        ``source_id``, ``focus``, and ``capability_key`` are optional and
        default to safe values so old messages still parse cleanly.
        """
        return cls(
            worker=d["worker"],
            kind=d["kind"],
            title=d["title"],
            detail=d["detail"],
            level=d["level"],
            urgency=d["urgency"],
            capability_key=d.get("capability_key"),
            focus=d.get("focus"),
            dedup_key=d["dedup_key"],
            emitted_at=datetime.fromisoformat(d["emitted_at"]),
            due_at=Date.fromisoformat(d["due_at"]) if d.get("due_at") else None,
            state=d.get("state", "open"),
            source_ref=d.get("source_ref"),
            source_id=d.get("source_id"),
        )


def build_signals(
    needs: tuple[NeedsItem, ...],
    *,
    now: datetime,
    worker: str = "xbook",
    source_ref: str | None = None,
) -> tuple[Signal, ...]:
    """Map a (severity-sorted, capped) NeedsItem tuple to Signals, 1:1, order
    preserved. Pure: no filtering, no re-sort, no dedup, no I/O — emit exactly
    the set the cockpit shows (anti-fatigue discipline inherited free)."""
    return tuple(
        Signal(
            worker=worker,
            kind=_kind_for(n.title),
            title=n.title,
            detail=n.detail,
            level=n.level,
            urgency=_urgency_from_due_at(n.due_at, n.level, now),
            capability_key=n.capability_key,
            focus=n.focus,
            dedup_key=_dedup_key(worker, n.title, n.capability_key, n.focus, n.source_id),
            emitted_at=now,
            due_at=n.due_at,
            source_ref=source_ref,
            source_id=n.source_id,
        )
        for n in needs
    )
