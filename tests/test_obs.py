# tests/test_obs.py
"""CC-OBS-* — shared telemetry (obs) emitter tests.

Mirrors the four workers' own ``obs.py`` tests (xbook / xhr / xletter / xquill)
so a migrated worker is byte-identical on the wire to the dashboard. The GCS
client is injected via ``storage_client_factory`` — no network, no
google-cloud-storage dependency. The runtime/cloud-logging side-channel is
exercised through an injected ``cloud_logging_sink`` so no google import is
needed either.

The dashboard reads ``logs/<worker_id>/<YYYY-MM-DD>/<run_id>.jsonl`` where each
line is ``{"event":…,"ts":…,"payload":{"severity":…, **fields}}`` (compact
separators, trailing newline). These tests pin that exact wire shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from clonway_cockpit.obs import (
    RESERVED_LOGRECORD_KEYS,
    SEVERITY_TO_LEVEL,
    event_buffer,
    isolated_event_buffers,
    make_obs,
    resolve_run_id,
)

# ---- fakes -----------------------------------------------------------------


class _FakeBlob:
    def __init__(self, store: dict[str, str], name: str) -> None:
        self._store = store
        self._name = name

    def upload_from_string(self, body: str, content_type: str | None = None) -> None:
        self._store[self._name] = body
        self._store.setdefault("__content_types__", "")
        # record content type alongside for one assertion
        self._store[f"__ct__::{self._name}"] = content_type or ""


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
        self._store["__bucket__"] = name
        return _FakeBucket(self._store)


class _BoomClient:
    """A client whose bucket() raises — simulates a GCS outage."""

    def __init__(self, project: object = None) -> None:
        pass

    def bucket(self, name: str) -> _FakeBucket:
        raise RuntimeError("simulated GCS failure")


def _data_lines(body: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in body.splitlines() if line]


# ---- module-level constants ------------------------------------------------


def test_severity_map_covers_canonical_names():  # CC-OBS-CONST-1
    assert SEVERITY_TO_LEVEL["DEBUG"] == logging.DEBUG
    assert SEVERITY_TO_LEVEL["INFO"] == logging.INFO
    # WARN is the contract §4.3 alias for WARNING.
    assert SEVERITY_TO_LEVEL["WARN"] == logging.WARNING
    assert SEVERITY_TO_LEVEL["WARNING"] == logging.WARNING
    assert SEVERITY_TO_LEVEL["ERROR"] == logging.ERROR
    assert SEVERITY_TO_LEVEL["CRITICAL"] == logging.CRITICAL


def test_reserved_keys_include_logrecord_colliders():  # CC-OBS-CONST-2
    # The classic colliders that 500'd the workers at INFO level.
    for k in ("args", "module", "message", "name", "msg", "taskName"):
        assert k in RESERVED_LOGRECORD_KEYS


# ---- run_id resolution -----------------------------------------------------


def test_resolve_run_id_explicit_wins(monkeypatch):  # CC-OBS-RID-1
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "env-exec")
    assert resolve_run_id("explicit") == "explicit"


def test_resolve_run_id_from_env(monkeypatch):  # CC-OBS-RID-2
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "env-exec")
    assert resolve_run_id(None) == "env-exec"


def test_resolve_run_id_uuid_fallback(monkeypatch):  # CC-OBS-RID-3
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    rid = resolve_run_id(None)
    assert rid != "None" and len(rid) == 32


# ---- event(): local log line -----------------------------------------------


def test_event_emits_info_by_default(caplog):  # CC-OBS-EVENT-1
    event, _ = make_obs(worker_id="xbook")
    with caplog.at_level(logging.DEBUG, logger="xbook.obs"):
        event("plan.complete", stage="plan", count=3)
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelname == "INFO"
    assert rec.msg == "plan.complete"
    assert rec.event == "plan.complete"  # type: ignore[attr-defined]
    assert rec.severity == "INFO"  # type: ignore[attr-defined]
    assert rec.stage == "plan"  # type: ignore[attr-defined]
    assert rec.count == 3  # type: ignore[attr-defined]


def test_event_severity_maps_to_level(caplog):  # CC-OBS-EVENT-2
    event, _ = make_obs(worker_id="xhr")
    with caplog.at_level(logging.DEBUG, logger="xhr.obs"):
        event("d", severity="DEBUG")
        event("w", severity="WARNING")
        event("e", severity="ERROR")
        event("c", severity="CRITICAL")
    assert [r.levelname for r in caplog.records] == ["DEBUG", "WARNING", "ERROR", "CRITICAL"]


def test_event_unknown_severity_raises():  # CC-OBS-EVENT-3
    event, _ = make_obs(worker_id="xbook")
    with pytest.raises(ValueError, match="unknown severity"):
        event("nope", severity="MEH")


def test_event_renames_reserved_fields_default_prefix(caplog):  # CC-OBS-EVENT-4
    # Default prefix is field_ (xbook's choice; the canonical source).
    event, _ = make_obs(worker_id="xbook")
    with caplog.at_level(logging.DEBUG, logger="xbook.obs"):
        event("run.started", trigger="webhook", args={"x": 1}, module="rcv", run_id="rid-1")
    rec = caplog.records[0]
    assert rec.trigger == "webhook"  # type: ignore[attr-defined]
    assert rec.run_id == "rid-1"  # type: ignore[attr-defined]
    assert rec.field_args == {"x": 1}  # type: ignore[attr-defined]
    assert rec.field_module == "rcv"  # type: ignore[attr-defined]


def test_event_reserved_prefix_configurable(caplog):  # CC-OBS-EVENT-5
    # xhr / xletter / xquill use f_ — the prefix is per-worker.
    event, _ = make_obs(worker_id="xhr", reserved_prefix="f_")
    with caplog.at_level(logging.DEBUG, logger="xhr.obs"):
        event("run.started", args={"x": 1})
    rec = caplog.records[0]
    assert rec.f_args == {"x": 1}  # type: ignore[attr-defined]


def test_event_custom_logger_factory(caplog):  # CC-OBS-EVENT-6
    # xbook injects its own get_logger; the helper must use it verbatim.
    seen: list[str] = []

    def factory(name: str) -> logging.Logger:
        seen.append(name)
        return logging.getLogger(name)

    event, _ = make_obs(worker_id="xbook", logger_factory=factory)
    with caplog.at_level(logging.DEBUG, logger="xbook.obs"):
        event("x.event")
    assert "xbook.obs" in seen


# ---- event(): cloud-logging side channel -----------------------------------


def test_cloud_logging_skipped_when_runtime_unset(monkeypatch):  # CC-OBS-CLOUD-1
    monkeypatch.delenv("XBOOK_RUNTIME", raising=False)
    sink_calls: list[Any] = []
    event, _ = make_obs(
        worker_id="xbook",
        runtime_env="XBOOK_RUNTIME",
        cloud_logging_sink=lambda name, sev, fields: sink_calls.append((name, sev, fields)),
    )
    event("local.event", stage="plan")
    assert sink_calls == []


def test_cloud_logging_called_on_cloud_run(monkeypatch):  # CC-OBS-CLOUD-2
    monkeypatch.setenv("XBOOK_RUNTIME", "cloud_run")
    sink_calls: list[Any] = []
    event, _ = make_obs(
        worker_id="xbook",
        runtime_env="XBOOK_RUNTIME",
        cloud_logging_sink=lambda name, sev, fields: sink_calls.append((name, sev, fields)),
    )
    event("cloud.event", severity="ERROR", stage="plan", count=7)
    assert sink_calls == [("cloud.event", "ERROR", {"stage": "plan", "count": 7})]


def test_cloud_logging_failure_does_not_propagate(caplog, monkeypatch):  # CC-OBS-CLOUD-3
    monkeypatch.setenv("XBOOK_RUNTIME", "cloud_run")

    def boom(name, sev, fields):
        raise RuntimeError("cloud logging down")

    event, _ = make_obs(worker_id="xbook", runtime_env="XBOOK_RUNTIME", cloud_logging_sink=boom)
    with caplog.at_level(logging.DEBUG, logger="xbook.obs"):
        event("still.local")  # must not raise
    # Local log line still fired.
    assert any(r.msg == "still.local" for r in caplog.records)


def test_no_cloud_logging_when_runtime_env_unconfigured(monkeypatch):  # CC-OBS-CLOUD-4
    # xquill ships no Cloud Logging side-channel — runtime_env=None means it's
    # never consulted even if a XQUILL_RUNTIME var happens to be set.
    monkeypatch.setenv("XQUILL_RUNTIME", "cloud_run")
    sink_calls: list[Any] = []
    event, _ = make_obs(
        worker_id="xquill",
        cloud_logging_sink=lambda *a: sink_calls.append(a),  # configured but...
    )
    event("x")  # ...runtime_env is None, so it's never called
    assert sink_calls == []


# ---- run_session: wire shape -----------------------------------------------


def test_run_session_writes_jsonl_at_right_path(monkeypatch):  # CC-OBS-RUN-1
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(
        worker_id="xbook",
        storage_client_factory=lambda: client,
    )
    with run_session(trigger="manual", run_id="exec-1"):
        event("plan.complete", stage="plan", count=3)

    store = client._store
    keys = [k for k in store if k.startswith("logs/")]
    assert len(keys) == 1
    key = keys[0]
    # Path: logs/<worker>/<YYYY-MM-DD>/<run_id>.jsonl
    assert key.startswith("logs/xbook/")
    assert key.endswith("/exec-1.jsonl")
    parts = key.split("/")
    assert len(parts[2]) == 10 and parts[2][4] == "-" and parts[2][7] == "-"
    # NDJSON, trailing newline, compact separators.
    body = store[key]
    assert body.endswith("\n")
    assert ", " not in body and '": ' not in body
    assert store[f"__ct__::{key}"] == "application/x-ndjson"


def test_run_session_buffers_events_with_payload_shape(monkeypatch):  # CC-OBS-RUN-2
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(worker_id="xhr", storage_client_factory=lambda: client)
    with run_session(trigger="scheduler", args={"job": "sync"}, run_id="r1"):
        event("stage.ok", severity="INFO", stage="sync")

    body = client._store["logs/xhr/" + _date_of(client) + "/r1.jsonl"]
    lines = _data_lines(body)
    # run.started, stage.ok, run.finished
    names = [e["event"] for e in lines]
    assert names == ["run.started", "stage.ok", "run.finished"]
    for e in lines:
        assert set(e) == {"event", "ts", "payload"}
        assert "severity" in e["payload"]
    started = lines[0]["payload"]
    assert started["trigger"] == "scheduler"
    assert started["args"] == {"job": "sync"}
    assert started["run_id"] == "r1"
    assert started["contract_version"] == "v0.1"
    assert started["source"] == "cloud_run"
    finished = lines[-1]["payload"]
    assert finished["status"] == "ok"
    assert "duration_ms" in finished
    assert finished["source"] == "cloud_run"


def _date_of(client: _FakeClient) -> str:
    key = next(k for k in client._store if k.startswith("logs/"))
    return key.split("/")[2]


def test_run_session_error_marks_status_and_reraises(monkeypatch):  # CC-OBS-RUN-3
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(worker_id="xquill", storage_client_factory=lambda: client)
    with pytest.raises(ValueError, match="kaboom"):  # noqa: SIM117
        with run_session(trigger="cron", run_id="r2"):
            raise ValueError("kaboom")
    body = client._store["logs/xquill/" + _date_of(client) + "/r2.jsonl"]
    finished = _data_lines(body)[-1]["payload"]
    assert finished["status"] == "error"
    assert "kaboom" in finished["summary"]


def test_run_session_run_id_from_env(monkeypatch):  # CC-OBS-RUN-4
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "fpo-77")
    client = _FakeClient()
    event, run_session = make_obs(worker_id="xletter", storage_client_factory=lambda: client)
    with run_session(trigger="scheduler"):
        event("noop")
    assert any(k.endswith("/fpo-77.jsonl") for k in client._store)


@pytest.mark.parametrize(
    "ordering",
    [
        "run_session_alone",
        "event_buffer_then_run_session",
        "run_session_then_event_buffer",
        "nested_same_worker",
        "nested_other_worker",
    ],
)
@pytest.mark.parametrize("raises", [False, True], ids=["clean", "exception"])
def test_event_buffer_run_session_ordering_matrix(monkeypatch, ordering, raises):
    """Public buffer scopes never disarm a worker run's lifecycle or flush policy."""
    import clonway_cockpit.obs._telemetry as obs_mod

    flushed: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(
        obs_mod,
        "flush_buffer",
        lambda buffer, **kwargs: flushed.append(list(buffer)) or True,
    )
    event, run_session = make_obs(worker_id="alpha")
    scopes: dict[str, Any] = {}

    def work() -> None:
        event("work.done")
        if raises:
            raise LookupError("boom")

    def exercise() -> None:
        if ordering == "run_session_alone":
            with run_session(trigger="test"):
                work()
        elif ordering == "event_buffer_then_run_session":
            with event_buffer("alpha") as scope:
                scopes["alpha"] = scope
                with run_session(trigger="test"):
                    work()
        elif ordering == "run_session_then_event_buffer":
            with run_session(trigger="test"), event_buffer("alpha") as scope:
                scopes["alpha"] = scope
                work()
        elif ordering == "nested_same_worker":
            with event_buffer("alpha") as outer:
                scopes["alpha"] = outer
                with event_buffer("alpha") as nested:
                    scopes["nested"] = nested
                    with run_session(trigger="test"):
                        work()
        else:
            with event_buffer("beta") as other:
                scopes["beta"] = other
                with run_session(trigger="test"):
                    work()

    with isolated_event_buffers():
        if raises:
            with pytest.raises(LookupError, match="boom"):
                exercise()
        else:
            exercise()

    expected_names = ["run.started", "work.done", "run.finished"]
    assert [[record["event"] for record in batch] for batch in flushed] == [expected_names]
    assert flushed[0][-1]["payload"]["status"] == ("error" if raises else "ok")
    if "alpha" in scopes:
        assert [record["event"] for record in scopes["alpha"].events] == expected_names
    if "nested" in scopes:
        assert scopes["nested"].events is scopes["alpha"].events
        assert scopes["nested"].owner is False
    if "beta" in scopes:
        assert scopes["beta"].events == []


