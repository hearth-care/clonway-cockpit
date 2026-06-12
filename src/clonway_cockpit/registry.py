"""Registry of cockpit capabilities — the framework spine shared by every worker.

A worker registers a :class:`CapabilitySpec` per capability at import time; the
cockpit renders its toolkit/menu from :func:`get_capabilities`. A
:class:`WizardContext` (synced state, optional live client, console, prompt fns)
is passed to every handler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.console import Console, RenderableType

from clonway_cockpit.audit_log import AuditSink
from clonway_cockpit.model import ScreenModel
from clonway_cockpit.prompts import ConfirmFn, InputFn


@dataclass(frozen=True)
class WizardContext[ClientT]:
    state: dict
    # Opaque to the cockpit framework spine (walk/render/registry never call methods on it).
    # Workers can bind this type parameter so handlers see their concrete client.
    client: ClientT | None
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
    # M4 guarded apply (opt-in): when set, the write gate offers a token handshake
    # instead of a blanket decline. Given {"token", "equivalent_cli"} it returns True
    # iff an authorized {"apply":true,"token":<token>} was received (the stdio pump
    # provides it under serve_stdio(allow_apply=True)). None = no guarded apply =
    # pure dry-run. Only consulted when ``dry_run`` is True.
    authorize_apply: Callable[[dict], bool] | None = None
    # WS-B autonomous-policy context: the identity of the capability whose walk is running,
    # threaded by shell._open_capability so the write gate can hand an authorization policy a
    # proposal it can DECIDE on (capability key + whether it moves money) — not just a token.
    # Defaults keep every existing WizardContext construction unchanged.
    capability_key: str | None = None
    capability_money_movement: bool = False
    # Optional framework audit sink. None keeps existing workers byte-identical.
    audit: AuditSink | None = None
    audit_worker: str = "cockpit"


AnyWizardContext = WizardContext[object]
Handler = Callable[[WizardContext[Any]], None]


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
    # WS-B: does this capability MOVE MONEY or change a payment destination (vs write a
    # reversible bookkeeping record)? A money_movement capability can NEVER be auto-approved by
    # an AllowlistPolicy, even if mistakenly allowlisted — the structural money-direction line.
    # Default False = reversible record (the safe, auto-approvable class).
    money_movement: bool = False


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
