"""CC-SIG-E2E-* — end-to-end signal bus tests.

Exercises the full emit → poll → Delivery round-trip using the shared fleet
interfaces, including:
- Multi-run emission history processed exactly once in order.
- Cursor restart: a fresh FileCursorStore resumes without re-delivery.
- At-least-once boundary: duplicate on crash-boundary (cursor write failure).
- Filter application across a multi-worker multi-run history.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date
from pathlib import Path

from clonway_cockpit.signals.emit import emit_signals
from clonway_cockpit.signals.model import Signal, build_signals
from clonway_cockpit.signals.subscribe import (
    FileCursorStore,
    Subscription,
    poll,
)
from clonway_cockpit.state import NeedsItem

_BUCKET = "e2e-bucket"


# ---------------------------------------------------------------------------
# Fake GCS — shared with emit and subscribe
# ---------------------------------------------------------------------------


class _FakeBlob:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self.name = name

    def upload_from_string(self, body: str, content_type: str | None = None, **kwargs) -> None:
        self._store[self.name] = body

    def download_as_text(self) -> str:
        if self.name not in self._store:
            raise _FakeNotFound(self.name)
        return self._store[self.name]


class _FakeNotFound(Exception):
    pass


_FakeNotFound.__name__ = "NotFound"


class _FakeBucket:
    def __init__(self, store: dict) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)

    def list_blobs(self, prefix: str = "", start_offset: str = "") -> list[_FakeBlob]:
        return [
            _FakeBlob(self._store, name)
            for name in sorted(self._store)
            if name.startswith(prefix) and (not start_offset or name >= start_offset)
        ]


class _FakeGcs:
    """Single shared store visible to both emit and subscribe."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def client(self) -> _FakeGcsClient:
        return _FakeGcsClient(self._store)


class _FakeGcsClient:
    def __init__(self, store: dict) -> None:
        self._store = store

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit(
    gcs: _FakeGcs,
    *,
    worker: str,
    needs: tuple[NeedsItem, ...],
    now: datetime,
    run_id: str,
    monkeypatch,
    flag_env: str | None = None,
) -> tuple[Signal, ...]:
    env = flag_env or f"{worker.upper()}_EMIT_SIGNALS"
    monkeypatch.setenv(env, "1")
    return emit_signals(
        worker_id=worker,
        flag_env=env,
        build=lambda *, today, now: build_signals(needs, now=now, worker=worker),
        now=now,
        today=now.date(),
        run_id=run_id,
        bucket=_BUCKET,
        storage_client_factory=gcs.client,
    )


def _needs(title: str, source_id: str) -> tuple[NeedsItem, ...]:
    return (NeedsItem(title, "detail", "warn", "cap", "focus", None, source_id),)


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


