# tests/test_signal_wire.py
"""CC-SIG-WIRE-* — Signal.from_wire round-trip tests."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date

from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)


def _make_signal(*, due_at: Date | None = None, source_id: str | None = None) -> Signal:
    need = NeedsItem(
        "Bills due this week",
        "3 bills due by Friday",
        "warn",
        "schedule-bills",
        "overdue",
        due_at,
        source_id,
    )
    return build_signals((need,), now=_NOW, worker="xbook")[0]


# CC-SIG-WIRE-1: round-trips a Signal with a real due_at and tz-aware emitted_at
def test_from_wire_round_trip_with_due_at():  # CC-SIG-WIRE-1
    s = _make_signal(due_at=Date(2026, 5, 29), source_id="bill-42")
    assert Signal.from_wire(s.to_wire()) == s


# CC-SIG-WIRE-2: due_at=None round-trips correctly (wire due_at is None → back to None)
def test_from_wire_round_trip_no_due_at():  # CC-SIG-WIRE-2
    s = _make_signal(due_at=None)
    wire = s.to_wire()
    assert wire["due_at"] is None
    assert Signal.from_wire(wire) == s


# CC-SIG-WIRE-3: tolerant parse — a dict missing source_id/state still parses with defaults
def test_from_wire_tolerant_missing_optional_fields():  # CC-SIG-WIRE-3
    s = _make_signal(due_at=Date(2026, 5, 30))
    wire = s.to_wire()
    # Simulate a slightly-old wire line that lacks these keys
    wire.pop("source_id")
    wire.pop("state")
    result = Signal.from_wire(wire)
    assert result.source_id is None
    assert result.state == "open"
    # Other fields intact
    assert result.title == s.title
    assert result.due_at == s.due_at
    assert result.emitted_at == s.emitted_at
