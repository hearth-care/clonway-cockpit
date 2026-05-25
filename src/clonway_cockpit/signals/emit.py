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
* Best-effort: a creds-less / offline / quota-throttled environment degrades
  silently, never crashing a cockpit launch or a scheduled run.

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

from clonway_cockpit.signals.model import Signal

_BUCKET = "clonway-orchestrator-eu-west2"  # shared fleet bucket (mirrors obs._BUCKET)
_TRUTHY = {"1", "true", "yes", "on"}

# google auth/forbidden error class names — matched by name so this module never
# has to import google packages clonway-cockpit doesn't depend on. A match logs
# at debug (expected when creds are absent); anything else logs at exception.
_QUIET_ERROR_NAMES = {"Forbidden", "GoogleAuthError", "DefaultCredentialsError"}


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
    bucket: str = _BUCKET,
    project: str | None = None,
    now: datetime | None = None,
    today: Date | None = None,
    run_id: str | None = None,
    storage_client_factory: Callable[[], Any] | None = None,
) -> tuple[Signal, ...]:
    """Build this worker's open Signals and flush them to GCS, best-effort.

    Flag-gated up front: returns ``()`` with zero work when ``flag_env`` is off
    (no build call, no client). Otherwise calls ``build(today=, now=)`` for the
    open set, writes ``latest.jsonl`` (overwritten every run, including empty)
    plus a dated archive (only when non-empty), and returns the built tuple.

    Degrades to whatever it managed to build on any failure — a build error
    returns ``()``; a GCS write error returns the built signals but skips the
    upload. Never raises: signals are observability, never break worker logic.

    ``project`` / ``storage_client_factory`` cover xquill's project-pinned
    client and test injection respectively.
    """
    if not flag_enabled(flag_env):
        return ()

    log = logging.getLogger(f"{worker_id}.signals")
    try:
        now = now or datetime.now(UTC)
        today = today or now.astimezone(UTC).date()
        run_id = run_id or os.environ.get("CLOUD_RUN_EXECUTION")
        signals = tuple(build(today=today, now=now))
    except Exception:  # noqa: BLE001 — never crash a cockpit launch / scheduled run
        log.exception("scan_and_emit failed")
        return ()

    _flush(
        signals,
        worker_id=worker_id,
        bucket=bucket,
        project=project,
        now=now,
        run_id=run_id,
        factory=storage_client_factory or _default_factory(project),
        log=log,
    )
    return signals


def _flush(
    signals: tuple[Signal, ...],
    *,
    worker_id: str,
    bucket: str,
    project: str | None,
    now: datetime,
    run_id: str | None,
    factory: Callable[[], Any],
    log: logging.Logger,
) -> bool:
    """Upload ``signals`` to GCS. Always overwrites the latest snapshot (even
    empty); writes a dated archive only when non-empty. Returns ``True`` only on
    a clean flush; swallows every error (auth/quota/transient/offline)."""
    try:
        gcs = factory().bucket(bucket)
        body = "".join(json.dumps(s.to_wire(), separators=(",", ":")) + "\n" for s in signals)
        gcs.blob(f"signals/{worker_id}/latest.jsonl").upload_from_string(
            body, content_type="application/x-ndjson"
        )
        if signals:
            date = now.astimezone(UTC).date().isoformat()
            rid = run_id or uuid.uuid4().hex
            gcs.blob(f"signals/{worker_id}/{date}/{rid}.jsonl").upload_from_string(
                body, content_type="application/x-ndjson"
            )
        return True
    except Exception as exc:  # noqa: BLE001 — observability must never break worker logic
        if type(exc).__name__ in _QUIET_ERROR_NAMES:
            log.debug("signal emit skipped (%s)", type(exc).__name__)
        else:
            log.exception("signal emit failed")
        return False
