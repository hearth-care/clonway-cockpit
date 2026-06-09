"""The receptionist — a front door that POINTS, never DOES.

The natural front door to the fleet is a receptionist (the secretary), not a god-router:
"that's a bookkeeping one — talk to Milo." The distinction is load-bearing. A router must be
flawless because it ACTS on its decision; a receptionist is robust because a wrong guess just
mis-directs — the owner re-asks, no harm done. So the receptionist only ever returns a
*pointer* to a persona; it never calls a tool or takes an action.

:func:`route` matches an incoming message to a persona by ``@``-mention (explicit) or domain
(the same cheap "is this mine?" gate the group space uses, injectable). One match → point to
it; several → name the candidates and ask; none → offer to list the team.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .group_chat import domain_match, extract_mentions
from .persona import Persona, PersonaRegistry


@dataclass(frozen=True)
class Route:
    """The receptionist's answer — who to talk to. It POINTS; it never acts.

    ``persona`` is the single best match (``None`` when ambiguous or unknown); ``candidates``
    lists every match; ``message`` is the human-readable pointer to show the owner."""

    persona: Persona | None
    candidates: list[Persona] = field(default_factory=list)
    message: str = ""

    @property
    def kind(self) -> str:
        if self.persona is not None:
            return "direct"
        if self.candidates:
            return "ambiguous"
        return "none"


def route(
    text: str,
    registry: PersonaRegistry,
    *,
    domain_matches: Callable[[str, Persona], bool] | None = None,
) -> Route:
    """Point ``text`` at the persona who owns it. ``@``-mention wins; else domain match."""
    # An explicit @-mention is a direct address — honour it over domain inference.
    raw = extract_mentions(text)
    resolved = [p for h in raw if (p := registry.get(h)) is not None]
    if len(resolved) == 1:
        p = resolved[0]
        return Route(persona=p, candidates=resolved, message=f"That's {p.name} — {p.domain}.")
    if len(resolved) > 1:
        names = " and ".join(f"@{p.handle}" for p in resolved)
        return Route(
            persona=None, candidates=resolved, message=f"That's for {names} — both can chime in."
        )
    if raw:
        # the owner addressed someone, but no persona has that handle — don't silently
        # fall through to a domain guess and claim it was a direct match.
        unknown = ", ".join(f"@{h}" for h in raw)
        return Route(
            persona=None, message=f"I don't recognise {unknown}. Want me to list the team?"
        )

    matcher = domain_matches or domain_match
    matches = [p for p in registry.all() if matcher(text, p)]
    if len(matches) == 1:
        p = matches[0]
        return Route(
            persona=p,
            candidates=matches,
            message=f"That's {p.name}'s — {p.domain}. Talk to @{p.handle}.",
        )
    if len(matches) > 1:
        names = " or ".join(f"@{p.handle}" for p in matches)
        return Route(
            persona=None,
            candidates=matches,
            message=f"That could be {names} — who did you mean?",
        )
    return Route(
        persona=None,
        candidates=[],
        message="I'm not sure who owns that — want me to list the team?",
    )
