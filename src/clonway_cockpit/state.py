"""Cockpit state snapshot — header fields, pulse pills + needs-you ranking.

The framework spine carries only the data shapes (``CockpitState``, ``NeedsItem``,
``Pill``); a worker computes and populates them from its own status report. The
``report`` slot is typed ``object | None`` so this module has no back-dep on any
worker's status model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date


@dataclass(frozen=True)
class Pill:
    label: str  # "Xero", "Lloyds"
    status: str  # "synced", "never synced"
    detail: str  # "06:45", "3d ago", ""
    level: str  # "ok" | "warn" | "error"
    source: str | None = None  # sync source key: "xero" | "lloyds" | "revolut"


@dataclass(frozen=True)
class NeedsItem:
    title: str
    detail: str
    level: str  # "ok" | "warn" | "error"
    capability_key: str | None  # which capability to launch, if any
    # Optional scope hint threaded to the launched capability's WizardContext.focus
    # so an alert opens a SCOPED view (e.g. "Bills overdue" → schedule-bills with
    # focus="overdue", which plans only the overdue bills). None = the full walk.
    focus: str | None = None
    # Forward-Signal enrichment, consumed only by build_signals — NOT rendered.
    # due_at = the real deadline where one exists (pay date / DD date / cash-breach
    # date); None for action-now and aggregate items. source_id = a stable
    # per-instance business id (cycle:pay_date, provider:coverage) folded into the
    # Signal dedup_key so two concurrent same-title instances get distinct keys.
    due_at: Date | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class CockpitState:
    tenant_name: str
    date_label: str = ""  # "Mon 27 Apr 2026"
    time_label: str = ""  # "08:14"
    tenant_id: str | None = None  # "9b40…"
    pills: tuple[Pill, ...] = ()
    needs: tuple[NeedsItem, ...] = ()
    report: object | None = None
