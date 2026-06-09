# The receptionist — a front door that points, never does

If the fleet wants a single front door, make it a **receptionist**, not a god-router.
"That's a bookkeeping one — talk to Milo." The distinction is load-bearing: a router must be
*flawless* because it acts on its decision; a receptionist is *robust* because a wrong guess
just mis-directs — the owner re-asks, no harm done. So `clonway_cockpit.receptionist.route`
only ever returns a **pointer** to a persona; it never calls a tool or takes an action.

```python
from clonway_cockpit.receptionist import route
from clonway_cockpit.persona import PersonaRegistry

r = route("who handles the cash?", PersonaRegistry.load_dir(Path("config/personas")))
r.kind       # "direct" | "ambiguous" | "none"
r.persona    # the single best match, or None
r.candidates # every match (≥2 when ambiguous)
r.message    # the pointer to show the owner ("That's Milo's — the books. Talk to @milo.")
```

`route` matches by `@`-mention first (an explicit address wins), else by domain — the same
cheap "is this mine?" keyword gate the group space uses, injectable via `domain_matches` for a
real cheap-model gate. One match → point to it; several → name the candidates and ask; none →
offer to list the team. This is the same self-selection question as the group chat, asked from
the front desk instead of in the room — keeping the two consistent (inject the same matcher).
