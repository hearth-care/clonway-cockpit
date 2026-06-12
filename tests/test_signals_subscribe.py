"""CC-SIG-SUB-* — subscription read API tests (FileCursorStore + poll).

GcsCursorStore is covered separately in test_signals_subscribe_gcs.py.
The GCS client is injected via ``storage_client_factory`` — no network,
no google-cloud-storage dependency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as Date
from pathlib import Path

from clonway_cockpit.signals.emit import emit_signals
from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.signals.subscribe import (
    FileCursorStore,
    Subscription,
    _archive_objects_after,
    _decode_cursor,
    _discover_workers,
    _matches,
    _run_id_from_path,
    poll,
)
from clonway_cockpit.state import NeedsItem

_NOW = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)
_TODAY = Date(2026, 6, 1)
_BUCKET = "test-bucket"


# ---------------------------------------------------------------------------
# Fake GCS client
# ---------------------------------------------------------------------------


class _FakeBlob:
    def __init__(self, store: dict[str, str], name: str) -> None:
        self._store = store
        self.name = name

    def upload_from_string(self, body: str, content_type: str | None = None, **kwargs) -> None:
        self._store[self.name] = body

    def download_as_text(self) -> str:
        if self.name not in self._store:
            raise _FakeNotFound(self.name)
        return self._store[self.name]


class _FakeNotFound(Exception):
    """Stands in for google.api_core.exceptions.NotFound."""

    pass


class _FakeBucket:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)

    def list_blobs(self, prefix: str = "", start_offset: str = "") -> list[_FakeBlob]:
        result = []
        for name in sorted(self._store):
            if not name.startswith(prefix):
                continue
            if start_offset and name < start_offset:
                continue
            result.append(_FakeBlob(self._store, name))
        return result


class _FakeClient:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


class _BoomClient:
    """Raises on bucket() — simulates creds absent."""

    def bucket(self, name: str) -> _FakeBucket:
        raise _FakeAuthError("no creds")


class _FakeAuthError(Exception):
    pass


_FakeAuthError.__name__ = "GoogleAuthError"  # match _QUIET_ERROR_NAMES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    worker: str = "xbook",
    title: str = "Bills due this week",
    urgency: str | None = None,
    kind: str | None = None,
    source_id: str | None = "bill-42",
    now: datetime = _NOW,
) -> Signal:
    need = NeedsItem(title, "detail", "warn", "cap-key", "focus", None, source_id)
    s = build_signals((need,), now=now, worker=worker)[0]
    if urgency is not None or kind is not None:
        from dataclasses import replace

        s = replace(s, urgency=urgency or s.urgency, kind=kind or s.kind)
    return s


def _write_archive(
    store: dict[str, str], worker: str, date: str, run_id: str, signals: list[Signal]
) -> str:
    """Serialize signals into an archive object in the fake store. Returns the object name."""
    obj = f"signals/{worker}/{date}/{run_id}.jsonl"
    body = "".join(json.dumps(s.to_wire(), separators=(",", ":")) + "\n" for s in signals)
    store[obj] = body
    return obj


# ---------------------------------------------------------------------------
# _run_id_from_path
# ---------------------------------------------------------------------------


def test_run_id_from_path():  # CC-SIG-SUB-HELPER-1
    assert _run_id_from_path("signals/xbook/2026-06-01/exec-abc.jsonl") == "exec-abc"
    assert _run_id_from_path("signals/xhr/2026-06-01/uuid123.jsonl") == "uuid123"


# ---------------------------------------------------------------------------
# _matches — filter logic
# ---------------------------------------------------------------------------


def test_matches_no_filters():  # CC-SIG-SUB-MATCH-1
    sub = Subscription(consumer_id="xbook")
    assert _matches(_make_signal(), sub) is True


def test_matches_kind_filter_accepts():  # CC-SIG-SUB-MATCH-2
    sub = Subscription(consumer_id="xbook", kinds=("deadline.approaching",))
    s = _make_signal(kind="deadline.approaching")
    assert _matches(s, sub) is True


def test_matches_kind_filter_rejects():  # CC-SIG-SUB-MATCH-3
    sub = Subscription(consumer_id="xbook", kinds=("anomaly.detected",))
    s = _make_signal(kind="deadline.approaching")
    assert _matches(s, sub) is False


def test_matches_min_urgency_accepts_equal():  # CC-SIG-SUB-MATCH-4
    sub = Subscription(consumer_id="xbook", min_urgency="due")
    s = _make_signal(urgency="due")
    assert _matches(s, sub) is True


def test_matches_min_urgency_accepts_higher():  # CC-SIG-SUB-MATCH-5
    sub = Subscription(consumer_id="xbook", min_urgency="due")
    s = _make_signal(urgency="overdue")
    assert _matches(s, sub) is True


def test_matches_min_urgency_rejects_lower():  # CC-SIG-SUB-MATCH-6
    sub = Subscription(consumer_id="xbook", min_urgency="due")
    s = _make_signal(urgency="soon")
    assert _matches(s, sub) is False


def test_matches_min_urgency_info_accepts_all():  # CC-SIG-SUB-MATCH-7
    sub = Subscription(consumer_id="xbook", min_urgency="info")
    for urgency in ("info", "soon", "due", "overdue"):
        assert _matches(_make_signal(urgency=urgency), sub) is True


# ---------------------------------------------------------------------------
# _discover_workers
# ---------------------------------------------------------------------------


def test_discover_workers_empty():  # CC-SIG-SUB-DISC-1
    client = _FakeClient()
    bkt = client.bucket("test-bucket")
    assert _discover_workers(bkt) == []


def test_discover_workers_multiple():  # CC-SIG-SUB-DISC-2
    client = _FakeClient()
    store = client._store
    _write_archive(store, "xbook", "2026-06-01", "r1", [_make_signal(worker="xbook")])
    _write_archive(store, "xhr", "2026-06-01", "r1", [_make_signal(worker="xhr")])
    _write_archive(store, "xbook", "2026-06-02", "r2", [_make_signal(worker="xbook")])
    bkt = client.bucket("test-bucket")
    workers = _discover_workers(bkt)
    assert set(workers) == {"xbook", "xhr"}
    assert workers == sorted(workers)  # sorted


def test_discover_workers_ignores_latest():  # CC-SIG-SUB-DISC-3
    client = _FakeClient()
    client._store["signals/xbook/latest.jsonl"] = ""
    bkt = client.bucket("test-bucket")
    # latest.jsonl has only 3 path segments, so it's ignored
    assert _discover_workers(bkt) == []


# ---------------------------------------------------------------------------
# _archive_objects_after
# ---------------------------------------------------------------------------


def test_archive_objects_after_no_cursor():  # CC-SIG-SUB-LIST-1
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal()])
    _write_archive(client._store, "xbook", "2026-06-02", "r2", [_make_signal()])
    bkt = client.bucket("test-bucket")
    names = _archive_objects_after(bkt, worker="xbook", cursor=None)
    assert names == [
        "signals/xbook/2026-06-01/r1.jsonl",
        "signals/xbook/2026-06-02/r2.jsonl",
    ]


def test_archive_objects_after_with_cursor():  # CC-SIG-SUB-LIST-2
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal()])
    _write_archive(client._store, "xbook", "2026-06-02", "r2", [_make_signal()])
    _write_archive(client._store, "xbook", "2026-06-03", "r3", [_make_signal()])
    bkt = client.bucket("test-bucket")
    names = _archive_objects_after(bkt, worker="xbook", cursor="signals/xbook/2026-06-01/r1.jsonl")
    assert names == [
        "signals/xbook/2026-06-02/r2.jsonl",
        "signals/xbook/2026-06-03/r3.jsonl",
    ]


def test_archive_objects_after_cursor_is_last():  # CC-SIG-SUB-LIST-3
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal()])
    bkt = client.bucket("test-bucket")
    names = _archive_objects_after(bkt, worker="xbook", cursor="signals/xbook/2026-06-01/r1.jsonl")
    assert names == []


def test_archive_objects_skips_latest_jsonl():  # CC-SIG-SUB-LIST-4
    client = _FakeClient()
    client._store["signals/xbook/latest.jsonl"] = ""
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal()])
    bkt = client.bucket("test-bucket")
    names = _archive_objects_after(bkt, worker="xbook", cursor=None)
    assert names == ["signals/xbook/2026-06-01/r1.jsonl"]


# ---------------------------------------------------------------------------
# FileCursorStore
# ---------------------------------------------------------------------------


def test_file_cursor_store_load_missing(tmp_path: Path):  # CC-SIG-SUB-CS-1
    cs = FileCursorStore(tmp_path)
    assert cs.load("xbook", "xbook") is None


def test_file_cursor_store_roundtrip(tmp_path: Path):  # CC-SIG-SUB-CS-2
    cs = FileCursorStore(tmp_path)
    cs.save("xbook", "xbook", "signals/xbook/2026-06-01/r1.jsonl")
    assert cs.load("xbook", "xbook") == "signals/xbook/2026-06-01/r1.jsonl"


def test_file_cursor_store_multiple_workers(tmp_path: Path):  # CC-SIG-SUB-CS-3
    cs = FileCursorStore(tmp_path)
    cs.save("consumer", "xbook", "signals/xbook/2026-06-01/r1.jsonl")
    cs.save("consumer", "xhr", "signals/xhr/2026-06-02/r2.jsonl")
    assert cs.load("consumer", "xbook") == "signals/xbook/2026-06-01/r1.jsonl"
    assert cs.load("consumer", "xhr") == "signals/xhr/2026-06-02/r2.jsonl"


def test_file_cursor_store_save_is_idempotent(tmp_path: Path):  # CC-SIG-SUB-CS-4
    cs = FileCursorStore(tmp_path)
    cs.save("c", "w", "obj-1")
    cs.save("c", "w", "obj-2")
    assert cs.load("c", "w") == "obj-2"


def test_file_cursor_store_creates_parent_dir(tmp_path: Path):  # CC-SIG-SUB-CS-5
    state_dir = tmp_path / "nested" / "state"
    cs = FileCursorStore(state_dir)
    cs.save("c", "w", "obj-1")
    assert cs.load("c", "w") == "obj-1"


# ---------------------------------------------------------------------------
# poll() — core semantics
# ---------------------------------------------------------------------------


def test_poll_returns_empty_when_no_objects(tmp_path: Path):  # CC-SIG-SUB-POLL-1
    client = _FakeClient()
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert result == []


def test_poll_delivers_signals_in_order(tmp_path: Path):  # CC-SIG-SUB-POLL-2
    client = _FakeClient()
    s1 = _make_signal(source_id="a")
    s2 = _make_signal(source_id="b")
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [s1])
    _write_archive(client._store, "xbook", "2026-06-02", "r2", [s2])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(result) == 2
    assert result[0].signal.source_id == "a"
    assert result[1].signal.source_id == "b"
    assert result[0].emitted_by_run == "r1"
    assert result[1].emitted_by_run == "r2"
    assert result[0].object_path == f"gs://{_BUCKET}/signals/xbook/2026-06-01/r1.jsonl"


def test_poll_advances_cursor_after_each_object(tmp_path: Path):  # CC-SIG-SUB-POLL-3
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal(source_id="a")])
    _write_archive(client._store, "xbook", "2026-06-02", "r2", [_make_signal(source_id="b")])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    # Cursor is now at r2's date with r2 in the processed set (the last object).
    active_date, processed = _decode_cursor(cs.load("xbook", "xbook"))
    assert active_date == "2026-06-02"
    assert processed == {"r2"}
    # Second poll: no new objects → empty.
    result2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert result2 == []


def test_poll_resumes_from_cursor(tmp_path: Path):  # CC-SIG-SUB-POLL-4
    """Process r1, then add r2 and r3 — only r2 and r3 are delivered."""
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal(source_id="a")])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(r1) == 1

    _write_archive(client._store, "xbook", "2026-06-02", "r2", [_make_signal(source_id="b")])
    _write_archive(client._store, "xbook", "2026-06-03", "r3", [_make_signal(source_id="c")])
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert [d.signal.source_id for d in r2] == ["b", "c"]


def test_poll_restart_resume_three_runs(tmp_path: Path):  # CC-SIG-SUB-POLL-5
    """Simulate a three-run emission history processed exactly once in order."""
    client = _FakeClient()
    signals = [_make_signal(source_id=f"s{i}") for i in range(3)]
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [signals[0]])
    _write_archive(client._store, "xbook", "2026-06-02", "r2", [signals[1]])
    _write_archive(client._store, "xbook", "2026-06-03", "r3", [signals[2]])

    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="consumer", workers=("xbook",))

    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert [d.signal.source_id for d in result] == ["s0", "s1", "s2"]
    active_date, processed = _decode_cursor(cs.load("consumer", "xbook"))
    assert active_date == "2026-06-03"
    assert processed == {"r3"}

    # Restart: second poll returns nothing — exactly-once semantics maintained.
    result2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert result2 == []


def test_poll_at_least_once_on_cursor_write_failure(tmp_path: Path):  # CC-SIG-SUB-POLL-6
    """Simulated cursor save failure → re-delivery on next poll (at-least-once)."""
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal(source_id="a")])

    class _BrokenCursorStore:
        def load(self, consumer_id: str, worker: str) -> str | None:
            return None

        def save(self, consumer_id: str, worker: str, cursor: str) -> None:
            raise OSError("disk full")

    cs = _BrokenCursorStore()
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    # First poll: signals are returned despite the cursor save failure.
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(r1) == 1
    # Second poll: cursor never advanced → same signals re-delivered.
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(r2) == 1


def test_poll_with_callback_commits_after_callback_returns(tmp_path: Path):  # CC-SIG-SUB-POLL-6B
    """Callback consumers commit only after processing the object's deliveries."""
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal(source_id="a")])

    events: list[str] = []

    class _SpyCursorStore(FileCursorStore):
        def save(self, consumer_id: str, worker: str, cursor: str) -> None:
            events.append(f"save:{cursor}")
            super().save(consumer_id, worker, cursor)

    def _process(delivery):
        events.append(f"process:{delivery.signal.source_id}")

    cs = _SpyCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    r1 = poll(
        sub,
        cursor_store=cs,
        bucket=_BUCKET,
        storage_client_factory=lambda: client,
        on_delivery=_process,
    )
    assert [d.signal.source_id for d in r1] == ["a"]
    # Callback runs before the cursor is committed; the saved cursor records the
    # object's date + run_id (encoded form).
    assert len(events) == 2
    assert events[0] == "process:a"
    assert events[1].startswith("save:")
    active_date, processed = _decode_cursor(events[1].removeprefix("save:"))
    assert active_date == "2026-06-01"
    assert processed == {"r1"}


