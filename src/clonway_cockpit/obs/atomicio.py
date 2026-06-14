"""Atomic file writes for GCSFuse-mounted state.

In-place appends (``open("a")``) to a file on a GCSFuse mount trigger
'stale file handle / generation mismatch' retry storms — the root cause of the
2026-06-11 xbook sync stall (~9 min blocked after the sync work itself had
succeeded; the post-stage ``model_usage.jsonl`` fan-in was the offender). The
fix, first applied in ``gateway.telemetry`` and now shared here, is to rewrite
the whole file to a temp sibling and ``os.replace`` it: GCSFuse gets one
generation-matched object replacement per write instead of an append retry loop.

``atomic_write_bytes`` is the primitive (whole-file replace); ``atomic_append``
is read-existing → concat → atomic-write on top of it. A process-wide lock keeps
each read-modify-write sequential — the old single-syscall ``open("a")`` append
got that atomicity from the kernel for free; the read-modify-write here would
otherwise race and lose lines under concurrency.
"""

from __future__ import annotations

import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

_WRITE_LOCK = threading.Lock()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp-sibling ``os.replace``, never an
    in-place truncate/append.

    The temp file is created in ``path``'s own directory so the ``os.replace`` is
    a same-filesystem rename (atomic, and one generation-matched replacement on
    GCSFuse). On any failure the temp file is cleaned up and the error re-raised
    to the caller.
    """
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, data)
            os.close(fd)
            os.replace(tmp, path)
        except Exception:  # clean up the temp, then re-raise to the caller
            with suppress(Exception):
                os.close(fd)
            with suppress(Exception):
                os.unlink(tmp)
            raise


def atomic_append(path: Path, line: str) -> None:
    """Append ``line`` (UTF-8) to ``path`` by rewriting the file via a
    temp-sibling rename, not an in-place ``open("a")`` append.

    Read-modify-write is held under a process-wide lock so concurrent appenders
    don't clobber each other's lines — the single-syscall append it replaces had
    that atomicity for free. A missing target is treated as empty.
    """
    with _WRITE_LOCK:
        try:
            existing = path.read_bytes()
        except OSError:
            existing = b""
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, existing + line.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, path)
        except Exception:  # clean up the temp, then re-raise to the caller
            with suppress(Exception):
                os.close(fd)
            with suppress(Exception):
                os.unlink(tmp)
            raise
