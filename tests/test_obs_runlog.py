# tests/test_obs_runlog.py
"""CC-RUNLOG-* — obs.runlog unit tests.

Golden tests verify byte-equivalence with the original worker semantics
(xbook / xhr / xletter): compact separators, ts injection, sha256 prefix,
key-sorted canonical hash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clonway_cockpit.obs.runlog import (
    append,
    default_runs_dir,
    hash_request,
    make_runlog,
    new_run_file,
)

# ---- default_runs_dir -------------------------------------------------------


def test_default_runs_dir_convention():  # CC-RUNLOG-DIR-1
    assert default_runs_dir("xbook") == Path(".xbook/runs")
    assert default_runs_dir("xhr") == Path(".xhr/runs")
    assert default_runs_dir("xletter") == Path(".xletter/runs")


# ---- new_run_file -----------------------------------------------------------


def test_new_run_file_creates_parent_dir(tmp_path):  # CC-RUNLOG-NEW-1
    runs_dir = tmp_path / "runs"
    path = new_run_file("abc123", runs_dir=runs_dir)
    assert runs_dir.is_dir()
    assert path == runs_dir / "abc123.jsonl"


def test_new_run_file_idempotent_mkdir(tmp_path):  # CC-RUNLOG-NEW-2
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    path = new_run_file("r1", runs_dir=runs_dir)
    assert path.name == "r1.jsonl"


# ---- append: wire format (golden) ------------------------------------------


def test_append_compact_separators_golden(tmp_path):  # CC-RUNLOG-APP-1
    # Golden: compact separators, no spaces after : or ,
    run_file = tmp_path / "r.jsonl"
    append(run_file, ts="2026-01-01T00:00:00+00:00", event="stage.ok", count=3)
    line = run_file.read_text()
    assert '", "' not in line, "should not have space after comma"
    assert '": ' not in line, "should not have space after colon"
    assert line.endswith("\n")


def test_append_ts_injected_when_absent(tmp_path):  # CC-RUNLOG-APP-2
    run_file = tmp_path / "r.jsonl"
    append(run_file, event="noop")
    entry = json.loads(run_file.read_text())
    assert "ts" in entry
    assert entry["ts"].startswith("20")  # looks like a year


def test_append_caller_ts_not_overwritten(tmp_path):  # CC-RUNLOG-APP-3
    run_file = tmp_path / "r.jsonl"
    append(run_file, ts="2026-05-01T12:00:00+00:00", event="x")
    entry = json.loads(run_file.read_text())
    assert entry["ts"] == "2026-05-01T12:00:00+00:00"


def test_append_multiple_lines(tmp_path):  # CC-RUNLOG-APP-4
    run_file = tmp_path / "r.jsonl"
    append(run_file, ts="2026-01-01T00:00:00+00:00", event="a")
    append(run_file, ts="2026-01-01T00:01:00+00:00", event="b")
    lines = [json.loads(ln) for ln in run_file.read_text().splitlines()]
    assert [e["event"] for e in lines] == ["a", "b"]


def test_append_non_serialisable_uses_str(tmp_path):  # CC-RUNLOG-APP-5
    # default=str fallback — mirrors all three worker originals.
    from datetime import date

    run_file = tmp_path / "r.jsonl"
    append(run_file, ts="2026-01-01T00:00:00+00:00", day=date(2026, 1, 1))
    entry = json.loads(run_file.read_text())
    assert entry["day"] == "2026-01-01"


# ---- hash_request -----------------------------------------------------------


def test_hash_request_prefix():  # CC-RUNLOG-HASH-1
    h = hash_request({"a": 1})
    assert h.startswith("sha256:")


def test_hash_request_stable_under_key_reordering():  # CC-RUNLOG-HASH-2
    h1 = hash_request({"b": 2, "a": 1})
    h2 = hash_request({"a": 1, "b": 2})
    assert h1 == h2


def test_hash_request_golden():  # CC-RUNLOG-HASH-3
    # Canonical form is sort_keys + compact separators; verify against known value.
    import hashlib

    body = {"ref": "ABC123", "amount": 99}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    assert hash_request(body) == expected


def test_hash_request_different_values_differ():  # CC-RUNLOG-HASH-4
    assert hash_request({"x": 1}) != hash_request({"x": 2})


# ---- Runlog dataclass + make_runlog ----------------------------------------


def test_make_runlog_default_runs_dir():  # CC-RUNLOG-MAKE-1
    rl = make_runlog("xbook")
    assert rl.runs_dir == Path(".xbook/runs")


def test_make_runlog_explicit_runs_dir(tmp_path):  # CC-RUNLOG-MAKE-2
    rl = make_runlog("xbook", runs_dir=tmp_path)
    assert rl.runs_dir == tmp_path


def test_runlog_methods_delegate_correctly(tmp_path):  # CC-RUNLOG-MAKE-3
    rl = make_runlog("xtest", runs_dir=tmp_path / "runs")
    rf = rl.new_run_file("r1")
    rl.append(rf, ts="2026-01-01T00:00:00+00:00", event="ok")
    entry = json.loads(rf.read_text())
    assert entry["event"] == "ok"
    h = rl.hash_request({"k": "v"})
    assert h.startswith("sha256:")


def test_runlog_is_frozen():  # CC-RUNLOG-MAKE-4
    rl = make_runlog("xbook")
    with pytest.raises((AttributeError, TypeError)):
        rl.runs_dir = Path("/tmp")  # type: ignore[misc]