def test_poll_with_callback_exception_leaves_cursor_uncommitted(
    tmp_path: Path,
):  # CC-SIG-SUB-POLL-6C
    """Consumer exception leaves the object cursor uncommitted for re-delivery."""
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [_make_signal(source_id="a")])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="xbook", workers=("xbook",))
    calls: list[str] = []

    def _process(delivery):
        calls.append(delivery.signal.source_id)
        raise RuntimeError("consumer crashed")

    r1 = poll(
        sub,
        cursor_store=cs,
        bucket=_BUCKET,
        storage_client_factory=lambda: client,
        on_delivery=_process,
    )
    assert [d.signal.source_id for d in r1] == ["a"]
    assert cs.load("xbook", "xbook") is None

    r2 = poll(
        sub,
        cursor_store=cs,
        bucket=_BUCKET,
        storage_client_factory=lambda: client,
        on_delivery=lambda delivery: calls.append(delivery.signal.source_id),
    )
    assert [d.signal.source_id for d in r2] == ["a"]
    assert calls == ["a", "a"]


def test_poll_same_date_nonmonotonic_run_id_no_loss(tmp_path: Path):  # CC-SIG-SUB-POLL-14
    """Regression: a later-emitted object in the SAME date with a lexically-smaller
    run_id must still be delivered, not silently skipped.

    run_ids are non-monotonic (``uuid4().hex`` / the Cloud Run ``<job>-<random>``
    execution suffix), so within one date object-name order != emission order. A
    cursor that uses the full last-object name as ``start_offset`` would exclude
    every later same-day emission whose name sorts before it — permanent loss.
    """
    client = _FakeClient()
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",))

    # First emission: lexically-large run_id.
    _write_archive(
        client._store, "xbook", "2026-06-01", "ffaa11", [_make_signal(source_id="first")]
    )
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert [d.signal.source_id for d in r1] == ["first"]

    # Second, LATER emission, same date, lexically-SMALLER run_id.
    _write_archive(
        client._store, "xbook", "2026-06-01", "0011bb", [_make_signal(source_id="second")]
    )
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert [d.signal.source_id for d in r2] == ["second"]  # not lost behind the cursor

    # Third poll: both processed, nothing new.
    r3 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert r3 == []


