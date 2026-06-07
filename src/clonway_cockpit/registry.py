"""Registry of cockpit capabilities — the framework spine shared by every worker.

A worker registers a :class:`CapabilitySpec` per capability at import time; the
cockpit renders its toolkit/menu from :func:`get_capabilities`. A
:class:`WizardContext` (synced state, optional live client, console, prompt fns)
is passed to every handler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console, RenderableType

from clonway_cockpit.model import ScreenModel
from clonway_cockpit.prompts import ConfirmFn, InputFn


@dataclass(frozen=True)
class WizardContext:
    state: dict
    # Opaque to the cockpit framework spine (walk/render/registry never call methods
    # on it — verified). Typed ``object | None`` rather than a concrete client so
    # this context is portable across workers with no back-dep; worker capability
    # cores narrow it to a real client where they need it.
    client: object | None
    console: Console
    input_fn: InputFn
    confirm_fn: ConfirmFn
    present: Callable[[RenderableType], None] | None = (
        None  # cockpit: draw a full screen (screen.update)
    )
    read_key: Callable[[], str] | None = None  # cockpit: read one raw keypress
    # Optional scope hint a launcher can pass so a capability narrows itself to a
    # subset (e.g. a needs-you "Bills overdue" alert launches schedule-bills with
    # focus="overdue", so the plan/review/apply cover just the overdue bills, not
    # every authorised bill). None = no focus = the full capability.
    focus: str | None = None
    # Optional observer the cockpit threads in so a walk's screens are emitted as
    # ScreenModels (for the agent driver). None = not emitting (console/test callers).
    on_screen: Callable[[ScreenModel], None] | None = None
    # Agent dry-run: when True, the write gate (walk.confirm_apply) ALWAYS declines,
    # so an agent driving over stdio (Host.agent_mode) can walk any flow end-to-end
    # and see the review/blast-radius but never posts. Default False = unchanged.
    dry_run: bool = False


Handler = Callable[[WizardContext], None]


@dataclass(frozen=True)
class BlastRadius:
    """What a capability changes — the single source of truth for pre-flight
    copy (used by the cockpit and, later, the docs). `summary` is one line;
    `details` are bullet lines; `reversible` describes idempotency/undo."""

    summary: str
    details: tuple[str, ...] = ()
    reversible: str = ""


@dataclass(frozen=True)
class CapabilitySpec:
    """A toolkit capability shown in the cockpit. `run` is the handler (Doctor,
    walks); None means a reference-only entry that just shows `equivalent_cli`.
    `shelf` is a single letter A-G (see the worker's shelf taxonomy)."""

    key: str
    shelf: str
    title: str
    summary: str
    equivalent_cli: str
    run: Handler | None = None
    blast_radius: BlastRadius | None = None
    beta: bool = False


_CAPABILITIES: dict[str, CapabilitySpec] = {}


def register_capability(spec: CapabilitySpec) -> None:
    """Register (or replace by key) a cockpit capability."""
    _CAPABILITIES[spec.key] = spec


def get_capabilities() -> list[CapabilitySpec]:
    """All registered capabilities, in registration order."""
    return list(_CAPABILITIES.values())


def get_capability(key: str) -> CapabilitySpec | None:
    return _CAPABILITIES.get(key)


def clear_capabilities() -> None:
    """Test-only: empty the capability registry."""
    _CAPABILITIES.clear()
