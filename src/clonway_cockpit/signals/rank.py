"""Central anti-fatigue ranking for the fleet — the single home of the
'severity sort + global cap' discipline every consumer (fleet cockpit, briefing)
shares, so no worker can flood the operator and ranking is identical everywhere."""

from __future__ import annotations

from datetime import date as Date  # noqa: F401 — re-exported for forward-compat
from datetime import datetime

from clonway_cockpit.signals.model import Signal

FLEET_NEEDS_CAP = 6  # the global cap the bridge shows ("N · soonest first")

_URGENCY_RANK = {"overdue": 0, "due": 1, "soon": 2, "info": 3}
_LEVEL_RANK = {"error": 0, "warn": 1, "ok": 2}


def _sort_key(s: Signal, *, now: datetime) -> tuple:
    # urgency first (overdue→info), then soonest due_at (None last), then level
    # (error→ok), then worker+title for deterministic stability.
    due_ord = s.due_at.toordinal() if s.due_at is not None else 10**9
    return (
        _URGENCY_RANK.get(s.urgency, 99),
        due_ord,
        _LEVEL_RANK.get(s.level, 99),
        s.worker,
        s.title,
    )


def rank_and_cap(signals, *, cap: int = FLEET_NEEDS_CAP, now: datetime) -> tuple[Signal, ...]:
    """Severity-sort the cross-worker union and take the top ``cap``. Pure; no I/O.

    The cap is GLOBAL (across workers) so the most-urgent items win regardless of
    which worker emitted them — a single noisy worker cannot crowd out a more
    urgent signal from another (the no-flood contract).
    """
    ranked = sorted(signals, key=lambda s: _sort_key(s, now=now))
    return tuple(ranked[:cap])