def test_archive_objects_after_same_date_smaller_run_id():  # CC-SIG-SUB-LIST-5
    """A same-date object whose run_id sorts before the cursor is still listed."""
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "ffaa11", [_make_signal()])
    _write_archive(client._store, "xbook", "2026-06-01", "0011bb", [_make_signal()])
    bkt = client.bucket("test-bucket")
    names = _archive_objects_after(
        bkt, worker="xbook", cursor="signals/xbook/2026-06-01/ffaa11.jsonl"
    )
    assert names == ["signals/xbook/2026-06-01/0011bb.jsonl"]


# ---------------------------------------------------------------------------
# poll() — filter application
# ---------------------------------------------------------------------------


def test_poll_filters_by_kind(tmp_path: Path):  # CC-SIG-SUB-POLL-7
    client = _FakeClient()
    s_action = _make_signal(kind="action.required", source_id="act")
    s_anomaly = _make_signal(kind="anomaly.detected", source_id="ano")
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [s_action, s_anomaly])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",), kinds=("action.required",))
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(result) == 1
    assert result[0].signal.source_id == "act"


def test_poll_filters_by_urgency(tmp_path: Path):  # CC-SIG-SUB-POLL-8
    client = _FakeClient()
    s_info = _make_signal(urgency="info", source_id="inf")
    s_overdue = _make_signal(urgency="overdue", source_id="ov")
    _write_archive(client._store, "xbook", "2026-06-01", "r1", [s_info, s_overdue])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",), min_urgency="due")
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(result) == 1
    assert result[0].signal.source_id == "ov"


