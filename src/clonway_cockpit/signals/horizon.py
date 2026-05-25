"""The shared forward-scan contract — a worker's proactive horizon as a
first-class framework concept (Signal-Layer Mechanism 2).

The onboarding guide calls ``scan_horizon()`` *mandatory*: a worker must declare
its **forward-looking** alerts (insurance renewals, filing deadlines, pay runs
due to post) with a real ``due_at``, not just its right-now ones. Until now that
contract lived only in prose — each worker hand-rolled a ``build_<worker>_signals``
with the ``(*, today, now) -> Sequence[Signal]`` shape that
``emit_signals(build=...)`` consumes. This module names that shape and gives
workers a way to declare and compose horizon scans.

Three pieces, all OPTIONAL/additive — existing ``build_*_signals`` keep working
untouched:

* ``ScanHorizon`` — the canonical protocol for "a worker's proactive horizon
  scan": ``(*, today, now) -> Sequence[Signal]``. Runtime-checkable so a future
  lint / template can assert a worker exposes one.
* ``compose_horizon(*scanners)`` — formalises what each worker hand-rolls:
  composes one-or-more horizon scanners into the single ``build(*, today, now)``
  callable ``emit_signals`` expects, concatenating their Signals in declaration
  order (stable; no re-sort, no dedup — ``rank_and_cap`` owns that downstream).
* ``scan_horizon`` — a lightweight, transparent marker tagging a function as a
  worker's horizon scan, with ``is_scan_horizon`` to discover it. The decorator
  returns the function unchanged; it only sets a flag attribute so a future C6
  template + a lint/test can assert a worker ships one.

Full code-*enforcement* (a worker can't ship without a horizon) lands with the
C6 worker template, which will bake in this shape; this module is the shared
abstraction that template will use.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as Date
from datetime import datetime
from typing import Protocol, runtime_checkable

from clonway_cockpit.signals.model import Signal

# Attribute the marker stamps on a scanner; namespaced to avoid clashes.
_MARKER_ATTR = "__clonway_scan_horizon__"


@runtime_checkable
class ScanHorizon(Protocol):
    """A worker's proactive forward-scan: ``(*, today, now) -> Sequence[Signal]``.

    The canonical name for the shape ``emit_signals(build=...)`` already
    consumes. ``today``/``now`` are keyword-only (matching how ``emit_signals``
    calls ``build(today=, now=)``); a scanner returns the open forward-looking
    Signals it sees, each ideally with a real ``due_at`` so urgency can sharpen
    as the date approaches without re-raising.
    """

    def __call__(self, *, today: Date, now: datetime) -> Sequence[Signal]: ...


def compose_horizon(*scanners: ScanHorizon) -> ScanHorizon:
    """Compose horizon scanners into one ``build(*, today, now)`` callable.

    Returns the single ``ScanHorizon`` that ``emit_signals(build=...)`` expects,
    concatenating each scanner's Signals in declaration order. Order is stable
    within and across scanners — no re-sort, no dedup, no filtering (the
    ``rank_and_cap`` discipline owns the global cap downstream; this only
    gathers). Zero scanners → a build that always returns ``()``; one scanner →
    a passthrough.
    """

    def build(*, today: Date, now: datetime) -> tuple[Signal, ...]:
        out: list[Signal] = []
        for scan in scanners:
            out.extend(scan(today=today, now=now))
        return tuple(out)

    return build


def scan_horizon[F: ScanHorizon](fn: F) -> F:
    """Mark ``fn`` as a worker's proactive horizon scan.

    Transparent: returns ``fn`` unchanged (same identity, same call behaviour)
    and only stamps a flag attribute so a future C6 template + a lint/test can
    discover that a worker ships a horizon scan. Adopting the marker is optional;
    it changes nothing at runtime.
    """
    setattr(fn, _MARKER_ATTR, True)
    return fn


def is_scan_horizon(obj: object) -> bool:
    """True iff ``obj`` was tagged with the ``@scan_horizon`` marker."""
    return getattr(obj, _MARKER_ATTR, False) is True
