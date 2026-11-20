"""Where the fleet's shared storage bucket comes from, and how a write reports its outcome.

The framework deliberately has no built-in bucket name. A built-in default let a
worker's ordinary test run on a developer machine with working cloud credentials write
into live fleet storage, so every writer and reader here resolves the bucket the same way:

1. an explicit ``bucket=`` argument from the caller; else
2. the ``CLONWAY_FLEET_BUCKET`` environment variable; else
3. none -- the function does nothing, logs one info line, and returns a result the caller
   can inspect (:attr:`FleetStorageOutcome.NOT_CONFIGURED`). It never raises and never
   falls back to a name.

A failed upload or read is logged once at warning with the exception's type and the
object path (never the contents) and reported as :attr:`FleetStorageOutcome.FAILED`.
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum

FLEET_BUCKET_ENV = "CLONWAY_FLEET_BUCKET"

_UNCONFIGURED_MESSAGE = "no fleet bucket configured: reminders are not being published"
_unconfigured_noted = False


class FleetStorageOutcome(StrEnum):
    """What a fleet-storage call did. ``str`` valued, so it prints and compares plainly."""

    OK = "ok"  # the upload or read completed (also: nothing needed publishing)
    DISABLED = "disabled"  # the worker's own flag is off; nothing was attempted
    NOT_CONFIGURED = "not_configured"  # no bucket argument and no CLONWAY_FLEET_BUCKET
    FAILED = "failed"  # attempted and failed; see the warning log line


def resolve_fleet_bucket(bucket: str | None = None) -> str | None:
    """The explicit ``bucket``, else ``$CLONWAY_FLEET_BUCKET``, else ``None``.

    Blank strings count as unset. The environment is read on every call, so a value set
    after import is honoured.
    """
    if bucket is not None and bucket.strip():
        return bucket.strip()
    env = os.environ.get(FLEET_BUCKET_ENV, "").strip()
    return env or None


def note_unconfigured(log: logging.Logger) -> None:
    """Say once per process, at info level, that nothing is being published."""
    global _unconfigured_noted
    if _unconfigured_noted:
        return
    _unconfigured_noted = True
    log.info(_UNCONFIGURED_MESSAGE)


def note_failure(log: logging.Logger, exc: BaseException, path: str) -> None:
    """One warning naming the exception type and the object path. Never the contents."""
    log.warning("fleet storage failed (%s) for %s", type(exc).__name__, path)


def _reset_notices_for_tests() -> None:
    global _unconfigured_noted
    _unconfigured_noted = False
