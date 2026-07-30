"""Shared run/stage telemetry emitter — the one best-effort GCS flush the whole
fleet uses for the Auto-Orchestrator (xops) dashboard.

Extracted from four near-identical worker ``obs.py`` files (xbook / xhr /
xletter / xquill). A worker keeps a thin ``obs.py`` shim that binds its
``worker_id`` (and any worker-specific knobs) via :func:`make_obs` and re-exports
the resulting ``event`` / ``run_session``. The wire shape, paths, run_id
resolution, and degrade behaviour are identical to the originals, so a migrated
worker is byte-identical on the wire — the dashboard never notices the swap.

The wire contract (do NOT change without coordinating with the xops dashboard):

* ``run_session`` wraps a run: emits ``run.started`` then yields; on exit emits
  ``run.finished`` (``status=error`` if the block raised) and flushes the
  buffered events to GCS as one JSONL object.
* Each ``event(name, severity=…, **fields)`` call inside an active session is
  buffered as ``{"event": name, "ts": <iso utc>, "payload": {"severity": …,
  **fields}}``. It also always fires a local stdlib log line (greppable
  ``key=value`` extras) and — when ``runtime_env`` is set to ``cloud_run`` —
  mirrors to a worker-supplied Cloud Logging sink.
* The buffer flushes to
  ``gs://clonway-orchestrator-eu-west2/logs/<worker_id>/<YYYY-MM-DD>/<run_id>.jsonl``
  where the date is taken from the FIRST buffered event's ``ts`` (so a run that
  straddles midnight UTC stays in one file) and ``run_id`` resolves to
  ``CLOUD_RUN_EXECUTION`` or a fresh uuid. Body is compact NDJSON with a
  trailing newline, ``content_type="application/x-ndjson"``.
* The flush is **runtime-gated** for workers that declare a ``runtime_env``:
  it only uploads when ``os.environ[runtime_env] == "cloud_run"`` (the same
  check that gates the Cloud Logging mirror) or when the operator opts in via
  ``CLONWAY_OBS_FORCE_FLUSH=1``. A test/dev/agent invocation with live ADC
  therefore canNOT pollute fleet telemetry (the 2026-06 incident: xletter's
  test suite uploaded 80 deliberately-failing runs that the xops digest counted
  as prod errors). The lifecycle events' ``source`` field tells the truth for
  these workers too: ``cloud_run`` only when actually in cloud_run, ``local``
  otherwise. Workers with ``runtime_env=None`` (xquill's launchd daemon, whose
  production runtime IS local) keep the legacy behaviour byte-identical:
  always flush, ``source="cloud_run"``.
* Best-effort: a creds-less / offline / quota-throttled environment degrades
  silently, never crashing a worker run. An auth/forbidden failure (expected in
  local/dev) logs at debug; anything else logs at exception.

``google-cloud-storage`` is NOT a dependency of clonway-cockpit — the import is
lazy (only the workers, which already depend on it, hit the default factory).
Tests inject a fake client via ``storage_client_factory``; the Cloud Logging
side-channel is injected via ``cloud_logging_sink`` so no google import is
needed there either.

Worker-specific behaviour that does NOT belong here (keep it in the shim): the
summary policy (xhr's job-name default, xletter's ``set_run_summary`` /
``parent_span_id`` helpers), xbook's reentrancy guard + truelayer dedupe reset.
Those wrap or extend :func:`make_obs`'s output; they don't change the wire.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_BUCKET = "clonway-orchestrator-eu-west2"  # shared fleet bucket

# Opt-in override for the runtime flush gate: set to "1" to flush a
# run_session's buffer to GCS even when the worker's ``runtime_env`` says this
# is not cloud_run (deliberate local telemetry checks / one-off backfills).
# No effect on workers with ``runtime_env=None``, which always flush. The
# lifecycle ``source`` stays truthful (``local``) under the override.
FORCE_FLUSH_ENV = "CLONWAY_OBS_FORCE_FLUSH"

# Canonical severity names → stdlib logging levels. ``WARN`` is the contract
# §4.3 alias for ``WARNING``; both map to the same level.
SEVERITY_TO_LEVEL: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# LogRecord attribute names that stdlib ``logging.makeRecord`` rejects as
# ``extra=`` keys with ``KeyError("Attempt to overwrite '<name>' in LogRecord")``.
# Any caller-supplied field with one of these names is renamed
# ``<reserved_prefix><name>`` before being passed to ``logger.log(extra=…)`` so
# the event() call doesn't blow up at INFO level (it 500'd the workers in prod).
# Superset of all four workers' sets (xbook omitted ``taskName``; include it).
RESERVED_LOGRECORD_KEYS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# google auth/forbidden error class names — matched by name so this module never
# imports google packages clonway-cockpit doesn't depend on. A match logs at
# debug (expected when creds are absent); anything else logs at exception.
_QUIET_ERROR_NAMES = {"Forbidden", "GoogleAuthError", "DefaultCredentialsError"}

# Per-(worker_id) run buffer. None when no run_session is active on this
# contextvar — in that case event() goes straight to local logging (+ cloud
# logging) without being buffered. Keyed by worker_id so two workers sharing a
# process (unusual, but the orchestrator might) don't clobber each other.
_RUN_BUFFERS: ContextVar[dict[str, list[dict]] | None] = ContextVar(
    "clonway_obs_run_buffers", default=None
)


@dataclass(frozen=True, slots=True)
class EventBufferScope:
    """One worker's active event list and whether this scope owns its binding."""

    events: list[dict]
    owner: bool