# ---- run_session: runtime flush gate -----------------------------------------


def test_run_session_no_flush_when_runtime_unset(monkeypatch, caplog):  # CC-OBS-GATE-1
    # The 2026-06 telemetry-pollution fix: a worker that declares a runtime_env
    # must NOT upload to the fleet bucket from a test/dev/agent invocation —
    # the storage client is never even constructed — and the lifecycle events
    # say source=local, not cloud_run.
    monkeypatch.delenv("XLETTER_RUNTIME", raising=False)
    monkeypatch.delenv("CLONWAY_OBS_FORCE_FLUSH", raising=False)
    factory_calls: list[int] = []

    def factory() -> _FakeClient:
        factory_calls.append(1)
        return _FakeClient()

    event, run_session = make_obs(
        worker_id="xletter",
        runtime_env="XLETTER_RUNTIME",
        storage_client_factory=factory,
    )
    with caplog.at_level(logging.DEBUG, logger="xletter.obs"):  # noqa: SIM117
        with run_session(trigger="manual", run_id="r-local"):
            event("stage.ok")
    assert factory_calls == []  # nothing uploaded, client never built
    started = next(r for r in caplog.records if r.msg == "run.started")
    finished = next(r for r in caplog.records if r.msg == "run.finished")
    assert started.source == "local"  # type: ignore[attr-defined]
    assert finished.source == "local"  # type: ignore[attr-defined]
    # The gate announces itself at debug so a missing prod flush is diagnosable.
    assert any("obs flush gated" in r.getMessage() for r in caplog.records)


