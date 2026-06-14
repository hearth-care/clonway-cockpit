"""CC-ATOMICIO-* — obs.atomicio unit tests.

The helper exists because in-place ``open("a")`` appends to a GCSFuse-mounted
file trigger stale-handle retry storms (the 2026-06-11 xbook sync stall). These
tests pin the two behaviours that matter: every write goes through a temp-sibling
``os.replace`` (never an in-place append on the target), and concurrent appends
don't lose lines.
"""

from __future__ import annotations

import builtins
import threading
from pathlib import Path

import pytest

from clonway_cockpit.obs import atomicio
from clonway_cockpit.obs.atomicio import atomic_append, atomic_write_bytes

# ---- atomic_append: behaviour ----------------------------------------------


def test_append_creates_then_grows(tmp_path: Path):  # CC-ATOMICIO-APP-1
    target = tmp_path / "log.jsonl"
    atomic_append(target, "a\n")
    atomic_append(target, "b\n")
    atomic_append(target, "c\n")
    assert target.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_append_to_missing_target_treated_as_empty(tmp_path: Path):  # CC-ATOMICIO-APP-2
    target = tmp_path / "fresh.jsonl"
    assert not target.exists()
    atomic_append(target, "first\n")
    assert target.read_text(encoding="utf-8") == "first\n"


def test_append_preserves_utf8(tmp_path: Path):  # CC-ATOMICIO-APP-3
    target = tmp_path / "u.jsonl"
    atomic_append(target, "café — £5\n")
    assert target.read_bytes() == "café — £5\n".encode()


def test_append_leaves_no_temp_files(tmp_path: Path):  # CC-ATOMICIO-APP-4
    target = tmp_path / "log.jsonl"
    for i in range(5):
        atomic_append(target, f"{i}\n")
    assert list(tmp_path.glob("*.tmp")) == []


# ---- atomic_append: goes through os.replace, never in-place append ----------


def test_append_uses_os_replace_once_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):  # CC-ATOMICIO-REPLACE-1
    replaces = {"n": 0}
    real_replace = atomicio.os.replace

    def _spy(src: object, dst: object) -> None:
        replaces["n"] += 1
        real_replace(src, dst)

    monkeypatch.setattr(atomicio.os, "replace", _spy)
    target = tmp_path / "log.jsonl"
    atomic_append(target, "x\n")
    atomic_append(target, "y\n")
    assert replaces["n"] == 2


def test_append_never_opens_target_for_inplace_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):  # CC-ATOMICIO-REPLACE-2
    # The whole point: the target is never opened in a writable/append mode —
    # that is the GCSFuse stale-handle trigger. The write lands on a temp sibling
    # and is renamed into place. Reading the target (rb) is fine.
    target = tmp_path / "log.jsonl"
    atomic_append(target, "seed\n")  # pre-existing file so read path is exercised

    real_open = builtins.open
    offending: list[tuple[str, str]] = []

    def _guard(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(file) == target and any(c in mode for c in ("a", "w", "+", "x")):
            offending.append((str(file), mode))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guard)
    atomic_append(target, "more\n")
    assert offending == []
    assert target.read_text(encoding="utf-8") == "seed\nmore\n"


def test_append_threadsafe_under_concurrency(tmp_path: Path):  # CC-ATOMICIO-LOCK-1
    # Read-rewrite-rename would race and lose lines without the lock. Drive max
    # contention via a barrier and assert every line survives.
    target = tmp_path / "log.jsonl"
    n = 40
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()
        atomic_append(target, f"{i}\n")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = sorted(int(ln) for ln in target.read_text(encoding="utf-8").splitlines())
    assert lines == list(range(n))


# ---- atomic_write_bytes -----------------------------------------------------


def test_write_bytes_creates_and_overwrites(tmp_path: Path):  # CC-ATOMICIO-WRITE-1
    target = tmp_path / "blob.bin"
    atomic_write_bytes(target, b"first")
    assert target.read_bytes() == b"first"
    atomic_write_bytes(target, b"second-longer")
    assert target.read_bytes() == b"second-longer"


def test_write_bytes_uses_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):  # CC-ATOMICIO-WRITE-2
    replaces = {"n": 0}
    real_replace = atomicio.os.replace

    def _spy(src: object, dst: object) -> None:
        replaces["n"] += 1
        real_replace(src, dst)

    monkeypatch.setattr(atomicio.os, "replace", _spy)
    atomic_write_bytes(tmp_path / "blob.bin", b"data")
    assert replaces["n"] == 1


def test_write_bytes_leaves_no_temp_on_replace_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):  # CC-ATOMICIO-WRITE-3
    # A failing replace must clean up the temp sibling and re-raise to the caller.
    def _boom(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomicio.os, "replace", _boom)
    target = tmp_path / "blob.bin"
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_bytes(target, b"data")
    assert list(tmp_path.glob("*.tmp")) == []
    assert not target.exists()
