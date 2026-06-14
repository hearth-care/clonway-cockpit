"""Per-worker JSONL run log — extracted from xbook/xhr/xletter runlog.py copies.

All three workers had 30-line files identical except for one constant
(``DEFAULT_RUNS_DIR = Path(".{worker_id}/runs")``). This module parameterises
that constant and adds :func:`make_runlog` so a worker shim is two lines.

Wire format is byte-identical to the originals:
  - Each entry is one compact-JSON line (``separators=(",", ":")``) with a
    trailing newline appended to the file.
  - ``ts`` is always injected as an ISO-8601 UTC string if not supplied by the
    caller.
  - ``hash_request`` returns ``"sha256:" + sha256(canonical_json).hexdigest()``
    where canonical JSON uses ``sort_keys=True, separators=(",", ":")``.

Retrieval date of this module: 2026-06-11.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clonway_cockpit.obs.atomicio import atomic_append


def default_runs_dir(worker_id: str) -> Path:
    """Return the conventional run-log directory for a worker: ``.{worker_id}/runs``."""
    return Path(f".{worker_id}/runs")


def new_run_file(run_id: str, *, runs_dir: Path) -> Path:
    """Create and return a new run-log file path; parent directories are created.

    Path: ``{runs_dir}/{run_id}.jsonl``
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir / f"{run_id}.jsonl"


def append(run_file: Path, **entry: Any) -> None:
    """Append one JSON entry to ``run_file``.

    ``ts`` is injected as an ISO-8601 UTC string if not already present.
    The entry is serialised with compact separators and a trailing newline.
    ``default=str`` handles non-JSON-serialisable values.
    """
    if "ts" not in entry:
        entry["ts"] = datetime.now(UTC).isoformat()
    line = json.dumps(entry, separators=(",", ":"), default=str) + "\n"
    atomic_append(run_file, line)


def hash_request(body: dict) -> str:
    """Return a canonical ``sha256:``-prefixed hex digest of ``body``.

    Keys are sorted and compact separators used so the hash is stable under
    key-insertion order differences — identical to the three worker originals.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Runlog:
    """Bound runlog: a ``runs_dir`` value paired with the three operations.

    Use :func:`make_runlog` to construct; the resulting object can be passed
    around instead of threading ``runs_dir`` through every call site.
    """

    runs_dir: Path

    def new_run_file(self, run_id: str) -> Path:
        return new_run_file(run_id, runs_dir=self.runs_dir)

    def append(self, run_file: Path, **entry: Any) -> None:
        append(run_file, **entry)

    def hash_request(self, body: dict) -> str:
        return hash_request(body)


def make_runlog(worker_id: str, *, runs_dir: Path | None = None) -> Runlog:
    """Return a :class:`Runlog` bound to ``runs_dir`` (defaulting to ``.{worker_id}/runs``)."""
    return Runlog(runs_dir=runs_dir if runs_dir is not None else default_runs_dir(worker_id))
