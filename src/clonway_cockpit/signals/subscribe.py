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
in that object are processed. Pass ``on_delivery=...`` to have :func:`poll`
invoke your consumer callback before committing the object cursor; a callback
exception yields re-delivery on the next :func:`poll`. Consumers MUST dedup by
``(signal.dedup_key, signal.emitted_at)``.

**Fail-open.** On creds/offline errors :func:`poll` returns ``[]`` and logs at
debug (same ``_QUIET_ERROR_NAMES`` idiom as ``emit.py``). A cursor write failure
or ``on_delivery`` exception is also logged and leaves that object to be
re-delivered — the delivery list returned by the call still contains those
signals for audit/debug.

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

    The cursor value is an **opaque token** the store round-trips verbatim — do
    not parse it. (It encodes the latest date reached plus the run_ids already
    processed in that date; see :func:`_decode_cursor` for why a bare object name
    is unsafe with non-monotonic run_ids.) :func:`poll` calls ``load`` once per
    worker at the start and ``save`` per object as it advances the mark.
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


class _ArchiveReadError(Exception):
    """Archive object was listed but could not be downloaded."""


def _discover_workers(bucket_obj: Any) -> list[str]:
    """List distinct worker names from archive objects under ``signals/``."""
    seen: set[str] = set()
    for blob in bucket_obj.list_blobs(prefix="signals/"):
        parts = blob.name.split("/")
        # Expect: signals/<worker>/<date>/<run_id>.jsonl (4 parts minimum)
        if len(parts) >= 4 and parts[-1].endswith(".jsonl"):
            seen.add(parts[1])
    return sorted(seen)


def _date_from_path(obj_name: str) -> str:
    """``signals/<w>/<date>/<run_id>.jsonl`` → ``<date>``."""
    return obj_name.split("/")[-2]


def _decode_cursor(cursor: str | None) -> tuple[str | None, set[str]]:
    """Decode a stored cursor into ``(active_date, processed_run_ids)``.

    The cursor is the high-water mark per ``(consumer, worker)``. Because archive
    object names end in a **non-monotonic** ``run_id`` (``uuid4`` / Cloud Run
    ``<job>-<random>`` execution suffix), object-name order within a single date
    is NOT emission order — so a bare last-object-name high-water mark would skip
    any later same-day emission whose name sorts before it. Instead the cursor
    carries the latest date reached plus the set of run_ids already processed
    *within that date*; everything in strictly-earlier dates is implicitly done.

    Two on-wire forms are accepted:

    - the current JSON form ``{"d": "<date>", "s": ["<run_id>", ...]}``; and
    - a legacy bare object name ``signals/<w>/<date>/<run_id>.jsonl`` (decoded as
      that object's date + its single run_id), so older persisted cursors resume.
    """
    if cursor is None:
        return None, set()
    try:
        obj = json.loads(cursor)
    except (ValueError, TypeError):
        obj = None
    if isinstance(obj, dict) and "d" in obj:
        return str(obj["d"]), {str(r) for r in obj.get("s", [])}
    # Legacy bare object name.
    return _date_from_path(cursor), {_run_id_from_path(cursor)}


def _encode_cursor(date: str, processed: set[str]) -> str:
    """Encode ``(active_date, processed_run_ids)`` into the stored cursor string."""
    return json.dumps({"d": date, "s": sorted(processed)}, separators=(",", ":"))


