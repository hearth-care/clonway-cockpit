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