@contextmanager
def event_buffer(worker_id: str) -> Iterator[EventBufferScope]:
    """Bind or join one worker's event list without exposing ContextVar state."""
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id must be a non-blank string")

    buffers = _RUN_BUFFERS.get()
    if buffers is not None and worker_id in buffers:
        yield EventBufferScope(events=buffers[worker_id], owner=False)
        return

    events: list[dict] = []
    new_buffers = dict(buffers) if buffers is not None else {}
    new_buffers[worker_id] = events
    token = _RUN_BUFFERS.set(new_buffers)
    try:
        yield EventBufferScope(events=events, owner=True)
    finally:
        _RUN_BUFFERS.reset(token)


@contextmanager
def isolated_event_buffers() -> Iterator[None]:
    """Temporarily isolate telemetry buffers for tests, restoring on every exit."""
    token = _RUN_BUFFERS.set(None)
    try:
        yield
    finally:
        _RUN_BUFFERS.reset(token)


CloudLoggingSink = Callable[[str, str, dict[str, Any]], None]
LoggerFactory = Callable[[str], logging.Logger]
StorageClientFactory = Callable[[], Any]


def resolve_run_id(run_id: str | None) -> str:
    """Resolve the run id: explicit arg, else ``CLOUD_RUN_EXECUTION``, else a
    fresh 32-char hex uuid. Never returns the literal string ``"None"``."""
    return run_id or os.environ.get("CLOUD_RUN_EXECUTION") or uuid.uuid4().hex


def _import_storage() -> Any:
    """Lazily import ``google.cloud.storage``. Kept behind a function so (a)
    clonway-cockpit needs no google dependency and (b) tests can monkeypatch it."""
    from google.cloud import storage

    return storage


def _default_factory(project: str | None) -> StorageClientFactory:
    def factory() -> Any:
        storage = _import_storage()
        # Faithful to the originals: bare Client() for Cloud Run workers (project
        # resolves from the runtime), explicit project= for xquill's launchd
        # daemon whose HOME-only env can't resolve a project otherwise.
        return storage.Client(project=project) if project else storage.Client()

    return factory


