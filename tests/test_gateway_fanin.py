from pathlib import Path

import pytest

from clonway_cockpit.gateway import (
    fanin_relpath,
    flush_model_usage,
    local_dir_sink,
    record_call,
)


def _seed_usage(base: Path) -> None:
    record_call(
        base,
        role="chat",
        provider="openai_compatible",
        model="m",
        prompt_tokens=10,
        completion_tokens=5,
        est_cost=0.001,
        ok=True,
        err=None,
    )


def test_fanin_relpath_shape():
    assert (
        fanin_relpath(worker="xbook", run_id="run1", date="2026-06-08")
        == "model-usage/xbook/2026-06-08/run1.jsonl"
    )


def test_local_dir_sink_writes(tmp_path):
    local_dir_sink(tmp_path)("model-usage/xbook/2026-06-08/run1.jsonl", b"hello\n")
    assert (tmp_path / "model-usage/xbook/2026-06-08/run1.jsonl").read_bytes() == b"hello\n"


def test_flush_reads_and_sinks(tmp_path):
    worker_base = tmp_path / "worker"
    _seed_usage(worker_base)
    captured: dict[str, object] = {}

    def sink(relpath: str, data: bytes) -> None:
        captured["relpath"] = relpath
        captured["data"] = data

    rel = flush_model_usage(
        worker_base, worker="xbook", run_id="run1", date="2026-06-08", sink=sink
    )
    assert rel == "model-usage/xbook/2026-06-08/run1.jsonl"
    assert captured["relpath"] == rel
    assert b'"model": "m"' in captured["data"]  # type: ignore[operator]


def test_flush_missing_file_returns_none(tmp_path):
    calls: list[str] = []
    rel = flush_model_usage(
        tmp_path / "nope",
        worker="x",
        run_id="r",
        date="2026-06-08",
        sink=lambda p, d: calls.append(p),
    )
    assert rel is None
    assert calls == []


def test_flush_empty_file_returns_none(tmp_path):
    (tmp_path / "model_usage.jsonl").write_text("   \n", encoding="utf-8")
    calls: list[str] = []
    rel = flush_model_usage(
        tmp_path, worker="x", run_id="r", date="2026-06-08", sink=lambda p, d: calls.append(p)
    )
    assert rel is None
    assert calls == []


def test_flush_rejects_unsafe_segments(tmp_path):
    _seed_usage(tmp_path)
    calls: list[str] = []

    def sink(relpath: str, data: bytes) -> None:
        calls.append(relpath)

    for worker, run, date in [
        ("../evil", "r", "2026-06-08"),
        ("x", "a/b", "2026-06-08"),
        ("x", "r", "2026/06/08"),
        ("X", "r", "2026-06-08"),  # uppercase
        ("x", "r", "not-a-date"),
    ]:
        assert flush_model_usage(tmp_path, worker=worker, run_id=run, date=date, sink=sink) is None
    assert calls == []  # nothing written for any unsafe input


def test_flush_swallows_sink_errors(tmp_path):
    _seed_usage(tmp_path)

    def boom(relpath: str, data: bytes) -> None:
        raise OSError("disk full")

    rel = flush_model_usage(tmp_path, worker="x", run_id="r", date="2026-06-08", sink=boom)
    assert rel is None  # best-effort: never raises


def test_flush_rejects_trailing_newline_worker(tmp_path):
    # regression guard: _SLUG_RE.fullmatch must reject "x\n" (re `$` alone accepts it)
    _seed_usage(tmp_path)
    calls: list[str] = []
    rel = flush_model_usage(
        tmp_path, worker="x\n", run_id="r", date="2026-06-08", sink=lambda p, d: calls.append(p)
    )
    assert rel is None
    assert calls == []


def test_flush_round_trips_bytes_exactly(tmp_path):
    worker_base = tmp_path / "worker"
    _seed_usage(worker_base)
    original = (worker_base / "model_usage.jsonl").read_bytes()
    captured: dict[str, bytes] = {}
    flush_model_usage(
        worker_base,
        worker="x",
        run_id="r",
        date="2026-06-08",
        sink=lambda p, d: captured.__setitem__("data", d),
    )
    assert captured["data"] == original  # byte-identical


def test_local_dir_sink_refuses_escaping_relpath(tmp_path):
    sink = local_dir_sink(tmp_path / "root")
    with pytest.raises(ValueError, match="escapes"):
        sink("../escaped.txt", b"x")
    assert not (tmp_path / "escaped.txt").exists()


def test_two_workers_build_a_fanin_tree(tmp_path):
    fanin_root = tmp_path / "fleet"
    sink = local_dir_sink(fanin_root)
    for worker in ("xbook", "xhr"):
        worker_base = tmp_path / worker
        _seed_usage(worker_base)
        rel = flush_model_usage(
            worker_base, worker=worker, run_id="run1", date="2026-06-08", sink=sink
        )
        assert rel == f"model-usage/{worker}/2026-06-08/run1.jsonl"
    # the fan-in tree now holds both workers' usage, keyed by worker (the fleet view)
    assert (fanin_root / "model-usage/xbook/2026-06-08/run1.jsonl").exists()
    assert (fanin_root / "model-usage/xhr/2026-06-08/run1.jsonl").exists()
