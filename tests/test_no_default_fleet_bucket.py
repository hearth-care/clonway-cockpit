"""No built-in fleet bucket: every writer takes it from its caller or CLONWAY_FLEET_BUCKET.

Covers the shared rule in ``clonway_cockpit.fleet_bucket`` for the three modules that used
to carry a bucket name (signal emit/subscribe/bridge, telemetry, audit log) and a source
scan that keeps any bucket literal out of ``src/`` and ``worker-template/``.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clonway_cockpit import fleet_bucket
from clonway_cockpit.audit_log import AuditEvent, make_audit_sink
from clonway_cockpit.fleet_bucket import FLEET_BUCKET_ENV, FleetStorageOutcome
from clonway_cockpit.obs import flush_buffer
from clonway_cockpit.obs._telemetry import flush_buffer_outcome, last_flush_outcome, make_obs
from clonway_cockpit.signals.bridge import failure_to_signal
from clonway_cockpit.signals.emit import emit_signals
from clonway_cockpit.signals.model import Signal
from clonway_cockpit.signals.subscribe import (
    FileCursorStore,
    GcsCursorStore,
    Subscription,
    poll,
)

_NOW = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
_EXPLICIT = "example-fleet-bucket"
_FROM_ENV = "example-env-bucket"
_UNCONFIGURED_LINE = "no fleet bucket configured: reminders are not being published"
_SECRET = "SECRET-BODY-CONTENT"


class NotFound(Exception):  # matched by name, as the real google error is
    pass


class _Blob:
    def __init__(self, store: dict, bucket: str, name: str, fail: Exception | None) -> None:
        self._store, self._bucket, self._name, self._fail = store, bucket, name, fail
        self.generation = None

    def upload_from_string(self, body: str, content_type: str | None = None, **_: object) -> None:
        if self._fail:
            raise self._fail
        self._store[(self._bucket, self._name)] = body

    def download_as_text(self) -> str:
        if self._fail:
            raise self._fail
        try:
            return self._store[(self._bucket, self._name)]
        except KeyError:
            raise NotFound(self._name) from None


class _Bucket:
    def __init__(self, store: dict, name: str, fail: Exception | None) -> None:
        self._store, self._name, self._fail = store, name, fail

    def blob(self, name: str) -> _Blob:
        return _Blob(self._store, self._name, name, self._fail)

    def list_blobs(self, **_: object) -> list:
        if self._fail:
            raise self._fail
        return []


class _Client:
    def __init__(self, fail: Exception | None = None) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self._fail = fail

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self.store, name, self._fail)


@pytest.fixture(autouse=True)
def _fresh_notice() -> None:
    fleet_bucket._reset_notices_for_tests()


def _signal() -> Signal:
    return Signal(
        worker="demo",
        kind="action.required",
        title="t",
        detail=_SECRET,
        level="warn",
        urgency="soon",
        capability_key=None,
        focus=None,
        dedup_key="k",
        emitted_at=_NOW,
    )


def _emit(client: _Client, **kw):
    return emit_signals(
        worker_id="demo",
        flag_env="DEMO_EMIT",
        build=lambda **_: (_signal(),),
        now=_NOW,
        storage_client_factory=lambda: client,
        **kw,
    )


def _info_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.getMessage() == _UNCONFIGURED_LINE
    ]


def _warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.fixture
def flag(monkeypatch):
    monkeypatch.setenv("DEMO_EMIT", "1")


# ---- resolution rule -------------------------------------------------------


def test_resolve_prefers_argument_then_env_then_none(monkeypatch):
    assert fleet_bucket.resolve_fleet_bucket() is None
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    assert fleet_bucket.resolve_fleet_bucket() == _FROM_ENV
    assert fleet_bucket.resolve_fleet_bucket(_EXPLICIT) == _EXPLICIT
    assert fleet_bucket.resolve_fleet_bucket("  ") == _FROM_ENV


# ---- signals: emit ----------------------------------------------------------


def test_emit_writes_to_explicit_bucket(flag):
    client = _Client()
    out = _emit(client, bucket=_EXPLICIT)
    assert out.outcome is FleetStorageOutcome.OK
    assert {b for b, _ in client.store} == {_EXPLICIT}
    assert len(out) == 1


def test_emit_writes_to_env_bucket(flag, monkeypatch):
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    client = _Client()
    out = _emit(client)
    assert out.outcome is FleetStorageOutcome.OK
    assert {b for b, _ in client.store} == {_FROM_ENV}


def test_emit_unconfigured_writes_nothing_and_says_so_once(flag, caplog):
    client = _Client()
    with caplog.at_level(logging.INFO):
        first = _emit(client)
        second = _emit(client)
    assert client.store == {}
    assert first.outcome is FleetStorageOutcome.NOT_CONFIGURED
    assert second.outcome is FleetStorageOutcome.NOT_CONFIGURED
    assert len(first) == 1  # the built signals are still returned
    assert len(_info_lines(caplog)) == 1


def test_emit_flag_off_reports_disabled(monkeypatch):
    monkeypatch.delenv("DEMO_EMIT", raising=False)
    out = _emit(_Client(), bucket=_EXPLICIT)
    assert out == ()
    assert out.outcome is FleetStorageOutcome.DISABLED


def test_emit_failed_upload_warns_without_content_and_does_not_raise(flag, caplog):
    client = _Client(fail=PermissionError("denied"))
    with caplog.at_level(logging.DEBUG):
        out = _emit(client, bucket=_EXPLICIT)
    assert out.outcome is FleetStorageOutcome.FAILED
    assert len(out) == 1
    warns = _warnings(caplog)
    assert len(warns) == 1
    msg = warns[0].getMessage()
    assert "PermissionError" in msg and "signals/demo/latest.jsonl" in msg
    assert _SECRET not in caplog.text
    assert warns[0].exc_info is None


def test_emit_auth_failure_is_a_warning_too(flag, caplog):
    class DefaultCredentialsError(Exception):
        pass

    with caplog.at_level(logging.DEBUG):
        out = _emit(_Client(fail=DefaultCredentialsError("none")), bucket=_EXPLICIT)
    assert out.outcome is FleetStorageOutcome.FAILED
    assert len(_warnings(caplog)) == 1


# ---- signals: bridge ----------------------------------------------------------


class _Failure:
    reason = "r"
    summary = _SECRET
    task_id = "t1"


def test_bridge_threads_bucket_and_env(flag, monkeypatch):
    client = _Client()
    failure_to_signal(
        worker_id="demo", flag_env="DEMO_EMIT", bucket=_EXPLICIT, storage_client_factory=lambda: client
    )(_Failure())
    assert {b for b, _ in client.store} == {_EXPLICIT}
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    client2 = _Client()
    failure_to_signal(
        worker_id="demo", flag_env="DEMO_EMIT", storage_client_factory=lambda: client2
    )(_Failure())
    assert {b for b, _ in client2.store} == {_FROM_ENV}


def test_bridge_unconfigured_writes_nothing(flag, caplog):
    client = _Client()
    with caplog.at_level(logging.INFO):
        failure_to_signal(
            worker_id="demo", flag_env="DEMO_EMIT", storage_client_factory=lambda: client
        )(_Failure())
    assert client.store == {}
    assert len(_info_lines(caplog)) == 1


# ---- signals: subscribe -------------------------------------------------------


def _poll(client: _Client, tmp_path: Path, **kw):
    return poll(
        Subscription(consumer_id="c", workers=("demo",)),
        cursor_store=FileCursorStore(tmp_path),
        storage_client_factory=lambda: client,
        **kw,
    )


def test_poll_unconfigured_returns_empty_with_outcome(tmp_path, caplog):
    client = _Client()
    with caplog.at_level(logging.INFO):
        result = _poll(client, tmp_path)
    assert result == []
    assert result.outcome is FleetStorageOutcome.NOT_CONFIGURED
    assert len(_info_lines(caplog)) == 1


def test_poll_uses_argument_or_env(tmp_path, monkeypatch):
    seen: list[str] = []

    class _Spy(_Client):
        def bucket(self, name: str) -> _Bucket:
            seen.append(name)
            return super().bucket(name)

    assert _poll(_Spy(), tmp_path, bucket=_EXPLICIT).outcome is FleetStorageOutcome.OK
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    _poll(_Spy(), tmp_path)
    assert seen == [_EXPLICIT, _FROM_ENV]


def test_poll_failure_warns_and_reports_failed(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        result = _poll(_Client(fail=PermissionError("x")), tmp_path, bucket=_EXPLICIT)
    assert result == []
    assert result.outcome is FleetStorageOutcome.FAILED
    assert len(_warnings(caplog)) == 1
    assert "PermissionError" in _warnings(caplog)[0].getMessage()


def test_gcs_cursor_store_bucket_rule(caplog, monkeypatch):
    client = _Client()
    store = GcsCursorStore("c", storage_client_factory=lambda: client)
    with caplog.at_level(logging.INFO):
        assert store.load("c", "w") is None
        store.save("c", "w", "x")
    assert client.store == {}
    assert store.last_outcome is FleetStorageOutcome.NOT_CONFIGURED
    assert len(_info_lines(caplog)) == 1
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    store.save("c", "w", "x")
    assert {b for b, _ in client.store} == {_FROM_ENV}
    assert store.last_outcome is FleetStorageOutcome.OK


def test_gcs_cursor_store_failed_save_reports_and_warns(caplog):
    class Forbidden(Exception):
        pass

    store = GcsCursorStore(
        "c", bucket=_EXPLICIT, storage_client_factory=lambda: _Client(fail=Forbidden("no"))
    )
    with caplog.at_level(logging.DEBUG):
        store.save("c", "w", "x")  # auth-class failures never raised; still must not be silent
    assert store.last_outcome is FleetStorageOutcome.FAILED
    assert len(_warnings(caplog)) >= 1


# ---- telemetry ------------------------------------------------------------------

_BUF = [{"event": "x", "ts": "2026-05-25T09:00:00+00:00", "payload": {"severity": "INFO", "d": _SECRET}}]


def _flush(client: _Client, **kw):
    return flush_buffer_outcome(
        _BUF,
        worker_id="demo",
        run_id="rid",
        storage_client_factory=lambda: client,
        log=logging.getLogger("demo.obs"),
        **kw,
    )


def test_flush_with_argument_and_env(monkeypatch):
    client = _Client()
    assert _flush(client, bucket=_EXPLICIT) is FleetStorageOutcome.OK
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    assert _flush(client) is FleetStorageOutcome.OK
    assert {b for b, _ in client.store} == {_EXPLICIT, _FROM_ENV}


def test_flush_unconfigured(caplog):
    client = _Client()
    with caplog.at_level(logging.INFO):
        out = _flush(client)
        again = _flush(client)
    assert out is again is FleetStorageOutcome.NOT_CONFIGURED
    assert client.store == {}
    assert len(_info_lines(caplog)) == 1
    ok = flush_buffer(
        _BUF,
        worker_id="demo",
        storage_client_factory=lambda: client,
        log=logging.getLogger("demo.obs"),
    )
    assert ok is False  # existing boolean contract: True only on a clean upload


def test_flush_failure_warns_without_content(caplog):
    with caplog.at_level(logging.DEBUG):
        out = _flush(_Client(fail=TimeoutError("slow")), bucket=_EXPLICIT)
    assert out is FleetStorageOutcome.FAILED
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "TimeoutError" in warns[0].getMessage()
    assert "logs/demo/2026-05-25/rid.jsonl" in warns[0].getMessage()
    assert _SECRET not in caplog.text


def test_make_obs_session_uses_env_bucket_and_records_outcome(monkeypatch):
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    client = _Client()
    event, run_session = make_obs(worker_id="demo", storage_client_factory=lambda: client)
    with run_session(trigger="t", run_id="rid"):
        event("hello")
    assert {b for b, _ in client.store} == {_FROM_ENV}
    assert last_flush_outcome("demo") is FleetStorageOutcome.OK


def test_make_obs_session_unconfigured_records_outcome(caplog):
    client = _Client()
    event, run_session = make_obs(worker_id="demo", storage_client_factory=lambda: client)
    with caplog.at_level(logging.INFO), run_session(trigger="t", run_id="rid"):
        event("hello")
    assert client.store == {}
    assert last_flush_outcome("demo") is FleetStorageOutcome.NOT_CONFIGURED
    assert len(_info_lines(caplog)) == 1


# ---- audit log ------------------------------------------------------------------


def _audit_event() -> AuditEvent:
    return AuditEvent(
        ts=_NOW,
        worker="demo",
        run_id="run-1",
        event="gate.offered",
        capability_key=None,
        actor="human",
        dry_run=True,
        money_movement=False,
        outcome=None,
        equivalent_cli=None,
        focus=None,
        ref=None,
    )


def _audit(tmp_path: Path, client: _Client, **kw):
    sink = make_audit_sink(
        "demo", base_dir=tmp_path, gcs=True, storage_client_factory=lambda: client, **kw
    )
    sink(_audit_event())
    return sink


def test_audit_with_argument_and_env(tmp_path, monkeypatch):
    client = _Client()
    sink = _audit(tmp_path, client, bucket=_EXPLICIT)
    assert sink.flush() is True  # type: ignore[attr-defined]
    assert {b for b, _ in client.store} == {_EXPLICIT}
    monkeypatch.setenv(FLEET_BUCKET_ENV, _FROM_ENV)
    client2 = _Client()
    sink2 = _audit(tmp_path / "b", client2)
    assert sink2.flush() is True  # type: ignore[attr-defined]
    assert {b for b, _ in client2.store} == {_FROM_ENV}


def test_audit_unconfigured_keeps_local_file_and_says_so_once(tmp_path, caplog):
    client = _Client()
    with caplog.at_level(logging.INFO):
        sink = _audit(tmp_path, client)
        assert sink.flush() is False  # type: ignore[attr-defined]
        sink.flush()  # type: ignore[attr-defined]
    assert client.store == {}
    assert sink.last_outcome is FleetStorageOutcome.NOT_CONFIGURED  # type: ignore[attr-defined]
    assert len(_info_lines(caplog)) == 1
    assert list(tmp_path.glob("*.jsonl"))  # the local record is untouched


def test_audit_failed_upload_warns_without_content(tmp_path, caplog):
    client = _Client(fail=OSError("disk"))
    with caplog.at_level(logging.DEBUG):
        sink = _audit(tmp_path, client, bucket=_EXPLICIT)
        assert sink.flush() is False  # type: ignore[attr-defined]
    assert sink.last_outcome is FleetStorageOutcome.FAILED  # type: ignore[attr-defined]
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "OSError" in warns[0].getMessage() and "audit/demo/" in warns[0].getMessage()


# ---- no bucket literal in shipped code ---------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
_LITERALS = (
    re.compile(r"orchestrator-eu", re.I),
    re.compile(r"[a-z0-9][a-z0-9-]*-(?:eu|us|asia)-(?:west|east|north|south|central)\d?\b", re.I),
)


def test_no_bucket_literal_under_src_or_worker_template():
    hits = []
    for base in ("src", "worker-template"):
        for path in (_ROOT / base).rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".png"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for rx in _LITERALS:
                for m in rx.finditer(text):
                    hits.append(f"{path.relative_to(_ROOT)}: {m.group(0)}")
    assert hits == []
