# tests/test_signal_rank.py
"""CC-RANK-* — rank_and_cap anti-fatigue tests."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date

from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.signals.rank import rank_and_cap
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)


def _sig(
    *,
    title: str,
    urgency: str,
    level: str = "warn",
    due_at: Date | None = None,
    worker: str = "xbook",
) -> Signal:
    """Build a Signal directly via build_signals for a one-need tuple."""
    # Map urgency back to a level and due_at that will produce the desired urgency.
    # Easier: build the Signal manually with known field values.
    need = NeedsItem(title, "detail", level, "schedule-bills", None, due_at, None)
    sigs = build_signals((need,), now=_NOW, worker=worker)
    # Override urgency post-hoc is not possible on a frozen dataclass, so we
    # instead use due_at to drive the urgency naturally where it matters.
    # For this test file we rely on due_at to produce the right urgency value,
    # or we build raw Signal objects when we need precise control.
    return sigs[0]


def _raw_sig(
    *,
    title: str,
    urgency: str,
    level: str = "warn",
    due_at: Date | None = None,
    worker: str = "xbook",
) -> Signal:
    """Build a raw Signal with exact urgency (bypasses build_signals urgency calc)."""
    return Signal(
        worker=worker,
        kind="action.required",
        title=title,
        detail="detail",
        level=level,
        urgency=urgency,
        capability_key=None,
        focus=None,
        dedup_key=f"{worker}|{title}",
        emitted_at=_NOW,
        due_at=due_at,
        state="open",
        source_ref=None,
        source_id=None,
    )


# CC-RANK-1: scrambled union of ≥2 workers → rank_and_cap returns urgency→due_at→level order
def test_rank_and_cap_ordering():  # CC-RANK-1
    signals = [
        _raw_sig(title="C info xbook", urgency="info", level="ok", worker="xbook"),
        _raw_sig(
            title="A overdue xhr",
            urgency="overdue",
            level="error",
            due_at=Date(2026, 5, 20),
            worker="xhr",
        ),
        _raw_sig(
            title="D soon warn",
            urgency="soon",
            level="warn",
            due_at=Date(2026, 5, 28),
            worker="xbook",
        ),
        _raw_sig(
            title="B due error",
            urgency="due",
            level="error",
            due_at=Date(2026, 5, 25),
            worker="xhr",
        ),
        _raw_sig(
            title="E soon ok", urgency="soon", level="ok", due_at=Date(2026, 5, 28), worker="xbook"
        ),
        _raw_sig(title="F info warn", urgency="info", level="warn", worker="xbook"),
    ]
    result = rank_and_cap(signals, cap=10, now=_NOW)
    titles = [s.title for s in result]
    # Expected order:
    # 1) overdue → A overdue xhr (due_at 2026-05-20, error)
    # 2) due    → B due error (due_at 2026-05-25, error)
    # 3) soon   → D soon warn (due_at 2026-05-28, warn) before E soon ok (same due_at, warn < ok)
    # 4) soon   → E soon ok
    # 5) info   → C info xbook (no due_at, ok) — level ok=2 vs F's warn=1 so F before C
    # 6) info   → F info warn (no due_at, warn)
    # Actually: None due_at → ord 10^9; level: error=0, warn=1, ok=2.
    # F (info, warn, None) → (3, 10^9, 1, "xbook", "F info warn")
    # C (info, ok, None)   → (3, 10^9, 2, "xbook", "C info xbook")
    # So F before C for info tier.
    assert titles == [
        "A overdue xhr",
        "B due error",
        "D soon warn",
        "E soon ok",
        "F info warn",
        "C info xbook",
    ]


# CC-RANK-CAP-1: 12 signals → len(rank_and_cap(..., cap=6)) == 6 and the 6 are highest severity
def test_rank_and_cap_respects_cap():  # CC-RANK-CAP-1
    # 4 overdue (highest) + 4 due + 4 info (lowest)
    overdue = [
        _raw_sig(
            title=f"OV-{i}",
            urgency="overdue",
            level="error",
            due_at=Date(2026, 5, 20),
            worker="xbook",
        )
        for i in range(4)
    ]
    due = [
        _raw_sig(
            title=f"DU-{i}", urgency="due", level="warn", due_at=Date(2026, 5, 25), worker="xbook"
        )
        for i in range(4)
    ]
    info = [_raw_sig(title=f"IN-{i}", urgency="info", level="ok", worker="xbook") for i in range(4)]
    signals = info + due + overdue  # deliberately scrambled
    result = rank_and_cap(signals, cap=6, now=_NOW)
    assert len(result) == 6
    # All 4 overdue must be in the result, plus the first 2 due (by title alpha)
    result_titles = {s.title for s in result}
    for s in overdue:
        assert s.title in result_titles
    # None of the info signals should be present
    for s in info:
        assert s.title not in result_titles


# CC-RANK-NOFLOOD-1: 50 info signals from "xbook" + 1 overdue from "xhr" → xhr overdue wins a cap=6 slot
def test_rank_and_cap_no_flood():  # CC-RANK-NOFLOOD-1
    noisy = [
        _raw_sig(title=f"noise-{i}", urgency="info", level="ok", worker="xbook") for i in range(50)
    ]
    urgent = _raw_sig(
        title="xhr-overdue",
        urgency="overdue",
        level="error",
        due_at=Date(2026, 5, 20),
        worker="xhr",
    )
    signals = noisy + [urgent]
    result = rank_and_cap(signals, cap=6, now=_NOW)
    result_titles = [s.title for s in result]
    assert "xhr-overdue" in result_titles, (
        "overdue signal from xhr must not be drowned by 50 xbook info signals"
    )
    assert len(result) == 6