def test_poll_filters_by_worker_explicit(tmp_path: Path):  # CC-SIG-SUB-POLL-9
    """Subscription with explicit workers only polls those workers."""
    client = _FakeClient()
    _write_archive(
        client._store, "xbook", "2026-06-01", "r1", [_make_signal(worker="xbook", source_id="b")]
    )
    _write_archive(
        client._store, "xhr", "2026-06-01", "r1", [_make_signal(worker="xhr", source_id="r")]
    )
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",))
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(result) == 1
    assert result[0].signal.source_id == "b"


# ---------------------------------------------------------------------------
# poll() — all-workers discovery
# ---------------------------------------------------------------------------


def test_poll_discovers_all_workers(tmp_path: Path):  # CC-SIG-SUB-POLL-10
    client = _FakeClient()
    _write_archive(
        client._store, "xbook", "2026-06-01", "r1", [_make_signal(worker="xbook", source_id="b")]
    )
    _write_archive(
        client._store, "xhr", "2026-06-01", "r1", [_make_signal(worker="xhr", source_id="r")]
    )
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c")  # workers=None → all
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert {d.signal.source_id for d in result} == {"b", "r"}


# ---------------------------------------------------------------------------
# poll() — creds-absent / offline degrade
# ---------------------------------------------------------------------------


