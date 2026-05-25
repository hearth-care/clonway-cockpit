# tests/test_signal_horizon.py
"""CC-SIG-HORIZON-* — the shared forward-scan contract (Mechanism 2).

A worker's proactive forward-scan is the canonical ``(*, today, now) ->
Sequence[Signal]`` shape that ``emit_signals(build=...)`` already consumes.
These tests pin the shared abstraction: the ``ScanHorizon`` protocol, the
``compose_horizon`` composer, and the ``scan_horizon`` marker. The abstraction
is additive — existing ``build_*_signals`` keep working untouched; this is the
shape they (and the future C6 template) can adopt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date

from clonway_cockpit.signals.emit import emit_signals
from clonway_cockpit.signals.horizon import (
    ScanHorizon,
    compose_horizon,
    is_scan_horizon,
    scan_horizon,
)
from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
_TODAY = Date(2026, 5, 25)


def _signal(*, title: str, source_id: str) -> Signal:
    need = NeedsItem(title, "detail", "warn", "schedule-bills", "overdue", None, source_id)
    return build_signals((need,), now=_NOW, worker="xbook")[0]


def _scanner_a(*, today: Date, now: datetime) -> tuple[Signal, ...]:
    return (_signal(title="Insurance renewal due", source_id="ins-1"),)


def _scanner_b(*, today: Date, now: datetime) -> tuple[Signal, ...]:
    return (
        _signal(title="Compliance filing due", source_id="cqc-1"),
        _signal(title="Compliance filing due", source_id="cqc-2"),
    )


def _scanner_empty(*, today: Date, now: datetime) -> tuple[Signal, ...]:
    return ()


# ---- ScanHorizon protocol --------------------------------------------------


def test_scan_horizon_protocol_accepts_worker_shape() -> None:  # CC-SIG-HORIZON-1
    # A (*, today, now) -> Sequence[Signal] function satisfies the protocol.
    scan: ScanHorizon = _scanner_a
    out = scan(today=_TODAY, now=_NOW)
    assert len(out) == 1
    assert out[0].title == "Insurance renewal due"


def test_scan_horizon_protocol_is_runtime_checkable() -> None:  # CC-SIG-HORIZON-2
    # The protocol is runtime_checkable so a lint/template can assert membership.
    assert isinstance(_scanner_a, ScanHorizon)
    assert isinstance(compose_horizon(_scanner_a), ScanHorizon)


# ---- compose_horizon -------------------------------------------------------


def test_compose_concatenates_in_order() -> None:  # CC-SIG-HORIZON-3
    build = compose_horizon(_scanner_a, _scanner_b)
    out = build(today=_TODAY, now=_NOW)
    titles = [s.title for s in out]
    # scanner_a's items come first, then scanner_b's — stable, no re-sort.
    assert titles == ["Insurance renewal due", "Compliance filing due", "Compliance filing due"]
    # source order preserved within a scanner too.
    assert [s.source_id for s in out] == ["ins-1", "cqc-1", "cqc-2"]


def test_compose_single_scanner_is_passthrough() -> None:  # CC-SIG-HORIZON-4
    build = compose_horizon(_scanner_b)
    out = build(today=_TODAY, now=_NOW)
    assert tuple(out) == _scanner_b(today=_TODAY, now=_NOW)


def test_compose_no_scanners_is_empty() -> None:  # CC-SIG-HORIZON-5
    build = compose_horizon()
    assert build(today=_TODAY, now=_NOW) == ()


def test_compose_all_empty_scanners_is_empty() -> None:  # CC-SIG-HORIZON-6
    build = compose_horizon(_scanner_empty, _scanner_empty)
    assert build(today=_TODAY, now=_NOW) == ()


def test_compose_skips_empty_keeps_non_empty() -> None:  # CC-SIG-HORIZON-7
    build = compose_horizon(_scanner_empty, _scanner_a, _scanner_empty)
    out = build(today=_TODAY, now=_NOW)
    assert [s.title for s in out] == ["Insurance renewal due"]


def test_compose_returns_tuple() -> None:  # CC-SIG-HORIZON-8
    build = compose_horizon(_scanner_a, _scanner_b)
    assert isinstance(build(today=_TODAY, now=_NOW), tuple)


def test_compose_result_satisfies_protocol() -> None:  # CC-SIG-HORIZON-9
    build: ScanHorizon = compose_horizon(_scanner_a)
    assert build(today=_TODAY, now=_NOW)[0].title == "Insurance renewal due"


# ---- compose_horizon feeds emit_signals (the real consumer) -----------------


def test_composed_build_drives_emit_signals(monkeypatch) -> None:  # CC-SIG-HORIZON-10
    # The whole point: a composed horizon IS the build= callable emit consumes.
    monkeypatch.setenv("XBOOK_EMIT_SIGNALS", "1")

    class _FakeBlob:
        def __init__(self, store, name):
            self._store, self._name = store, name

        def upload_from_string(self, body, content_type=None):
            self._store[self._name] = body

    class _FakeBucket:
        def __init__(self, store):
            self._store = store

        def blob(self, name):
            return _FakeBlob(self._store, name)

    class _FakeClient:
        def __init__(self):
            self._store = {}

        def bucket(self, name):
            return _FakeBucket(self._store)

    client = _FakeClient()
    out = emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=compose_horizon(_scanner_a, _scanner_b),
        now=_NOW,
        today=_TODAY,
        run_id="exec-h",
        storage_client_factory=lambda: client,
    )
    assert [s.title for s in out] == [
        "Insurance renewal due",
        "Compliance filing due",
        "Compliance filing due",
    ]
    assert client._store["signals/xbook/latest.jsonl"].count("\n") == 3


# ---- scan_horizon marker ---------------------------------------------------


def test_scan_horizon_marker_tags_function() -> None:  # CC-SIG-HORIZON-11
    @scan_horizon
    def my_scan(*, today: Date, now: datetime) -> tuple[Signal, ...]:
        return ()

    assert is_scan_horizon(my_scan) is True


def test_scan_horizon_marker_is_transparent() -> None:  # CC-SIG-HORIZON-12
    # The decorator returns the function unchanged — same identity, callable.
    def raw(*, today: Date, now: datetime) -> tuple[Signal, ...]:
        return (_signal(title="Insurance renewal due", source_id="ins-1"),)

    decorated = scan_horizon(raw)
    assert decorated is raw
    assert decorated(today=_TODAY, now=_NOW)[0].title == "Insurance renewal due"


def test_unmarked_function_is_not_scan_horizon() -> None:  # CC-SIG-HORIZON-13
    assert is_scan_horizon(_scanner_a) is False
    assert is_scan_horizon(lambda: None) is False


def test_marked_scanner_still_composes() -> None:  # CC-SIG-HORIZON-14
    @scan_horizon
    def marked(*, today: Date, now: datetime) -> tuple[Signal, ...]:
        return (_signal(title="Insurance renewal due", source_id="ins-1"),)

    build = compose_horizon(marked, _scanner_b)
    assert [s.title for s in build(today=_TODAY, now=_NOW)] == [
        "Insurance renewal due",
        "Compliance filing due",
        "Compliance filing due",
    ]
