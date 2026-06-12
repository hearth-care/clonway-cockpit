from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime
from datetime import date as Date

import pytest

from clonway_cockpit.signals.model import build_signals
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
_TODAY = Date(2026, 5, 25)


class _FakeBlob:
    def __init__(self, store: dict[str, str], name: str) -> None:
        self._store = store
        self._name = name

    def upload_from_string(self, body: str, content_type: str | None = None) -> None:
        self._store[self._name] = body


class _FakeBucket:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self.store)


def _need(
    *,
    title: str = "Bills due this week",
    detail: str = "3 bills due by Friday",
    level: str = "warn",
    capability_key: str | None = "schedule-bills",
    focus: str | None = "overdue",
    due_at: Date | None = None,
    source_id: str | None = "bill-42",
) -> NeedsItem:
    return NeedsItem(title, detail, level, capability_key, focus, due_at, source_id)


def test_factory_from_needs_is_wire_identical_to_explicit_build_signals() -> None:
    from clonway_cockpit.signals.factory import SignalFactory

    needs = (
        _need(),
        _need(
            title="DRAFT bills need approval",
            detail="2 drafts",
            level="error",
            capability_key=None,
            focus=None,
            source_id=None,
        ),
    )
    factory = SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS")

    assert [s.to_wire() for s in factory.from_needs(needs, now=_NOW, source_ref="runbook")] == [
        s.to_wire() for s in build_signals(needs, now=_NOW, worker="xhr", source_ref="runbook")
    ]


def test_factory_make_seals_worker_emitted_at_and_dedup_key() -> None:
    from clonway_cockpit.signals.factory import SignalFactory

    factory = SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS")

    signature = inspect.signature(factory.make)
    assert "worker" not in signature.parameters
    assert "emitted_at" not in signature.parameters
    assert "dedup_key" not in signature.parameters

    signal = factory.make(
        title="Bills due this week",
        detail="3 bills due by Friday",
        level="warn",
        capability_key="schedule-bills",
        focus="overdue",
        source_id="bill-42",
        now=_NOW,
    )
    assert signal.worker == "xhr"
    assert signal.emitted_at == _NOW
    assert signal.dedup_key == build_signals((_need(),), now=_NOW, worker="xhr")[0].dedup_key

    for sealed_kw in ("worker", "emitted_at", "dedup_key"):
        with pytest.raises(TypeError):
            factory.make(
                title="Bills due this week",
                detail="3 bills due by Friday",
                level="warn",
                now=_NOW,
                **{sealed_kw: "caller-value"},
            )


def test_factory_emit_rejects_foreign_worker_signal(monkeypatch, caplog) -> None:
    from clonway_cockpit.signals.factory import SignalFactory, SignalIdentityError

    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")
    factory = SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS")
    client = _FakeClient()
    foreign = build_signals((_need(),), now=_NOW, worker="xbook")[0]

    out = factory.emit(
        build=lambda **_: (foreign,),
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: client,
    )

    assert out == ()
    assert client.store == {}
    assert any(
        record.exc_info and record.exc_info[0] is SignalIdentityError for record in caplog.records
    )


def test_factory_kind_resolution_order_and_explicit_validation() -> None:
    from clonway_cockpit.signals.factory import SignalFactory

    factory = SignalFactory(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        title_kinds={
            "Bills due this week": "approval.pending",
            "DBS expiring": "credential.expiring",
        },
    )

    assert (
        factory.make(title="DBS expiring", detail="Alice", level="warn", now=_NOW).kind
        == "credential.expiring"
    )
    assert (
        factory.make(
            title="Bills due this week", detail="Override legacy", level="warn", now=_NOW
        ).kind
        == "approval.pending"
    )
    assert (
        factory.make(
            title="DBS expiring",
            detail="Alice",
            level="warn",
            kind="deadline.approaching",
            now=_NOW,
        ).kind
        == "deadline.approaching"
    )
    with pytest.raises(ValueError, match="unknown signal kind"):
        factory.make(title="DBS expiring", detail="Alice", level="warn", kind="bad.kind", now=_NOW)


def test_unknown_title_warns_once_and_falls_back(caplog) -> None:
    from clonway_cockpit.signals.factory import SignalFactory

    caplog.set_level(logging.WARNING, logger="xhr.signals")
    factory = SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS")

    first = factory.make(title="DBS expiring", detail="Alice", level="warn", now=_NOW)
    second = factory.make(title="DBS expiring", detail="Bob", level="warn", now=_NOW)

    assert first.kind == "action.required"
    assert second.kind == "action.required"
    warnings = [r for r in caplog.records if "unknown signal title" in r.getMessage()]
    assert len(warnings) == 1


def test_unknown_title_strict_mode_raises(monkeypatch) -> None:
    from clonway_cockpit.signals.factory import SignalFactory, UnknownSignalTitle

    with pytest.raises(UnknownSignalTitle):
        SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS", strict_kinds=True).make(
            title="DBS expiring", detail="Alice", level="warn", now=_NOW
        )

    monkeypatch.setenv("CLONWAY_SIGNALS_STRICT_KINDS", "1")
    with pytest.raises(UnknownSignalTitle):
        SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS").make(
            title="DBS expiring", detail="Alice", level="warn", now=_NOW
        )


def test_factory_emit_logs_unknown_title_count(monkeypatch, caplog) -> None:
    from clonway_cockpit.signals.factory import SignalFactory

    monkeypatch.setenv("XHR_EMIT_SIGNALS", "1")
    caplog.set_level(logging.INFO, logger="xhr.signals")
    factory = SignalFactory(worker_id="xhr", flag_env="XHR_EMIT_SIGNALS")
    client = _FakeClient()

    out = factory.emit(
        build=lambda **_: (
            factory.make(title="DBS expiring", detail="Alice", level="warn", now=_NOW),
            factory.make(title="Bills due this week", detail="3 bills", level="warn", now=_NOW),
        ),
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: client,
    )

    assert len(out) == 2
    assert any("unknown_title_kinds=1" in record.getMessage() for record in caplog.records)