def flush_buffer(
    buffer: list[dict],
    *,
    worker_id: str,
    run_id: str | None = None,
    bucket: str = _BUCKET,
    project: str | None = None,
    storage_client_factory: StorageClientFactory | None = None,
    log: logging.Logger,
) -> bool:
    """Upload ``buffer`` as one JSONL object to the orchestrator bucket.

    Blob path is ``logs/<worker_id>/<YYYY-MM-DD>/<run_id>.jsonl`` where the date
    is taken from the first event's ``ts`` (a run straddling midnight UTC stays
    in one file) and ``run_id`` resolves via :func:`resolve_run_id`. An empty
    buffer is a no-op (returns ``True``). Returns ``True`` only on a clean
    upload; swallows every error (auth/quota/transient/offline) — observability
    must never break worker logic. Auth/forbidden failures (expected when creds
    are absent) log at debug; anything else logs at exception.
    """
    if not buffer:
        return True
    factory = storage_client_factory or _default_factory(project)
    try:
        body = "\n".join(json.dumps(e, separators=(",", ":")) for e in buffer) + "\n"
        date = buffer[0]["ts"][:10]
        rid = resolve_run_id(run_id)
        blob_path = f"logs/{worker_id}/{date}/{rid}.jsonl"
        factory().bucket(bucket).blob(blob_path).upload_from_string(
            body, content_type="application/x-ndjson"
        )
        return True
    except Exception as exc:  # noqa: BLE001 — observability must never break worker logic
        if type(exc).__name__ in _QUIET_ERROR_NAMES:
            log.debug(
                "obs flush skipped (%s); %d events not uploaded", type(exc).__name__, len(buffer)
            )
        else:
            log.exception("obs flush failed; %d events dropped", len(buffer))
        return False


