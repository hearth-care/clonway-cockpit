"""Local-only usage telemetry for the cockpit — which capabilities the operator
actually reaches for. Counts live in ``<base>/usage.json`` (the gitignored state
dir); NOTHING financial is stored — only capability keys, action counters, and a
last-touched timestamp. The product question this answers: which tools earn their
place, and which are ignored (undiscovered vs useless).

Two hard guarantees:

* **Local-only, no network.** This module never touches any worker's API or a
  socket. It's a tiny JSON read-modify-write beside the other state files.
* **Best-effort, never crashes the cockpit.** Every read/write is wrapped — a
  missing / unwritable / corrupt file degrades silently (``record`` is a no-op;
  ``load`` returns ``{}``). A telemetry failure must never break a walk or the
  loop, so this is deliberately defensive in a way the rest of the codebase is
  not — the reason is the calm-and-robust contract.

The storage ``base`` is injectable so a worker points it at its own state dir,
and tests write to ``tmp_path`` and never pollute the operator's real counts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# The default state dir. Injectable so a worker overrides it with its own state
# dir (e.g. ``Path(".xbook")``); usage.json sits inside whatever base it gets.
_DEFAULT_BASE = Path(".cockpit")
_FILENAME = "usage.json"

# The three counters every capability row carries. "open" is every time the
# capability was reached; "applied"/"cancelled" are the posting walks' outcome
# branches (so completion = applied / open).
ACTIONS = ("open", "applied", "cancelled")


def _path(base: Path | None) -> Path:
    return (base or _DEFAULT_BASE) / _FILENAME


def load(*, base: Path | None = None) -> dict:
    """Return the usage map ``{key: {"open": N, "applied": N, "cancelled": N,
    "last": "<iso>"}}``. Best-effort: a missing / unreadable / corrupt file (or a
    payload that isn't a dict) returns ``{}`` — never raises."""
    try:
        raw = _path(base).read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — missing/unwritable/corrupt → empty, never raise
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def record(key: str, action: str = "open", *, base: Path | None = None) -> None:
    """Best-effort increment of ``key``'s ``action`` counter, stamping ``last`` to
    now (UTC, ISO). ``action`` ∈ {"open","applied","cancelled"}; an unknown action
    is ignored. Tolerant read-modify-write: a corrupt/missing file starts fresh,
    and ANY failure (unwritable base, encode error, …) is swallowed — recording
    usage must never break the cockpit."""
    if action not in ACTIONS:
        return
    try:
        data = load(base=base)
        row = data.get(key)
        if not isinstance(row, dict):
            row = {}
        for a in ACTIONS:
            if not isinstance(row.get(a), int):
                row[a] = 0
        row[action] = int(row[action]) + 1
        row["last"] = datetime.now(UTC).isoformat(timespec="seconds")
        data[key] = row
        path = _path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:  # noqa: BLE001 — telemetry is best-effort; never break the loop
        return