def _archive_objects_after(
    bucket_obj: Any,
    *,
    worker: str,
    cursor: str | None,
) -> list[str]:
    """Sorted archive object names for ``worker`` not yet processed per ``cursor``.

    Listing starts at the cursor's **date prefix** (``signals/<w>/<date>/``), not
    the full cursor object name, so same-date objects emitted *after* the cursor
    but with a lexically-smaller ``run_id`` are still listed (run_ids are
    non-monotonic — see :func:`_decode_cursor`). Already-processed objects are
    then filtered out: anything in a strictly-earlier date, and any run_id already
    recorded in the active date's processed set.

    Risk note: listing grows with archive depth within the active date — revisit
    when a retention policy is set on the bucket.
    """
    prefix = f"signals/{worker}/"
    active_date, processed = _decode_cursor(cursor)
    # Anchor the listing at the active date's prefix (ISO dates sort
    # chronologically, so this safely skips every fully-processed earlier date).
    start = f"{prefix}{active_date}/" if active_date is not None else prefix
    names = sorted(
        blob.name
        for blob in bucket_obj.list_blobs(prefix=prefix, start_offset=start)
        if blob.name.endswith(".jsonl") and len(blob.name.split("/")) == 4
    )
    out: list[str] = []
    for name in names:
        date = _date_from_path(name)
        if active_date is not None:
            if date < active_date:
                continue  # defensive — start_offset already excludes these
            if date == active_date and _run_id_from_path(name) in processed:
                continue  # already processed within the active date
        out.append(name)
    return out


def _read_signals(bucket_obj: Any, obj_name: str) -> list[Signal]:
    """Download and deserialise one NDJSON archive object into Signals."""
    try:
        text = bucket_obj.blob(obj_name).download_as_text()
    except Exception as exc:  # noqa: BLE001
        _log.debug("could not download archive object %s", obj_name)
        raise _ArchiveReadError(obj_name) from exc
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
    on_delivery: Callable[[Delivery], None] | None = None,
    now: datetime | None = None,
) -> list[Delivery]:
    """Return new :class:`Delivery` items since the last cursor, or ``[]`` on error.

    **Ordering.** Deliveries within a worker are in object-name order — chronological
    *across* ISO-date prefixes, but not within a single date (the trailing ``run_id``
    is non-monotonic, so intra-date order is not emission order; don't rely on it for
    causality). Delivery is still complete: no same-date object is skipped (the cursor
    lists from the date prefix and tracks processed run_ids). Workers iterate in the
    order given by ``sub.workers`` (or discovery order when ``workers=None``).

    **Cursor discipline.** The cursor advances per-object, inside :func:`poll`,
    after all matching signals in that object are collected or processed. If
    ``on_delivery`` is provided, it is called for each matching delivery before
    the cursor advances; a callback exception leaves that object uncommitted for
    re-delivery on the next call. If ``cursor_store.save`` raises, that object
    will also be re-delivered — handle duplicates by deduping on
    ``(signal.dedup_key, signal.emitted_at)``.

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
        active_date, processed = _decode_cursor(cursor)
        for obj_name in obj_names:
            try:
                signals = _read_signals(bkt, obj_name)
            except _ArchiveReadError:
                break
            run_id = _run_id_from_path(obj_name)
            callback_failed = False
            for s in signals:
                if _matches(s, sub):
                    delivery = Delivery(
                        signal=s,
                        emitted_by_run=run_id,
                        object_path=f"gs://{bucket}/{obj_name}",
                    )
                    deliveries.append(delivery)
                    if on_delivery is not None:
                        try:
                            on_delivery(delivery)
                        except Exception:  # noqa: BLE001
                            _log.exception(
                                "signal poll: consumer callback failed for %s",
                                obj_name,
                            )
                            callback_failed = True
                            break
            if callback_failed:
                break
            # Advance the cursor per-object: record this object's date + run_id in
            # the high-water mark. A later same-date object with a lexically-smaller
            # run_id is still found next poll (date-prefix listing + processed set);
            # crossing into a newer date resets the processed set. Failure here means
            # re-delivery of this object on the next poll — at-least-once guarantee.
            obj_date = _date_from_path(obj_name)
            if active_date is None or obj_date > active_date:
                active_date, processed = obj_date, {run_id}
            else:  # same date as the active cursor — accumulate
                processed = processed | {run_id}
            try:
                cursor_store.save(sub.consumer_id, worker, _encode_cursor(active_date, processed))
            except Exception:  # noqa: BLE001
                _log.exception(
                    "cursor save failed for %s/%s — object will be re-delivered",
                    sub.consumer_id,
                    worker,
                )

    return deliveries
