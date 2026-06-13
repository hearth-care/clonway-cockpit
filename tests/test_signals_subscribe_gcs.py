"""CC-SIG-SUB-GCS-* — GcsCursorStore tests.

Tests the GCS-backed cursor store in isolation using a fake GCS client that
simulates generation-match preconditions. No google-cloud-storage dependency.
"""

from __future__ import annotations

import json

import pytest

from clonway_cockpit.signals.subscribe import GcsCursorStore

_BUCKET = "test-bucket"
_CONSUMER = "orchestrator"


# ---------------------------------------------------------------------------
# Fake GCS with generation tracking
# ---------------------------------------------------------------------------


class _FakeGcsError(Exception):
    pass


class _FakeNotFound(_FakeGcsError):
    pass


_FakeNotFound.__name__ = "NotFound"


class _FakePreconditionFailed(_FakeGcsError):
    pass


_FakePreconditionFailed.__name__ = "PreconditionFailed"


class _FakeAuthError(_FakeGcsError):
    pass


_FakeAuthError.__name__ = "GoogleAuthError"


class _FakeBlob:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self.name = name
        self.generation: int | None = None

    def download_as_text(self) -> str:
        entry = self._store.get(self.name)
        if entry is None:
            raise _FakeNotFound(self.name)
        body, gen = entry
        self.generation = gen
        return body

    def upload_from_string(
        self,
        body: str,
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> None:
        current = self._store.get(self.name)
        current_gen = None if current is None else current[1]
        if if_generation_match is not None:
            if if_generation_match == 0:
                # Create-only: fail if already exists
                if current is not None:
                    raise _FakePreconditionFailed("already exists")
            elif current_gen != if_generation_match:
                raise _FakePreconditionFailed(
                    f"precondition failed: expected gen {if_generation_match}, got {current_gen}"
                )
        new_gen = 1 if current is None else current_gen + 1
        self._store[self.name] = (body, new_gen)
        self.generation = new_gen


class _FakeBucket:
    def __init__(self, store: dict) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeClient:
    def __init__(self) -> None:
        self._store: dict = {}

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gcs_cursor_load_missing():  # CC-SIG-SUB-GCS-1
    """load() returns None when the cursor object doesn't exist yet."""
    client = _FakeClient()
    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: client)
    assert cs.load(_CONSUMER, "xbook") is None


def test_gcs_cursor_roundtrip():  # CC-SIG-SUB-GCS-2
    client = _FakeClient()
    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: client)
    cs.save(_CONSUMER, "xbook", "signals/xbook/2026-06-01/r1.jsonl")
    assert cs.load(_CONSUMER, "xbook") == "signals/xbook/2026-06-01/r1.jsonl"


def test_gcs_cursor_multiple_workers():  # CC-SIG-SUB-GCS-3
    client = _FakeClient()
    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: client)
    cs.save(_CONSUMER, "xbook", "signals/xbook/2026-06-01/r1.jsonl")
    cs.save(_CONSUMER, "xhr", "signals/xhr/2026-06-01/r1.jsonl")
    assert cs.load(_CONSUMER, "xbook") == "signals/xbook/2026-06-01/r1.jsonl"
    assert cs.load(_CONSUMER, "xhr") == "signals/xhr/2026-06-01/r1.jsonl"


def test_gcs_cursor_save_updates_generation():  # CC-SIG-SUB-GCS-4
    """Each save increments the generation — the precondition reads the latest gen."""
    client = _FakeClient()
    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: client)
    cs.save(_CONSUMER, "xbook", "obj-1")
    cs.save(_CONSUMER, "xbook", "obj-2")  # must read current gen then write with match
    assert cs.load(_CONSUMER, "xbook") == "obj-2"


def test_gcs_cursor_stores_at_correct_path():  # CC-SIG-SUB-GCS-5
    """Cursor object lands at subscriptions/<consumer_id>/cursor.json."""
    client = _FakeClient()
    cs = GcsCursorStore("myapp", bucket=_BUCKET, storage_client_factory=lambda: client)
    cs.save("myapp", "xbook", "obj-1")
    expected_key = "subscriptions/myapp/cursor.json"
    assert expected_key in client._store
    body = json.loads(client._store[expected_key][0])
    assert "myapp\x00xbook" in body


def test_gcs_cursor_load_quiet_on_auth_error():  # CC-SIG-SUB-GCS-6
    """load() returns None on GoogleAuthError (creds absent)."""

    class _BoomClient:
        def bucket(self, name: str):
            raise _FakeAuthError("no creds")

    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: _BoomClient())
    assert cs.load(_CONSUMER, "xbook") is None


def test_gcs_cursor_save_quiet_on_auth_error():  # CC-SIG-SUB-GCS-7
    """save() silently skips on GoogleAuthError."""

    class _BoomClient:
        def bucket(self, name: str):
            raise _FakeAuthError("no creds")

    cs = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: _BoomClient())
    cs.save(_CONSUMER, "xbook", "obj-1")  # must not raise


def test_gcs_cursor_save_raises_on_precondition_failed():  # CC-SIG-SUB-GCS-8
    """Concurrent writer: PreconditionFailed is re-raised (not silenced)."""
    client = _FakeClient()
    # Pre-populate the cursor object at generation 1 by writing directly to the store
    key = f"subscriptions/{_CONSUMER}/cursor.json"
    client._store[key] = ('{"stale": "data"}', 99)

    # The GcsCursorStore reads generation=99, tries to write with if_generation_match=99.
    # But our fake client's store returns gen=99, so the write should succeed.
    # To trigger a precondition failure, we need two writers racing.
    # Simulate: save() reads generation=99 but by write time store has changed to gen=100.
    write_calls = []

    class _RacingClient:
        def bucket(self, name: str):
            return _RacingBucket()

    class _RacingBucket:
        def blob(self, name: str):
            return _RacingBlob(name)

    class _RacingBlob:
        def __init__(self, name: str):
            self.name = name
            self.generation = None

        def download_as_text(self) -> str:
            self.generation = 42
            return '{"stale": "value"}'

        def upload_from_string(self, body: str, content_type=None, if_generation_match=None):
            write_calls.append(if_generation_match)
            raise _FakePreconditionFailed("concurrent write")

    cs2 = GcsCursorStore(_CONSUMER, bucket=_BUCKET, storage_client_factory=lambda: _RacingClient())
    with pytest.raises(_FakePreconditionFailed):
        cs2.save(_CONSUMER, "xbook", "obj-x")
    assert write_calls == [42]  # precondition was the generation we read