def test_run_session_flushes_on_cloud_run_with_cloud_run_source(monkeypatch):  # CC-OBS-GATE-2
    # In real cloud_run the wire is byte-identical to the pre-gate emitter:
    # flush happens, lifecycle source stays "cloud_run".
    monkeypatch.setenv("XLETTER_RUNTIME", "cloud_run")
    monkeypatch.delenv("CLONWAY_OBS_FORCE_FLUSH", raising=False)
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(
        worker_id="xletter",
        runtime_env="XLETTER_RUNTIME",
        storage_client_factory=lambda: client,
    )
    with run_session(trigger="scheduler", run_id="r-cr"):
        event("stage.ok")
    body = client._store["logs/xletter/" + _date_of(client) + "/r-cr.jsonl"]
    lines = _data_lines(body)
    assert [e["event"] for e in lines] == ["run.started", "stage.ok", "run.finished"]
    assert lines[0]["payload"]["source"] == "cloud_run"
    assert lines[-1]["payload"]["source"] == "cloud_run"


def test_run_session_force_flush_opt_in(monkeypatch):  # CC-OBS-GATE-3
    # CLONWAY_OBS_FORCE_FLUSH=1 is the explicit operator override: the flush
    # happens off-cloud_run, but source stays truthful ("local").
    monkeypatch.delenv("XLETTER_RUNTIME", raising=False)
    monkeypatch.setenv("CLONWAY_OBS_FORCE_FLUSH", "1")
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(
        worker_id="xletter",
        runtime_env="XLETTER_RUNTIME",
        storage_client_factory=lambda: client,
    )
    with run_session(trigger="manual", run_id="r-forced"):
        event("stage.ok")
    body = client._store["logs/xletter/" + _date_of(client) + "/r-forced.jsonl"]
    lines = _data_lines(body)
    assert lines[0]["payload"]["source"] == "local"
    assert lines[-1]["payload"]["source"] == "local"


