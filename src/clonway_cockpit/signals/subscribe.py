"""Signal subscription read API — cursor-based polling over the dated archive.

The source of truth for consumers is the **dated archive**:
``signals/<worker>/<YYYY-MM-DD>/<run_id>.jsonl``. These objects are append-only
with stable names; ``latest.jsonl`` is the human/dashboard snapshot only and
MUST NOT be used as a cursor-based state source.

Two :class:`CursorStore` implementations are provided:

- :class:`FileCursorStore` — consumer-local state directory (the default for
  workers with a persistent ``.{worker}/`` state dir).
- :class:`GcsCursorStore` — shared bucket state at
  ``subscriptions/<consumer_id>/cursor.json``, for stateless Cloud Run consumers.

**At-least-once delivery.** The cursor is committed per-object after all signals
in that object are added to the delivery list. A crash *between* object read and
cursor commit yields re-delivery on the next :func:`poll`. Consumers MUST dedup
by ``(signal.dedup_key, signal.emitted_at)``.

**Fail-open.** On creds/offline errors :func:`poll` returns ``[]`` and logs at
debug (same ``_QUIET_ERROR_NAMES`` idiom as ``emit.py``). A cursor write failure
is also logged and leaves that object to be re-delivered — the delivery list
returned by the call still contains those signals.

**Single-writer assumption.** Two replicas using the same ``consumer_id`` will
double-process. The :class:`GcsCursorStore` generation-precondition narrows but
does not eliminate this window. Run one replica per ``consumer_id`` (Cloud Run
``min-instances=1`` jobs satisfy this today — re-verify at scale).

**Phase-B push trigger (doorbell design).** When bucket notifications arrive over
Pub/Sub, consumers receiving the notification should call :func:`poll` with the
same subscription — correctness never depends on Pub/Sub delivery (a missed
notification is healed by the next poll; a duplicate is absorbed by the cursor).
See ``docs/signal-bus.md`` for the Pub/Sub wiring recipe.

**What the bus does NOT deliver.** The archive only records *raised* signals
(non-empty emit runs). A signal that disappears from ``latest.jsonl`` never
generates a closure event in the archive. Consumers tracking open/closed state
must snapshot ``latest.jsonl`` directly or use the orchestrator's lifecycle
layer — that is out of scope here (Phase-C work).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from clonway_cockpit.signals.emit import _BUCKET, _QUIET_ERROR_NAMES
from clonway_cockpit.signals.model import Signal

_log = logging.getLogger(__name__)

# Urgency ladder — "info" is lowest, "overdue" is highest.
# min_urgency filtering excludes signals below the requested level.
_URGENCY_RANK: dict[str, int] = {"info": 0, "soon": 1, "due": 2, "overdue": 3}


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subscription:
    """What a consumer wants and who it is (namespaces the cursor).

    All filter fields are optional; ``None`` means "accept everything".
    ``workers=None`` triggers worker auto-discovery from the bucket (one
    list call per :func:`poll`).
    """

    consumer_id: str
    workers: tuple[str, ...] | None = None  # None = all emitters in the bucket
    kinds: tuple[str, ...] | None = None  # filter on Signal.kind
    min_urgency: str | None = None  # info < soon < due < overdue


@dataclass(frozen=True)
class Delivery:
    """One delivered Signal, enriched with provenance for audit and dedup."""

    signal: Signal
    emitted_by_run: str  # run_id segment of the archive object name
    object_path: str  # gs://<bucket>/<object> — stable per archive object


# ---------------------------------------------------------------------------
# CursorStore protocol + implementations
# ---------------------------------------------------------------------------


class CursorStore(Protocol):
    """Per-``(consumer_id, worker)`` high-water mark.

    The cursor value is the **object name** (``signals/<w>/<d>/<id>.jsonl``)
    of the last fully-processed archive object. :func:`poll` calls
    ``load`` once per worker at the start and ``save`` once per worker after
    all objects for that worker have been consumed.
    """

    def load(self, consumer_id: str, worker: str) -> str | None: ...

    def save(self, consumer_id: str, worker: str, cursor: str) -> None: ...


class FileCursorStore:
    """Cursor store backed by a single JSON file in a local state directory.

    The file is written atomically (tmp → rename) to avoid half-written state on
    crash. Workers already keep a ``.{worker}/`` state directory; pass that path
    as ``state_dir``.

    Not safe for concurrent use from multiple processes — one logical consumer
    per ``consumer_id``, one writer at a time.
    """

    def __init__(self, state_dir: Path | str) -> None:
        self._path = Path(state_dir) / "signal_cursors.json"

    def _read(self) -> dict[str, str]:
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(self._path)

    @staticmethod
    def _key(consumer_id: str, worker: str) -> str:
        # NUL separator is never valid in either field.
        return f"{consumer_id}\x00{worker}"

    def load(self, consumer_id: str, worker: str) -> str | None:
        return self._read().get(self._key(consumer_id, worker))

    def save(self, consumer_id: str, worker: str, cursor: str) -> None:
        data = self._read()
        data[self._key(consumer_id, worker)] = cursor
        self._write(data)


class GcsCursorStore:
    """Cursor store backed by GCS for stateless Cloud Run consumers.

    Cursors are stored as a single JSON object at
    ``subscriptions/<consumer_id>/cursor.json`` in the signals bucket. Writes
    use a generation-match precondition to detect concurrent writers — a
    ``PreconditionFailed`` error is logged and re-raised so the caller can retry
    or accept re-delivery on the next :func:`poll`.

    Single-writer assumption: two replicas sharing a ``consumer_id`` will race on
    writes. The precondition narrows (but does not eliminate) the double-process
    window. Use ``min-instances=1`` Cloud Run jobs to enforce single-writer.
    """

    def __init__(
        self,
        consumer_id: str,
        *,
        bucket: str = _BUCKET,
        storage_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._consumer_id = consumer_id
        self._bucket = bucket
        self._factory = storage_client_factory

    def _obj_name(self) -> str:
        return f"subscriptions/{self._consumer_id}/cursor.json"

    def _client(self) -> Any:
        if self._factory is not None:
            return self._factory()
        from google.cloud import storage  # noqa: PLC0415 — lazy import

        return storage.Client()

    def _get(self) -> tuple[dict[str, str], int | None]:
        """Return (cursor dict, blob generation). ({}, None) if object absent."""
        client = self._client()
        blob = client.bucket(self._bucket).blob(self._obj_name())
        try:
            text = blob.download_as_text()
            data: dict[str, str] = json.loads(text)
            return data, blob.generation
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "NotFound":
                return {}, None
            raise

    @staticmethod
    def _key(consumer_id: str, worker: str) -> str:
        return f"{consumer_id}\x00{worker}"

    def load(self, consumer_id: str, worker: str) -> str | None:
        try:
            data, _ = self._get()
            return data.get(self._key(consumer_id, worker))
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ in _QUIET_ERROR_NAMES:
                _log.debug("GcsCursorStore.load skipped (%s)", type(exc).__name__)
                return None
            _log.exception("GcsCursorStore.load failed")
            return None

    def save(self, consumer_id: str, worker: str, cursor: str) -> None:
        try:
            data, generation = self._get()
            data[self._key(consumer_id, worker)] = cursor
            client = self._client()
            blob = client.bucket(self._bucket).blob(self._obj_name())
            # if_generation_match=0 means "create only if not yet exists".
            # For an existing object, the actual generation enforces single-writer.
            precondition = 0 if generation is None else generation
            blob.upload_from_string(
                json.dumps(data, separators=(",", ":")),
                content_type="application/json",
                if_generation_match=precondition,
            )
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if name in _QUIET_ERROR_NAMES:
                _log.debug("GcsCursorStore.save skipped (%s)", name)
                return
            _log.exception("GcsCursorStore.save failed (%s)", name)
            raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _discover_workers(bucket_obj: Any) -> list[str]:
    """List distinct worker names from archive objects under ``signals/``."""
    seen: set[str] = set()
    for blob in bucket_obj.list_blobs(prefix="signals/"):
        parts = blob.name.split("/")
        # Expect: signals/<worker>/<date>/<run_id>.jsonl (4 parts minimum)
        if len(parts) >= 4 and parts[-1].endswith(".jsonl"):
            seen.add(parts[1])
    return sorted(seen)


def _archive_objects_after(
    bucket_obj: Any,
    *,
    worker: str,
    cursor: str | None,
) -> list[str]:
    """Sorted archive object names for ``worker`` strictly after ``cursor``.

    Uses ``start_offset`` to skip the date prefix before the cursor (risk note:
    listing grows with archive depth — revisit when a retention policy is set on
    the bucket).
    """
    prefix = f"signals/{worker}/"
    # start_offset is the cursor itself (inclusive); we skip it below.
    start = cursor if cursor is not None else prefix
    names = sorted(
        blob.name
        for blob in bucket_obj.list_blobs(prefix=prefix, start_offset=start)
        if blob.name.endswith(".jsonl") and len(blob.name.split("/")) == 4
    )
    # start_offset is inclusive — skip the cursor object itself (already processed).
    if cursor is not None and names and names[0] == cursor:
        names = names[1:]
    return names


def _read_signals(bucket_obj: Any, obj_name: str) -> list[Signal]:
    """Download and deserialise one NDJSON archive object into Signals."""
    try:
        text = bucket_obj.blob(obj_name).download_as_text()
    except Exception:  # noqa: BLE001
        _log.debug("could not download archive object %s", obj_name)
        return []
    out: list[Signal] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            out.append(Signal.from_wire(json.loads(line)))
        except Exception:  # noqa: BLE001
            _log.debug("skipping malformed signal line in %s", obj_name)
    return out


def _matches(signal: Signal, sub: Subscription) -> bool:
    if sub.kinds is not None and signal.kind not in sub.kinds:
        return False
    if sub.min_urgency is not None:
        min_rank = _URGENCY_RANK.get(sub.min_urgency, 0)
        sig_rank = _URGENCY_RANK.get(signal.urgency, 0)
        if sig_rank < min_rank:
            return False
    return True


def _run_id_from_path(obj_name: str) -> str:
    """``signals/<w>/<d>/<run_id>.jsonl`` → ``<run_id>``."""
    stem = obj_name.rsplit("/", 1)[-1]
    return stem.removesuffix(".jsonl")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def poll(
    sub: Subscription,
    *,
    cursor_store: CursorStore,
    bucket: str = _BUCKET,
    storage_client_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
) -> list[Delivery]:
    """Return new :class:`Delivery` items since the last cursor, or ``[]`` on error.

    **Ordering.** Deliveries within a worker are in object-name order (chronological
    for ISO-date archive prefixes). Workers iterate in the order given by
    ``sub.workers`` (or discovery order when ``workers=None``).

    **Cursor discipline.** The cursor advances per-object, inside :func:`poll`,
    after all signals in that object are added to the result list. If
    ``cursor_store.save`` raises, that object will be re-delivered on the next
    call — handle duplicates by deduping on ``(signal.dedup_key, signal.emitted_at)``.

    **Fail-open.** Returns ``[]`` (never raises) on GCS creds/offline errors or
    when worker discovery fails.
    """
    _ = now  # accepted for API symmetry with emit; not needed here

    def _default_factory() -> Any:
        from google.cloud import storage  # noqa: PLC0415 — lazy import

        return storage.Client()

    factory = storage_client_factory or _default_factory
    try:
        client = factory()
        bkt = client.bucket(bucket)
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ in _QUIET_ERROR_NAMES:
            _log.debug("signal poll skipped (%s)", type(exc).__name__)
        else:
            _log.exception("signal poll: client init failed")
        return []

    workers: tuple[str, ...] | None = sub.workers
    if workers is None:
        try:
            workers = tuple(_discover_workers(bkt))
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ in _QUIET_ERROR_NAMES:
                _log.debug("signal poll: worker discovery skipped (%s)", type(exc).__name__)
            else:
                _log.exception("signal poll: worker discovery failed")
            return []

    deliveries: list[Delivery] = []
    for worker in workers:
        cursor = cursor_store.load(sub.consumer_id, worker)
        try:
            obj_names = _archive_objects_after(bkt, worker=worker, cursor=cursor)
        except Exception:  # noqa: BLE001
            _log.exception("signal poll: listing failed for worker %s", worker)
            continue
        for obj_name in obj_names:
            signals = _read_signals(bkt, obj_name)
            run_id = _run_id_from_path(obj_name)
            for s in signals:
                if _matches(s, sub):
                    deliveries.append(
                        Delivery(
                            signal=s,
                            emitted_by_run=run_id,
                            object_path=f"gs://{bucket}/{obj_name}",
                        )
                    )
            # Advance cursor per-object. Failure here means re-delivery of this
            # object on the next poll — at-least-once guarantee.
            try:
                cursor_store.save(sub.consumer_id, worker, obj_name)
            except Exception:  # noqa: BLE001
                _log.exception(
                    "cursor save failed for %s/%s — object will be re-delivered",
                    sub.consumer_id,
                    worker,
                )

    return deliveries
