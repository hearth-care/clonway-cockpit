# tests/test_signal_emit.py
"""CC-SIG-EMIT-* — shared emit helper tests.

Mirrors the four workers' own emit tests (xbook / xhr / xletter / xquill) so a
migrated worker is byte-identical on the wire. The GCS client is injected via
``storage_client_factory`` — no network, no google-cloud-storage dependency.
The flag is read from the real environment (``monkeypatch.setenv``) exactly as a
worker reads it in production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date

import pytest

from clonway_cockpit.signals.emit import emit_signals, flag_enabled
from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
_TODAY = Date(2026, 5, 25)


# ---- fakes -----------------------------------------------------------------


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
    """Records the project it was constructed with; routes blobs to a dict."""

    def __init__(self, project: object = None) -> None:
        self.project = project
        self._store: dict[str, str] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


class _BoomClient:
    """A client whose bucket() raises — simulates a GCS outage."""

    def __init__(self, project: object = None) -> None:
        pass

    def bucket(self, name: str) -> _FakeBucket:
        raise RuntimeError("simulated GCS failure")


def _signal(*, title: str = "Bills due this week", source_id: str | None = "bill-42") -> Signal:
    need = NeedsItem(
        title, "3 bills due by Friday", "warn", "schedule-bills", "overdue", None, source_id
    )
    return build_signals((need,), now=_NOW, worker="xbook")[0]


def _build_one(*, today: Date | None = None, now: datetime | None = None) -> tuple[Signal, ...]:
    return (_signal(),)


def _build_empty(*, today: Date | None = None, now: datetime | None = None) -> tuple[Signal, ...]:
    return ()


def _enable(monkeypatch, flag: str) -> None:
    monkeypatch.setenv(flag, "1")


# ---- flag_enabled ----------------------------------------------------------


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on", " on ", "On"])
def test_flag_enabled_truthy(monkeypatch, val):  # CC-SIG-EMIT-FLAG-1
    monkeypatch.setenv("X_EMIT_SIGNALS", val)
    assert flag_enabled("X_EMIT_SIGNALS") is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "nope", "2", "y"])
def test_flag_enabled_falsey(monkeypatch, val):  # CC-SIG-EMIT-FLAG-2
    monkeypatch.setenv("X_EMIT_SIGNALS", val)
    assert flag_enabled("X_EMIT_SIGNALS") is False


def test_flag_enabled_default_off(monkeypatch):  # CC-SIG-EMIT-FLAG-3
    monkeypatch.delenv("X_EMIT_SIGNALS", raising=False)
    assert flag_enabled("X_EMIT_SIGNALS") is False


# ---- emit_signals: flag gating ---------------------------------------------


def test_emit_disabled_returns_empty_no_write(monkeypatch):  # CC-SIG-EMIT-1
    monkeypatch.delenv("XHR_EMIT_SIGNALS", raising=False)
    calls: list[str] = []

    def factory():
        calls.append("constructed")
        return _FakeClient()

    def build(*, today=None, now=None):
        calls.append("built")
        return _build_one()

    out = emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=build,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=factory,
    )
    assert out == ()
    # Flag-gated up front: build never called, no client constructed, no write.
    assert calls == []


# ---- emit_signals: latest snapshot -----------------------------------------


def test_emit_writes_latest_at_right_path(monkeypatch):  # CC-SIG-EMIT-2
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")
    client = _FakeClient()
    out = emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        run_id="exec-123",
        storage_client_factory=lambda: client,
    )
    assert len(out) == 1
    store = client._store
    assert "signals/xhr/latest.jsonl" in store
    line = store["signals/xhr/latest.jsonl"]
    # NDJSON: one compact line per signal, trailing newline.
    assert line.endswith("\n")
    assert line.count("\n") == 1
    # Compact separators (byte-identical to the workers' own emit).
    assert ", " not in line and '": ' not in line


def test_emit_writes_dated_archive_when_non_empty(monkeypatch):  # CC-SIG-EMIT-3
    _enable(monkeypatch, "XLETTER_EMIT_SIGNALS")
    client = _FakeClient()
    emit_signals(
        worker_id="xletter",
        flag_env="XLETTER_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        run_id="exec-abc",
        storage_client_factory=lambda: client,
    )
    store = client._store
    assert "signals/xletter/latest.jsonl" in store
    assert "signals/xletter/2026-05-25/exec-abc.jsonl" in store
    # latest and dated archive carry identical bodies.
    assert (
        store["signals/xletter/latest.jsonl"] == store["signals/xletter/2026-05-25/exec-abc.jsonl"]
    )


def test_emit_overwrites_latest_even_when_empty(monkeypatch):  # CC-SIG-EMIT-4
    _enable(monkeypatch, "XBOOK_EMIT_SIGNALS")
    client = _FakeClient()
    out = emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=_build_empty,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: client,
    )
    assert out == ()
    store = client._store
    # latest is written (empty body) so a now-quiet worker clears its old set...
    assert store["signals/xbook/latest.jsonl"] == ""
    # ...but no dated archive is written for an empty set.
    assert not any(k.startswith("signals/xbook/2026-05-25/") for k in store)


# ---- emit_signals: best-effort degrade -------------------------------------


def test_emit_swallows_gcs_error_returns_built(monkeypatch):  # CC-SIG-EMIT-5
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")
    out = emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: _BoomClient(),
    )
    # The build result is still returned (scan still "saw" them); the GCS write
    # degraded silently — never raises.
    assert len(out) == 1


def test_emit_swallows_build_error_returns_empty(monkeypatch):  # CC-SIG-EMIT-6
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")

    def _build_boom(*, today=None, now=None):
        raise ValueError("build blew up")

    out = emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=_build_boom,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: _FakeClient(),
    )
    assert out == ()


# ---- emit_signals: project + run_id resolution -----------------------------


def test_default_factory_threads_project(monkeypatch):  # CC-SIG-EMIT-7
    _enable(monkeypatch, "XQUILL_EMIT_SIGNALS")
    import clonway_cockpit.signals.emit as emit_mod

    captured: dict[str, object] = {}

    class _StorageStub:
        @staticmethod
        def Client(project=None):  # noqa: N802 — mirrors google.cloud.storage.Client
            captured["project"] = project
            return _FakeClient(project=project)

    monkeypatch.setattr(emit_mod, "_import_storage", lambda: _StorageStub)
    emit_signals(
        worker_id="xquill",
        flag_env="XQUILL_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        project="clonway-care-bookkeeper",
    )
    # xquill's launchd-env requirement: explicit project= threads through.
    assert captured["project"] == "clonway-care-bookkeeper"


def test_default_factory_no_project(monkeypatch):  # CC-SIG-EMIT-8
    _enable(monkeypatch, "XBOOK_EMIT_SIGNALS")
    import clonway_cockpit.signals.emit as emit_mod

    captured: dict[str, object] = {"project": "<unset>"}

    class _StorageStub:
        @staticmethod
        def Client(project=None):  # noqa: N802
            captured["project"] = project
            return _FakeClient(project=project)

    monkeypatch.setattr(emit_mod, "_import_storage", lambda: _StorageStub)
    emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
    )
    # Bare storage.Client() — project None for non-xquill workers.
    assert captured["project"] is None


def test_run_id_from_cloud_run_execution_env(monkeypatch):  # CC-SIG-EMIT-9
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "fpo-exec-77")
    client = _FakeClient()
    emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: client,
    )
    assert "signals/xhr/2026-05-25/fpo-exec-77.jsonl" in client._store


def test_run_id_uuid_fallback(monkeypatch):  # CC-SIG-EMIT-10
    _enable(monkeypatch, "XQUILL_EMIT_SIGNALS")
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    emit_signals(
        worker_id="xquill",
        flag_env="XQUILL_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: client,
    )
    dated = [k for k in client._store if k.startswith("signals/xquill/2026-05-25/")]
    assert len(dated) == 1
    # The fallback is a 32-char hex uuid, not a literal "None".
    fname = dated[0].rsplit("/", 1)[1].removesuffix(".jsonl")
    assert fname != "None" and len(fname) == 32


def test_explicit_run_id_beats_env(monkeypatch):  # CC-SIG-EMIT-11
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "env-exec")
    client = _FakeClient()
    emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=_build_one,
        now=_NOW,
        today=_TODAY,
        run_id="explicit-exec",
        storage_client_factory=lambda: client,
    )
    assert "signals/xhr/2026-05-25/explicit-exec.jsonl" in client._store
    assert "signals/xhr/2026-05-25/env-exec.jsonl" not in client._store


def test_build_receives_today_and_now(monkeypatch):  # CC-SIG-EMIT-12
    _enable(monkeypatch, "XHR_EMIT_SIGNALS")
    seen: dict[str, object] = {}

    def build(*, today=None, now=None):
        seen["today"] = today
        seen["now"] = now
        return ()

    emit_signals(
        worker_id="xhr",
        flag_env="XHR_EMIT_SIGNALS",
        build=build,
        now=_NOW,
        today=_TODAY,
        storage_client_factory=lambda: _FakeClient(),
    )
    assert seen["today"] == _TODAY
    assert seen["now"] == _NOW