def make_obs(
    *,
    worker_id: str,
    project: str | None = None,
    bucket: str = _BUCKET,
    runtime_env: str | None = None,
    cloud_logging_sink: CloudLoggingSink | None = None,
    reserved_prefix: str = "field_",
    logger_factory: LoggerFactory | None = None,
    logger_name: str | None = None,
    storage_client_factory: StorageClientFactory | None = None,
) -> tuple[Callable[..., None], Callable[..., Any]]:
    """Build a worker's ``(event, run_session)`` pair bound to its config.

    The returned ``run_session`` and ``event`` produce exactly the wire records
    the four workers ship today, so a migrated worker is byte-identical on the
    dashboard. Worker-specific knobs:

    * ``worker_id`` — dashboard identity (e.g. ``xbook``; ``xsecretary`` for the
      xquill package). Drives the GCS path and the default logger name.
    * ``project`` — passed to ``storage.Client(project=…)`` for xquill's
      launchd daemon; ``None`` (bare ``Client()``) for the Cloud Run workers.
    * ``runtime_env`` — env var (e.g. ``XBOOK_RUNTIME``) checked for the value
      ``cloud_run``. Gates BOTH side-channels: the Cloud Logging mirror and the
      ``run_session`` GCS flush (the flush can also be forced locally via
      ``CLONWAY_OBS_FORCE_FLUSH=1``). It also drives the lifecycle events'
      ``source`` field: ``cloud_run`` when the env matches, ``local`` otherwise.
      ``None`` (xquill, whose production runtime is a local launchd daemon) ⇒
      no cloud-logging mirror ever, and the legacy flush behaviour is kept
      byte-identical: always flush, ``source="cloud_run"``.
    * ``cloud_logging_sink`` — worker-supplied ``(name, severity, fields) ->
      None`` that mirrors to Cloud Logging. The worker owns the google import.
    * ``reserved_prefix`` — prefix for renamed reserved LogRecord fields:
      ``field_`` (xbook, the default) or ``f_`` (xhr / xletter / xquill).
    * ``logger_factory`` / ``logger_name`` — xbook injects its
      ``xbook.logutil.get_logger``; others use stdlib ``logging.getLogger``.
      The logger name defaults to ``<worker_id>.obs``.
    * ``storage_client_factory`` — test injection / custom client construction.
    """
    log_name = logger_name or f"{worker_id}.obs"
    get_log: LoggerFactory = logger_factory or logging.getLogger

    def _in_cloud_run() -> bool:
        """True when the worker's declared runtime env says we're in cloud_run.

        Checked at call time (not bind time) — same as the Cloud Logging gate —
        so tests and entrypoints that set the env after import are honoured.
        """
        return runtime_env is not None and os.environ.get(runtime_env) == "cloud_run"

    def _flush_allowed() -> bool:
        """Whether run_session may upload its buffer to the fleet bucket.

        Workers with no ``runtime_env`` keep the legacy always-flush behaviour
        (their production runtime is local — xquill's launchd daemon). Workers
        WITH one only flush in cloud_run, or under the explicit
        ``CLONWAY_OBS_FORCE_FLUSH=1`` operator override — never from a bare
        test/dev/agent invocation that happens to hold live ADC.
        """
        if runtime_env is None:
            return True
        return _in_cloud_run() or os.environ.get(FORCE_FLUSH_ENV) == "1"

    def event(name: str, *, severity: str = "INFO", **fields: Any) -> None:
        """Emit one structured event.

        Always fires a local stdlib log record (greppable ``key=value`` extras).
        When a ``run_session`` is active on this contextvar, appends the wire
        record to its per-run buffer. When ``runtime_env`` is set to
        ``cloud_run``, mirrors to the Cloud Logging sink (best-effort).
        """
        if severity not in SEVERITY_TO_LEVEL:
            raise ValueError(f"unknown severity {severity!r}")

        level = SEVERITY_TO_LEVEL[severity]
        logger = get_log(log_name)
        extras: dict[str, Any] = {"event": name, "severity": severity}
        for k, v in fields.items():
            extras[f"{reserved_prefix}{k}" if k in RESERVED_LOGRECORD_KEYS else k] = v
        logger.log(level, name, extra=extras)

        buffers = _RUN_BUFFERS.get()
        if buffers is not None and worker_id in buffers:
            buffers[worker_id].append(
                {
                    "event": name,
                    "ts": datetime.now(UTC).isoformat(),
                    "payload": {"severity": severity, **fields},
                }
            )

        if runtime_env and cloud_logging_sink and os.environ.get(runtime_env) == "cloud_run":
            # Best-effort secondary channel — a flaky Cloud Logging client must
            # never silence the local log line, the on-disk record of truth.
            with contextlib.suppress(Exception):
                cloud_logging_sink(name, severity, fields)

    @contextmanager
    def run_session(
        *,
        trigger: str,
        args: dict | None = None,
        run_id: str | None = None,
    ) -> Iterator[None]:
        """Wrap a run — emit ``run.started`` / ``run.finished`` and flush JSONL.

        Reentrant: if a session for this ``worker_id`` is already active on the
        contextvar (e.g. a CLI callback opened one and the command opens another),
        join it as a no-op rather than emitting a second lifecycle pair or
        double-flushing.
        """
        buffers = _RUN_BUFFERS.get()
        if buffers is not None and worker_id in buffers:
            yield
            return

        rid = resolve_run_id(run_id)
        started_at = time.monotonic()
        buffer: list[dict] = []
        new_buffers = dict(buffers) if buffers is not None else {}
        new_buffers[worker_id] = buffer
        token = _RUN_BUFFERS.set(new_buffers)

        # Resolved once per session so run.started and run.finished agree.
        # Legacy ``cloud_run`` for runtime_env=None workers (xquill — wire
        # unchanged); truthful for workers that declared a runtime env.
        source = "cloud_run" if (runtime_env is None or _in_cloud_run()) else "local"

        event(
            "run.started",
            trigger=trigger,
            args=args or {},
            run_id=rid,
            contract_version="v0.1",
            source=source,
        )
        status, summary = "ok", ""
        try:
            yield
        except BaseException as exc:
            status = "error"
            summary = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            event(
                "run.finished",
                status=status,
                duration_ms=duration_ms,
                summary=summary,
                source=source,
            )
            _RUN_BUFFERS.reset(token)
            if _flush_allowed():
                flush_buffer(
                    buffer,
                    worker_id=worker_id,
                    run_id=rid,
                    bucket=bucket,
                    project=project,
                    storage_client_factory=storage_client_factory,
                    log=get_log(log_name),
                )
            else:
                get_log(log_name).debug(
                    "obs flush gated (%s != 'cloud_run', %s unset); %d events not uploaded",
                    runtime_env,
                    FORCE_FLUSH_ENV,
                    len(buffer),
                )

    return event, run_session