def test_poll_degrades_to_empty_on_creds_error(tmp_path: Path):  # CC-SIG-SUB-POLL-11
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",))
    result = poll(
        sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: _BoomClient()
    )
    assert result == []


# ---------------------------------------------------------------------------
# poll() — multiple workers, independent cursors
# ---------------------------------------------------------------------------


def test_poll_independent_cursors_per_worker(tmp_path: Path):  # CC-SIG-SUB-POLL-12
    client = _FakeClient()
    _write_archive(
        client._store, "xbook", "2026-06-01", "r1", [_make_signal(worker="xbook", source_id="b1")]
    )
    _write_archive(
        client._store, "xhr", "2026-06-01", "r1", [_make_signal(worker="xhr", source_id="r1")]
    )
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook", "xhr"))

    # First poll: get both
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert {d.signal.source_id for d in r1} == {"b1", "r1"}

    # Add a second xbook archive but not xhr
    _write_archive(
        client._store, "xbook", "2026-06-02", "r2", [_make_signal(worker="xbook", source_id="b2")]
    )
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    # Only xbook's new signal, xhr has no new objects
    assert len(r2) == 1
    assert r2[0].signal.source_id == "b2"


# ---------------------------------------------------------------------------
# poll() — Delivery wire properties
# ---------------------------------------------------------------------------


