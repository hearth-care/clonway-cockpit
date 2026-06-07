"""Authorization policies for the cockpit write gate.

A **policy** is the seam between "a write is being attempted at the guarded-apply gate" and
"should it proceed" — a callable ``(proposal) -> bool`` handed the gate's proposal (at minimum
``token`` + ``equivalent_cli``; richer where the caller supplies it). The framework ships the
reference policies below; a worker or the orchestrator supplies its own (e.g. WS-B's allowlist
policy that auto-approves a reversible-record set).

**The default everywhere is deny / dry-run.** A write proceeds ONLY when a policy explicitly
authorizes it against a matching per-gate token. Wiring a permissive policy into a real worker
is a deliberate, reviewed act — never a default.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping

# A policy decides whether the write described by ``proposal`` may proceed.
ApprovalPolicy = Callable[[Mapping[str, object]], bool]


def deny_all(_proposal: Mapping[str, object]) -> bool:
    """Never authorize a write — the safe default. The agent can navigate any flow but posts
    nothing unless a caller supplies a policy that authorizes."""
    return False


def approve_all(_proposal: Mapping[str, object]) -> bool:
    """Authorize EVERY write. The reference auto-approver — used by the golden-path test and the
    seed WS-B's allowlist policy refines.

    NOT a default: wiring this into a real worker means every gated write posts, with no human
    and no allowlist. Use only in tests, or behind an explicit, reviewed opt-in."""
    return True


class AllowlistPolicy:
    """Auto-approve a write ONLY if its capability is on an operator-enabled allowlist AND it
    does not move money — WS-B's autonomous policy (the agent posts the reversible bookkeeping
    set without a human; the operator audits after).

    Two locks: (1) the capability key must be in ``allowlist`` — the operator's deliberate
    opt-in per capability; an EMPTY allowlist authorizes NOTHING, so this is safe by default.
    (2) a ``money_movement`` proposal is REFUSED even if its key is allowlisted — the structural
    money-direction line cannot be opted out of by mistake. A proposal with no capability key
    (an untagged/legacy gate) is never auto-approved."""

    def __init__(self, allowlist, *, label: str = "") -> None:  # noqa: ANN001
        self.allowlist = frozenset(allowlist)
        self.label = label

    def __call__(self, proposal: Mapping[str, object]) -> bool:
        if proposal.get("money_movement"):
            return False  # structural exclusion — never auto-approve a money-direction write
        key = proposal.get("capability_key")
        return bool(key) and key in self.allowlist


def prompt_human(
    proposal: Mapping[str, object],
    *,
    input_fn: Callable[[], str] = input,
    out=None,  # noqa: ANN001 — a writable stream; defaults to stderr
) -> bool:
    """Reference interactive approver: show the proposal and read a y/N decision. The concrete
    human-in-the-loop policy.

    Writes the prompt to ``out`` (default ``stderr``) so it never pollutes a JSON ``stdout``
    channel a driver may be reading. ``input_fn`` is injectable for tests."""
    stream = out if out is not None else sys.stderr
    cli = proposal.get("equivalent_cli", "(unknown action)")
    print(f"Apply: {cli}  [y/N] ", end="", file=stream, flush=True)
    return input_fn().strip().lower() in ("y", "yes")
