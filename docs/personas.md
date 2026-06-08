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

This layer is **identity only**. The persona's *character* — the full system-prompt "soul" on
top of the shared constitution — lives in the worker's persona config (e.g.
`config/<persona>.yaml`), not here. Personality lives in the face, not the hands: a pernickety
inspector and a breezy marketer call the *same* gated tools; voice is pure presentation.
