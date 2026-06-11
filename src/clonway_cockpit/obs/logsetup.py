"""Root-logger setup for worker entrypoints, servers, and scheduled jobs.

Replaces the per-entrypoint ``logging.basicConfig`` / handler wiring that had
drifted across at least five workers (xbook, xhr, xletter, xops, xquill) with
a single function that they can all call identically.

Design constraints:
- **Stdlib-only** — no third-party deps; this module must work in every worker.
- **Idempotent** — a second call reconfigures (replaces handlers) without
  duplicating them; safe if two entry-points in the same process call it.
- **Non-invasive** — only touches the root logger plus the names in ``quiet``;
  never removes or reconfigures any other logger.
- **Not JSON** — ``obs`` events are the structured telemetry channel; this is
  the human / log-explorer channel. Plain text, greppable.

Format: ``%(asctime)s %(levelname)s %(name)s %(message)s`` UTC.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence


def setup_logging(
    worker_id: str,
    *,
    level: str | None = None,
    runtime_env: str | None = None,
    quiet: Sequence[str] = (),
) -> None:
    """Configure the root logger for a worker process.

    Args:
        worker_id: Used to derive the default level env-var
            (``{WORKER_ID.upper()}_LOG_LEVEL``).
        level: Explicit log level string (``"DEBUG"``, ``"INFO"``, …).
            Overrides the env-var. Defaults to ``INFO`` if neither is set.
        runtime_env: Name of the env-var that holds the runtime tag (e.g.
            ``"XBOOK_RUNTIME"``).  When the variable's value is ``"cloud_run"``
            plain ``StreamHandler`` output is used and the format omits ANSI
            codes — Cloud Logging splits on newlines so each record must be a
            single line.  ``None`` means no special cloud-run handling (same
            formatter used regardless of env).
        quiet: Logger names to force to ``WARNING`` (e.g. noisy libs like
            ``"httpx"``, ``"urllib3"``).  Applied after the root logger is
            configured; does not affect the root level.
    """
    env_level_var = f"{worker_id.upper()}_LOG_LEVEL"
    resolved_level_str = level or os.environ.get(env_level_var) or "INFO"
    resolved_level = getattr(logging, resolved_level_str.upper(), logging.INFO)

    in_cloud_run = runtime_env is not None and os.environ.get(runtime_env) == "cloud_run"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = __import__("time").gmtime  # type: ignore[assignment]

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(resolved_level)
    # Replace all existing handlers — idempotent, no duplication.
    root.handlers = [handler]

    for name in quiet:
        logging.getLogger(name).setLevel(logging.WARNING)

    _ = in_cloud_run  # same StreamHandler in both paths; kept for future use
