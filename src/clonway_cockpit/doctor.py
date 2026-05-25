"""Doctor framework types — the data shapes a worker's deep health check builds.

The framework spine carries the ``Probe``/``Fix`` records plus the generic
``verdict()``/``fixes_for()`` helpers; a worker supplies the probe/fix builders
that inspect its own auth, state freshness, config and locks. Nothing
auto-applies (P4) — the cockpit prints the command to run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Fix:
    title: str
    cmd: str
    note: str = ""
    run: Callable[[], str] | None = None  # None => display-only (e.g. browser auth)
    confirm: bool = False  # ask one key before running (state-changing fixes)


@dataclass(frozen=True)
class Probe:
    name: str
    level: str  # "ok" | "warn" | "error"
    detail: str
    fix: Fix | None


def verdict(probes: list[Probe]) -> tuple[int, int]:
    """Return (warnings, errors)."""
    warns = sum(1 for p in probes if p.level == "warn")
    errs = sum(1 for p in probes if p.level == "error")
    return warns, errs


def fixes_for(probes: list[Probe]) -> list[Fix]:
    """The named fixes carried by the probes, in probe order."""
    return [p.fix for p in probes if p.fix is not None]
