"""Shared Signal emitter — the one best-effort GCS flush the whole fleet uses.

Extracted from four near-identical worker ``emit.py`` files (xbook / xhr /
xletter / xquill). A worker keeps a ~10-line ``signals/emit.py`` wrapper that
supplies its ``worker_id``, flag name, and a pure ``build(today=, now=)`` and
delegates the rest here. The wire shape, paths, run_id resolution, and degrade
behaviour are identical to the originals, so a migrated worker is byte-identical
on the wire.

Behaviour (mirrors ``obs.py``'s GCS flush idiom):

* Flag-guarded (``<WORKER>_EMIT_SIGNALS``, truthy ``{1,true,yes,on}``, default
  off). Gated up front — zero work, no client, no build call when off.
* Writes the open set to ``signals/<worker>/latest.jsonl`` every run, even when
  empty, so a now-quiet worker clears its previously-raised set (the read model
  for the Fleet Cockpit / morning briefing).
* Writes a dated archive ``signals/<worker>/<YYYY-MM-DD>/<run_id>.jsonl`` only
  when the set is non-empty (append-only history; mirrors obs's empty-buffer
  no-op).
* Best-effort: a creds-less / offline / quota-throttled environment never crashes
  a cockpit launch or a scheduled run. A failed upload is logged once at warning
  (exception type and object path only) and reported on the returned
  :class:`EmitResult`.
* No built-in bucket: the bucket is the ``bucket=`` argument, else
  ``CLONWAY_FLEET_BUCKET``, else none (nothing is uploaded; see
  :mod:`clonway_cockpit.fleet_bucket`).

``google-cloud-storage`` is NOT a dependency of clonway-cockpit — the import is
lazy (only the workers, which already depend on it, hit the default factory).
Tests inject a fake client via ``storage_client_factory``.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from datetime import date as Date
from typing import Any

from clonway_cockpit.fleet_bucket import (
    FleetStorageOutcome,
    note_failure,
    note_unconfigured,
    resolve_fleet_bucket,
)
from clonway_cockpit.signals.model import Signal

_TRUTHY = {"1", "true", "yes", "on"}

class EmitResult(tuple[Signal, ...]):
    """The signals :func:`emit_signals` built, plus what happened to the upload.

    It is a plain tuple of :class:`Signal` for every existing caller (equality, length,
    iteration and indexing are unchanged). ``outcome`` is a
    :class:`~clonway_cockpit.fleet_bucket.FleetStorageOutcome`: ``OK`` (uploaded),
    ``DISABLED`` (the worker's flag is off), ``NOT_CONFIGURED`` (no bucket argument and no
    ``CLONWAY_FLEET_BUCKET``; nothing uploaded) or ``FAILED`` (the build or the upload
    failed; see the warning log line).
    """

    outcome: FleetStorageOutcome

    def __new__(
        cls, signals: Sequence[Signal] = (), outcome: FleetStorageOutcome = FleetStorageOutcome.OK
    ) -> EmitResult:
        self = super().__new__(cls, signals)
        self.outcome = outcome
        return self


def flag_enabled(env_var: str) -> bool:
    """True iff ``env_var`` is set to a truthy value (``{1,true,yes,on}``,
    case-insensitive, surrounding whitespace ignored). Default off."""
    return os.environ.get(env_var, "").strip().lower() in _TRUTHY


def _import_storage() -> Any:
    """Lazily import ``google.cloud.storage``. Kept behind a function so (a)
    clonway-cockpit needs no google dependency and (b) tests can monkeypatch it."""
    from google.cloud import storage

    return storage


def _default_factory(project: str | None) -> Callable[[], Any]:
    def factory() -> Any:
        storage = _import_storage()
        # Faithful to the originals: bare Client() for Cloud Run workers (project
        # resolves from the runtime), explicit project= for xquill's launchd
        # daemon whose HOME-only env can't resolve a project otherwise.
        return storage.Client(project=project) if project else storage.Client()

    return factory


def emit_signals(
    *,
    worker_id: str,
    flag_env: str,
    build: Callable[..., Sequence[Signal]],
    bucket: str | None = None,
    project: str | None = None,
    now: datetime | None = None,
    today: Date | None = None,
    run_id: str | None = None,
    storage_client_factory: Callable[[], Any] | None = None,
) -> EmitResult:
    """Build this worker's open Signals and flush them to GCS, best-effort.

    Flag-gated up front: returns an empty result (outcome ``DISABLED``) with zero
    work when ``flag_env`` is off (no build call, no client). Otherwise calls ``build(today=, now=)`` for the
    open set, writes ``latest.jsonl`` (overwritten every run, including empty)
    plus a dated archive (only when non-empty), and returns the built tuple.

    Degrades to whatever it managed to build on any failure — a build error
    returns an empty result; a GCS write error returns the built signals but skips
    the upload; both carry outcome ``FAILED``. With no bucket configured the
    signals are built and returned but nothing is uploaded (``NOT_CONFIGURED``).
    Never raises: signals are observability, never break worker logic.

    ``project`` / ``storage_client_factory`` cover xquill's project-pinned
    client and test injection respectively.
    """
    if not flag_enabled(flag_env):
        return EmitResult((), FleetStorageOutcome.DISABLED)

    log = logging.getLogger(f"{worker_id}.signals")
    try:
        now = now or datetime.now(UTC)
        today = today or now.astimezone(UTC).date()
        run_id = run_id or os.environ.get("CLOUD_RUN_EXECUTION")
        signals = tuple(build(today=today, now=now))
    except Exception:  # noqa: BLE001 — never crash a cockpit launch / scheduled run
        log.exception("scan_and_emit failed")
        return EmitResult((), FleetStorageOutcome.FAILED)

    outcome = _flush(
        signals,
        worker_id=worker_id,
        bucket=resolve_fleet_bucket(bucket),
        project=project,
        now=now,
        run_id=run_id,
        factory=storage_client_factory or _default_factory(project),
        log=log,
    )
    return EmitResult(signals, outcome)


def _flush(
    signals: tuple[Signal, ...],
    *,
    worker_id: str,
    bucket: str | None,
    project: str | None,
    now: datetime,
    run_id: str | None,
    factory: Callable[[], Any],
    log: logging.Logger,
) -> FleetStorageOutcome:
    """Upload ``signals`` to GCS. Always overwrites the latest snapshot (even
    empty); writes a dated archive only when non-empty. Returns the outcome;
    swallows every error (auth/quota/transient/offline) after one warning."""
    if bucket is None:
        note_unconfigured(log)
        return FleetStorageOutcome.NOT_CONFIGURED
    path = f"signals/{worker_id}/latest.jsonl"
    try:
        gcs = factory().bucket(bucket)
        body = "".join(json.dumps(s.to_wire(), separators=(",", ":")) + "\n" for s in signals)
        gcs.blob(path).upload_from_string(
            body, content_type="application/x-ndjson"
        )
        if signals:
            date = now.astimezone(UTC).date().isoformat()
            rid = run_id or uuid.uuid4().hex
            path = f"signals/{worker_id}/{date}/{rid}.jsonl"
            gcs.blob(path).upload_from_string(
                body, content_type="application/x-ndjson"
            )
        return FleetStorageOutcome.OK
    except Exception as exc:  # noqa: BLE001 — observability must never break worker logic
        note_failure(log, exc, f"gs://{bucket}/{path}")
        return FleetStorageOutcome.FAILED