def test_run_session_legacy_flush_when_no_runtime_env(monkeypatch):  # CC-OBS-GATE-4
    # runtime_env=None (xquill — production runtime IS local launchd) keeps the
    # legacy behaviour byte-identical: always flush, source="cloud_run".
    monkeypatch.delenv("CLONWAY_OBS_FORCE_FLUSH", raising=False)
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    client = _FakeClient()
    event, run_session = make_obs(worker_id="xsecretary", storage_client_factory=lambda: client)
    with run_session(trigger="cron", run_id="r-legacy"):
        event("stage.ok")
    body = client._store["logs/xsecretary/" + _date_of(client) + "/r-legacy.jsonl"]
    lines = _data_lines(body)
    assert lines[0]["payload"]["source"] == "cloud_run"
    assert lines[-1]["payload"]["source"] == "cloud_run"


# ---- run_session: best-effort degrade --------------------------------------


def test_run_session_swallows_gcs_error(monkeypatch):  # CC-OBS-RUN-5
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    event, run_session = make_obs(worker_id="xhr", storage_client_factory=lambda: _BoomClient())
    # The whole block completes without the flush error propagating.
    with run_session(trigger="manual", run_id="r3"):
        event("stage.ok")
    # No assertion on store: the point is no exception escaped.


def test_run_session_empty_buffer_no_upload(monkeypatch):  # CC-OBS-RUN-6
    # A run_session always emits run.started + run.finished, so the buffer is
    # never empty in practice; but _flush_buffer's empty no-op is part of the
    # contract for direct reuse. Exercise it via flush_buffer directly.
    from clonway_cockpit.obs import flush_buffer

    client = _FakeClient()
    ok = flush_buffer(
        [],
        worker_id="xbook",
        run_id="r",
        storage_client_factory=lambda: client,
        log=logging.getLogger("t"),
    )
    assert ok is True
    assert not any(k.startswith("logs/") for k in client._store)


