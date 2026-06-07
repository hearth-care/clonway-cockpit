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

    Locks: (1) the capability key must be in ``allowlist`` — the operator's deliberate opt-in
    per capability; an EMPTY allowlist authorizes NOTHING, so this is safe by default. (2) a
    ``money_movement`` proposal is REFUSED even if its key is allowlisted — the structural
    money-direction line cannot be opted out of by mistake. (3) ``max_applies`` caps the number
    of autonomous applies in one session, so a runaway can't post an unbounded batch before a
    human sees it (the scale checkpoint). A proposal with no capability key (untagged/legacy
    gate) is never auto-approved."""

    def __init__(
        self,
        allowlist,  # noqa: ANN001
        *,
        label: str = "",
        max_applies: int | None = None,
    ) -> None:
        self.allowlist = frozenset(allowlist)
        self.label = label
        self.max_applies = max_applies
        self._applied = 0

    def __call__(self, proposal: Mapping[str, object]) -> bool:
        # Structural money-direction exclusion, FAIL-SAFE: a capability is eligible only if
        # money_movement is EXPLICITLY False (the real threaded proposal is always a bool).
        # Anything else — True, or a malformed truthy/falsy non-False value (`[]`,`{}`,`5`,`None`)
        # from an external/crafted proposal — is refused rather than slipping through as "not money".
        if proposal.get("money_movement", False) is not False:
            return False
        key = proposal.get("capability_key")
        if not (bool(key) and key in self.allowlist):
            return False
        # Scale checkpoint: refuse once the per-session apply cap is reached.
        if self.max_applies is not None and self._applied >= self.max_applies:
            return False
        self._applied += 1
        return True


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