def test_delivery_object_path_and_run_id(tmp_path: Path):  # CC-SIG-SUB-POLL-13
    client = _FakeClient()
    _write_archive(client._store, "xbook", "2026-06-01", "exec-xyz", [_make_signal()])
    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="c", workers=("xbook",))
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert len(result) == 1
    d = result[0]
    assert d.emitted_by_run == "exec-xyz"
    assert d.object_path == f"gs://{_BUCKET}/signals/xbook/2026-06-01/exec-xyz.jsonl"


# ---------------------------------------------------------------------------
# Integration: emit → poll roundtrip
# ---------------------------------------------------------------------------


def test_emit_to_poll_roundtrip(tmp_path: Path, monkeypatch):  # CC-SIG-SUB-INT-1
    """emit_signals writes an archive; poll() picks it up exactly once."""
    monkeypatch.setenv("XBOOK_EMIT_SIGNALS", "1")
    client = _FakeClient()
    factory = lambda: client  # noqa: E731

    from clonway_cockpit.state import NeedsItem

    needs = (NeedsItem("Bills due this week", "3 bills", "warn", "cap", "focus", None, "b42"),)
    emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=lambda *, today, now: build_signals(needs, now=now, worker="xbook"),
        now=_NOW,
        today=_TODAY,
        run_id="emit-run-1",
        bucket=_BUCKET,
        storage_client_factory=factory,
    )

    cs = FileCursorStore(tmp_path)
    sub = Subscription(consumer_id="orchestrator", workers=("xbook",))
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=factory)
    assert len(r1) == 1
    assert r1[0].signal.source_id == "b42"
    assert r1[0].emitted_by_run == "emit-run-1"

    # Second poll — cursor advanced → empty
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=factory)
    assert r2 == []


def test_emit_to_poll_resumes_after_restart(tmp_path: Path, monkeypatch):  # CC-SIG-SUB-INT-2
    """Cursor persists to disk — a fresh FileCursorStore resumes correctly."""
    monkeypatch.setenv("XBOOK_EMIT_SIGNALS", "1")
    client = _FakeClient()
    factory = lambda: client  # noqa: E731

    from clonway_cockpit.state import NeedsItem

    needs = (NeedsItem("Sync the books", "needed", "error", "sync", "focus", None, "s1"),)
    emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=lambda *, today, now: build_signals(needs, now=now, worker="xbook"),
        now=_NOW,
        today=_TODAY,
        run_id="run-a",
        bucket=_BUCKET,
        storage_client_factory=factory,
    )

    state_dir = tmp_path / "state"
    sub = Subscription(consumer_id="orch", workers=("xbook",))

    # Simulate first consumer session
    cs1 = FileCursorStore(state_dir)
    r1 = poll(sub, cursor_store=cs1, bucket=_BUCKET, storage_client_factory=factory)
    assert len(r1) == 1

    # Simulate restarted consumer (new FileCursorStore, same state_dir)
    cs2 = FileCursorStore(state_dir)
    r2 = poll(sub, cursor_store=cs2, bucket=_BUCKET, storage_client_factory=factory)
    assert r2 == []  # cursor persisted → not re-delivered