# ---- flush_buffer: project + bucket threading ------------------------------


def test_flush_buffer_threads_bucket_and_body():  # CC-OBS-FLUSH-1
    client = _FakeClient()
    buf = [{"event": "x", "ts": "2026-05-25T09:00:00+00:00", "payload": {"severity": "INFO"}}]
    flush = _flush_helper()
    ok = flush(
        buf,
        worker_id="xbook",
        run_id="rid",
        storage_client_factory=lambda: client,
        log=logging.getLogger("t"),
    )
    assert ok is True
    assert client._store["__bucket__"] == "clonway-orchestrator-eu-west2"
    body = client._store["logs/xbook/2026-05-25/rid.jsonl"]
    assert body == json.dumps(buf[0], separators=(",", ":")) + "\n"


def test_flush_buffer_date_from_first_event_ts():  # CC-OBS-FLUSH-2
    # Path date comes from buffer[0]['ts'][:10], not "today" — a run straddling
    # midnight keeps all events in the one file.
    client = _FakeClient()
    buf = [
        {"event": "a", "ts": "2026-05-25T23:59:59+00:00", "payload": {"severity": "INFO"}},
        {"event": "b", "ts": "2026-05-26T00:00:01+00:00", "payload": {"severity": "INFO"}},
    ]
    _flush_helper()(
        buf,
        worker_id="xhr",
        run_id="rid",
        storage_client_factory=lambda: client,
        log=logging.getLogger("t"),
    )
    assert "logs/xhr/2026-05-25/rid.jsonl" in client._store


