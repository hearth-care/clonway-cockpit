# Personas — the identity layer

A **persona** is the colleague the owner DMs/emails — a name, handle, email, avatar, voice,
and a one-line domain. It is the *face*; the worker repo (the toolkit) is the *hands*. The
persona carries **no** capability — it routes to / narrates its own gated deterministic
tools. Two principles: **"hire the persona, not the program"** (a new colleague = a new
persona pointed at a toolkit; the org chart is the architecture) and **"the persona is the
face, the toolkit is the hands."**

## The model

```python
from pathlib import Path
from clonway_cockpit.persona import Persona, PersonaRegistry, load_persona

p = Persona.from_dict({
    "handle": "milo",                 # required: stable addressable slug [a-z0-9_-]
    "name": "Milo Garth",             # required
    "domain": "the books",            # required: one line — what this colleague owns
    "email": "milo@clonwaycare.co.uk",# optional
    "avatar_ref": "🧮",               # optional: path / url / emoji, resolved by the surface
    "voice": "warm, precise to the penny",  # optional: short style descriptor
})

registry = PersonaRegistry.load_dir(Path("config/personas"))  # every *.toml in a dir
registry.get("milo")        # -> Persona | None
registry.all()              # -> sorted by handle
```

`handle`/`name`/`domain` are required; a missing one or a bad handle raises `PersonaError`.

## Format — and the YAML escape hatch

The batteries-included loader reads **TOML** (`load_persona(path)`, `PersonaRegistry.load_dir`)
because TOML is in the stdlib (`tomllib`, Python 3.12+) and the framework core stays
dependency-free. A worker that keeps personas in YAML (alongside its other `config/*.yaml`)
just parses its own file and calls `Persona.from_dict(...)` — `from_dict` is the real contract;
the TOML loader is a convenience. See `examples/personas/` for two illustrative personas
(`milo`, `quill`).

## Identity vs soul

`Persona` is **identity only**. The persona's *character* is its **soul** — and it lives one
layer up, in `clonway_cockpit.persona_soul`:

```python
from clonway_cockpit.persona_soul import compose_system_prompt, load_soul

soul = load_soul(Path("config/souls/milo.md"))   # the swappable, per-worker voice
system_prompt = compose_system_prompt(soul)        # soul stacked on the SHARED constitution
```

`compose_system_prompt(soul, constitution=DEFAULT_CONSTITUTION)` stacks the swappable soul on
top of the **mandatory constitution** (never fabricate, cite data freshness, owner-only
commands, the approval gate, internal-first) and **validates the constitution is intact** —
personality can flavour the voice but can never edit away a guardrail (`SoulError` if a
required phrase is missing). Two starter souls ship in `examples/souls/` (`milo`, `quill`).

Personality lives in the face, not the hands: a pernickety inspector and a breezy marketer
call the *same* gated tools; voice is pure presentation. **Worker adoption** — pointing a
worker's existing persona-config loader at `compose_system_prompt` — is the per-repo follow-up.

## Colleague — identity + soul, wired to a gateway

`Persona` (the `.toml`) and the soul (the `.md`) are two reps of one colleague; on their own
nothing binds them, and nothing drives a *fleet* through a model. `clonway_cockpit.colleague`
is the wire that closes both gaps. **A `Colleague` is a persona bound to its soul**, and
"add a colleague" becomes one path: drop `<handle>.toml` + `<handle>.md` in a pair of dirs.

```python
from pathlib import Path
from clonway_cockpit.colleague import load_colleagues, gateway_responder
from clonway_cockpit.gateway.config import GatewayConfig
from clonway_cockpit.gateway.gateway import Gateway
from clonway_cockpit.group_chat import FakeChatTransport, GroupSpace

fleet = load_colleagues(Path("config/personas"), Path("config/souls"))  # pairs by handle
fleet.get("milo").system_prompt   # soul stacked on the validated constitution
fleet.registry                    # the identity-only PersonaRegistry — feeds GroupSpace / route

gw = Gateway(GatewayConfig.from_dict({"roles": {"chat": {
    "provider": "openai_compatible", "base_url": "http://localhost:11434/v1",  # local Ollama
    "model": "qwen2.5:0.5b"}}}))

space = GroupSpace(
    space_id="ops", registry=fleet.registry, transport=FakeChatTransport(),
    responder=gateway_responder(fleet, gw, role="chat"),   # <- the reference wire
)
space.owner_says("can you check our VAT return?")   # the matching colleague replies via the model
```

`gateway_responder` is the reference `responder` the group room injects in place of the
`echo_responder` stub: for the persona that self-selects, it composes that persona's **own**
soul into the system prompt, sends it plus the inbound message through the gateway at `role`,
and returns the reply — so the *whole fleet* converses, not just a hand-wired Milo. It is
stateless by design (system + the one message; production layers a per-space transcript on
top), stays **quiet** when a persona has no soul or the model returns empty, and (by default)
stays quiet on a `GatewayError` so one colleague's model hiccup doesn't crash the round.
Nothing here can move money or send — a responder only returns text into the room, and the
owner-only-command air-gap (`is_command`) is unchanged. Runnable end-to-end demo (no network,
fake completer): `examples/fleet_chat_demo.py`; swap the fake for a `Gateway` to go live.
