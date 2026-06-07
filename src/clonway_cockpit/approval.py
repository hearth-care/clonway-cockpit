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