def test_default_factory_threads_project(monkeypatch):  # CC-OBS-FLUSH-3
    import clonway_cockpit.obs._telemetry as obs_mod

    captured: dict[str, object] = {}

    class _StorageStub:
        @staticmethod
        def Client(project=None):  # noqa: N802 — mirrors google.cloud.storage.Client
            captured["project"] = project
            return _FakeClient(project=project)

    monkeypatch.setattr(obs_mod, "_import_storage", lambda: _StorageStub)
    buf = [{"event": "x", "ts": "2026-05-25T09:00:00+00:00", "payload": {"severity": "INFO"}}]
    obs_mod.flush_buffer(
        buf,
        worker_id="xsecretary",
        run_id="rid",
        project="clonway-care-bookkeeper",
        log=logging.getLogger("t"),
    )
    # xquill/xsecretary's launchd-env requirement: explicit project= threads through.
    assert captured["project"] == "clonway-care-bookkeeper"


def test_default_factory_no_project(monkeypatch):  # CC-OBS-FLUSH-4
    import clonway_cockpit.obs._telemetry as obs_mod

    captured: dict[str, object] = {"project": "<unset>"}

    class _StorageStub:
        @staticmethod
        def Client(project=None):  # noqa: N802
            captured["project"] = project
            return _FakeClient(project=project)

    monkeypatch.setattr(obs_mod, "_import_storage", lambda: _StorageStub)
    buf = [{"event": "x", "ts": "2026-05-25T09:00:00+00:00", "payload": {"severity": "INFO"}}]
    obs_mod.flush_buffer(buf, worker_id="xbook", run_id="rid", log=logging.getLogger("t"))
    assert captured["project"] is None


def test_flush_buffer_quiet_on_auth_error(caplog):  # CC-OBS-FLUSH-5
    # An auth/forbidden failure (creds absent in local/dev) logs at debug, not
    # exception — matching xbook's quiet skip. Matched by class name so this
    # module never imports google.
    class Forbidden(Exception):
        pass

    class _AuthBoom:
        def bucket(self, name):
            raise Forbidden("no creds")

    buf = [{"event": "x", "ts": "2026-05-25T09:00:00+00:00", "payload": {"severity": "INFO"}}]
    log = logging.getLogger("xbook.obs")
    with caplog.at_level(logging.DEBUG, logger="xbook.obs"):
        ok = _flush_helper()(
            buf,
            worker_id="xbook",
            run_id="rid",
            storage_client_factory=lambda: _AuthBoom(),
            log=log,
        )
    assert ok is False
    # Quiet: debug record, no ERROR/exception record.
    assert all(r.levelno < logging.ERROR for r in caplog.records)
    assert any("skipped" in r.getMessage() for r in caplog.records)


def _flush_helper():
    from clonway_cockpit.obs import flush_buffer

    return flush_buffer
