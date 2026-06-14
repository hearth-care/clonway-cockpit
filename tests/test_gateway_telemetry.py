import threading
from pathlib import Path

import pytest

from clonway_cockpit.gateway.telemetry import load_events, record_call
from clonway_cockpit.obs import atomicio


def _record(base: Path, **over: object) -> None:
    kw: dict[str, object] = dict(
        role="chat",
        provider="openai_compatible",
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=20,
        est_cost=0.0001,
        ok=True,
        err=None,
    )
    kw.update(over)
    record_call(base, **kw)  # type: ignore[arg-type]


def test_record_then_load_roundtrip(tmp_path: Path):
    _record(tmp_path)
    _record(
        tmp_path, ok=False, err="GatewayError", prompt_tokens=0, completion_tokens=0, est_cost=None
    )
    events = load_events(tmp_path)
    assert len(events) == 2
    first = events[0]
    assert first["role"] == "chat"
    assert first["model"] == "gpt-4o-mini"
    assert first["prompt_tokens"] == 10
    assert first["completion_tokens"] == 20
    assert first["ok"] is True
    assert "ts" in first
    assert events[1]["ok"] is False
    assert events[1]["err"] == "GatewayError"
    assert events[1]["est_cost"] is None


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_events(tmp_path / "nope") == []


def test_record_never_crashes_on_unwritable_base(tmp_path: Path):
    # base path lives *inside* a regular file → mkdir/open must fail and be swallowed
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    bad_base = blocker / "sub"
    _record(bad_base)  # must NOT raise
    assert load_events(bad_base) == []


def test_record_uses_atomic_temp_rename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The GCSFuse stale-handle root cause is in-place appends; the write must go
    # through os.replace (temp-sibling rename), exactly once per record_call. The
    # rename now lives in the shared obs.atomicio helper.
    replaces = {"n": 0}
    real_replace = atomicio.os.replace

    def _spy(src: object, dst: object) -> None:
        replaces["n"] += 1
        real_replace(src, dst)

    monkeypatch.setattr(atomicio.os, "replace", _spy)
    _record(tmp_path)
    assert replaces["n"] == 1
    assert len(load_events(tmp_path)) == 1


def test_record_leaves_no_temp_files(tmp_path: Path):
    for _ in range(5):
        _record(tmp_path)
    assert list(tmp_path.glob("*.tmp")) == []
    assert len(load_events(tmp_path)) == 5


def test_record_threadsafe_under_concurrency(tmp_path: Path):
    # Read-rewrite-rename would race and lose lines without the lock; the old
    # single-syscall append did not. Drive max contention via a barrier and assert
    # every line survives.
    n = 40
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()
        _record(tmp_path, prompt_tokens=i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = load_events(tmp_path)
    assert len(events) == n
    assert sorted(e["prompt_tokens"] for e in events) == list(range(n))
