"""Best-effort, local-only per-call usage telemetry for the model gateway.

Mirrors ``clonway_cockpit.usage`` exactly in posture: local file, no extra
network, and NEVER crashes the call. The difference is the shape — this is a
per-call EVENT stream (one JSONL line per model call, carrying tokens + an
estimated cost) rather than usage.py's capability-open counter rollup. It is the
model-£ stream xops cannot currently see (providers bill outside GCP); a later
slice has xops read it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_BASE = Path(".cockpit")
_FILENAME = "model_usage.jsonl"


def _path(base: Path | None) -> Path:
    return (base or _DEFAULT_BASE) / _FILENAME


def record_call(
    base: Path | None,
    *,
    role: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    est_cost: float | None,
    ok: bool,
    err: str | None,
) -> None:
    """Append one usage event as a JSONL line. Best-effort: any failure
    (unwritable base, encode error) is swallowed — telemetry must never turn a
    good model call into a failed one."""
    try:
        event = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "role": role,
            "provider": provider,
            "model": model,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "est_cost": est_cost,
            "ok": bool(ok),
            "err": err,
        }
        path = _path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 — telemetry is best-effort; never break a call
        return


def load_events(base: Path | None = None) -> list[dict]:
    """Read the recorded events back (tests + a later xops reader). Best-effort:
    a missing / unreadable file returns ``[]``; corrupt lines are skipped."""
    try:
        text = _path(base).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — missing/unreadable → empty, never raise
        return []
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --- Fleet fan-in -------------------------------------------------------------
# The gateway writes model_usage.jsonl locally in each worker. To build a
# fleet-wide view (xops's cost page), each worker fans its file out to a shared
# location under a per-worker path; xops lists that prefix and derives the worker
# from the path. The framework provides the path convention + the flush logic +
# a stdlib local-dir sink; the GCS-client sink is the caller's, so the framework
# stays dependency-free.

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Sink = Callable[[str, bytes], None]


def fanin_relpath(*, worker: str, run_id: str, date: str) -> str:
    """The canonical fleet fan-in path for a worker's model-usage, relative to a
    fleet telemetry root: ``model-usage/<worker>/<date>/<run_id>.jsonl``."""
    return f"model-usage/{worker}/{date}/{run_id}.jsonl"


def local_dir_sink(root: Path) -> Sink:
    """A stdlib sink that writes fan-in objects under a local directory ``root``
    (a fan-in dir, or a GCS-FUSE mount). The GCS-client sink is the caller's."""

    def _sink(relpath: str, data: bytes) -> None:
        target = (root / relpath).resolve()
        # Defence-in-depth: refuse to write outside root even if a caller passes a
        # relpath directly (flush_model_usage only ever passes validated templates).
        if not target.is_relative_to(root.resolve()):
            raise ValueError(f"fan-in relpath escapes the root: {relpath!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    return _sink


def flush_model_usage(
    base: Path | None, *, worker: str, run_id: str, date: str, sink: Sink
) -> str | None:
    """Fan a worker's local ``model_usage.jsonl`` out to a fleet location via
    ``sink(relpath, data)``. Returns the relpath written, or ``None`` if there was
    nothing to flush or ``worker``/``run_id``/``date`` aren't safe path segments.

    Best-effort and never-raises: a missing file or a sink error is swallowed —
    fan-in must never break a run.
    """
    if not (_SLUG_RE.fullmatch(worker) and _SLUG_RE.fullmatch(run_id) and _DATE_RE.fullmatch(date)):
        return None
    try:
        data = _path(base).read_bytes()
    except OSError:
        return None
    if not data.strip():
        return None
    relpath = fanin_relpath(worker=worker, run_id=run_id, date=date)
    try:
        sink(relpath, data)
    except Exception:  # noqa: BLE001 — fan-in is best-effort; never break a run
        return None
    return relpath