def test_e2e_three_run_history_exactly_once(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-1
    """Three runs emitted; poll processes each exactly once in chronological order."""
    gcs = _FakeGcs()
    base = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    dates = [
        datetime(2026, 6, 1, 9, tzinfo=UTC),
        datetime(2026, 6, 2, 9, tzinfo=UTC),
        datetime(2026, 6, 3, 9, tzinfo=UTC),
    ]
    for i, dt in enumerate(dates):
        _emit(
            gcs,
            worker="xbook",
            needs=_needs("Bills due this week", f"b{i}"),
            now=dt,
            run_id=f"r{i}",
            monkeypatch=monkeypatch,
        )

    sub = Subscription(consumer_id="orch", workers=("xbook",))
    cs = FileCursorStore(tmp_path)

    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert [d.signal.source_id for d in r1] == ["b0", "b1", "b2"]
    assert [d.emitted_by_run for d in r1] == ["r0", "r1", "r2"]

    # Second poll: cursor advanced → nothing new.
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert r2 == []


def test_e2e_cursor_restart(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-2
    """A fresh FileCursorStore reading the same state_dir resumes without re-delivery."""
    gcs = _FakeGcs()
    _emit(
        gcs,
        worker="xbook",
        needs=_needs("Sync the books", "s1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="run-a",
        monkeypatch=monkeypatch,
    )

    sub = Subscription(consumer_id="orch", workers=("xbook",))
    state_dir = tmp_path / "state"

    # First session
    cs1 = FileCursorStore(state_dir)
    r1 = poll(sub, cursor_store=cs1, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert len(r1) == 1

    # Simulated restart — new store object, same state dir
    cs2 = FileCursorStore(state_dir)
    r2 = poll(sub, cursor_store=cs2, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert r2 == []  # cursor persisted; not re-delivered


def test_e2e_at_least_once_on_cursor_failure(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-3
    """If the cursor write fails the signal is re-delivered on the next poll."""
    gcs = _FakeGcs()
    _emit(
        gcs,
        worker="xbook",
        needs=_needs("Bills due this week", "b1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="run-a",
        monkeypatch=monkeypatch,
    )

    sub = Subscription(consumer_id="orch", workers=("xbook",))

    class _BrokenCursor:
        def load(self, *_):
            return None

        def save(self, *_):
            raise OSError("disk full")

    r1 = poll(sub, cursor_store=_BrokenCursor(), bucket=_BUCKET, storage_client_factory=gcs.client)
    assert len(r1) == 1
    # Re-delivery because cursor never advanced.
    r2 = poll(sub, cursor_store=_BrokenCursor(), bucket=_BUCKET, storage_client_factory=gcs.client)
    assert len(r2) == 1
    assert r1[0].signal.dedup_key == r2[0].signal.dedup_key  # same signal both times


def test_e2e_two_workers_independent_cursors(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-4
    """Two workers emit independently; consumer cursors advance independently."""
    gcs = _FakeGcs()
    _emit(
        gcs,
        worker="xbook",
        needs=_needs("Bills due this week", "b1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="r1",
        monkeypatch=monkeypatch,
    )
    _emit(
        gcs,
        worker="xhr",
        needs=_needs("Compliance filing due", "c1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="r1",
        monkeypatch=monkeypatch,
    )

    sub = Subscription(consumer_id="orch", workers=("xbook", "xhr"))
    cs = FileCursorStore(tmp_path)

    # First poll: both
    r1 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert {d.signal.source_id for d in r1} == {"b1", "c1"}

    # Emit only for xbook
    _emit(
        gcs,
        worker="xbook",
        needs=_needs("Bills due this week", "b2"),
        now=datetime(2026, 6, 2, 9, tzinfo=UTC),
        run_id="r2",
        monkeypatch=monkeypatch,
    )

    # Second poll: only the new xbook signal
    r2 = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert len(r2) == 1
    assert r2[0].signal.source_id == "b2"


def test_e2e_filter_by_kind(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-5
    """Only signals matching the subscription kind filter are returned."""
    gcs = _FakeGcs()
    # "Bills due this week" → kind=deadline.approaching
    # "Unmatched bank lines" → kind=action.required
    needs = (
        NeedsItem("Bills due this week", "d", "warn", "cap", "f", None, "b1"),
        NeedsItem("Unmatched bank lines", "d", "warn", "cap", "f", None, "u1"),
    )
    monkeypatch.setenv("XBOOK_EMIT_SIGNALS", "1")
    emit_signals(
        worker_id="xbook",
        flag_env="XBOOK_EMIT_SIGNALS",
        build=lambda *, today, now: build_signals(needs, now=now, worker="xbook"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        today=Date(2026, 6, 1),
        run_id="r1",
        bucket=_BUCKET,
        storage_client_factory=gcs.client,
    )

    sub = Subscription(consumer_id="orch", workers=("xbook",), kinds=("action.required",))
    cs = FileCursorStore(tmp_path)
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert len(result) == 1
    assert result[0].signal.source_id == "u1"
    assert result[0].signal.kind == "action.required"


def test_e2e_workers_none_auto_discovers(tmp_path: Path, monkeypatch) -> None:  # CC-SIG-E2E-6
    """Subscription(workers=None) discovers all emitters automatically."""
    gcs = _FakeGcs()
    _emit(
        gcs,
        worker="xbook",
        needs=_needs("Bills due this week", "b1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="r1",
        monkeypatch=monkeypatch,
    )
    _emit(
        gcs,
        worker="xhr",
        needs=_needs("Compliance filing due", "c1"),
        now=datetime(2026, 6, 1, 9, tzinfo=UTC),
        run_id="r1",
        monkeypatch=monkeypatch,
        flag_env="XHR_EMIT_SIGNALS",
    )

    sub = Subscription(consumer_id="orch")  # workers=None
    cs = FileCursorStore(tmp_path)
    result = poll(sub, cursor_store=cs, bucket=_BUCKET, storage_client_factory=gcs.client)
    assert {d.signal.source_id for d in result} == {"b1", "c1"}
