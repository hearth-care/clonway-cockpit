"""Persona identity — the thin, worker-agnostic "face" layer.

A :class:`Persona` is the colleague an owner DMs/emails: a name, a handle, an email,
an avatar, a voice, and a one-line domain ("what this colleague owns"). It carries NO
domain capability — the toolkit (the worker repo) is the hands; the persona is the face.
"Hire the persona, not the program": a new colleague is a new persona pointed at a toolkit.

The framework owns only the *shape* + load/validate (stdlib ``tomllib`` — the core stays
dependency-free). A worker that keeps personas in YAML parses its own file and calls
:meth:`Persona.from_dict`; the registry's ``.toml`` loader is the batteries-included path.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# A handle is a stable, addressable slug (e.g. "milo") — lowercase, used to @-address the
# persona and to key the registry. Kept strict so it's safe in a path / an @mention.
_HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

_REQUIRED = ("handle", "name", "domain")


class PersonaError(ValueError):
    """A persona definition is missing a required field or is otherwise invalid."""


@dataclass(frozen=True)
class Persona:
    """One colleague's identity. ``handle``/``name``/``domain`` are required; the rest are
    presentation the surface resolves (an ``avatar_ref`` is a worker-resolved path/emoji)."""

    handle: str  # stable addressable slug, e.g. "milo"
    name: str  # human name, e.g. "Milo Garth"
    domain: str  # one line — what this colleague owns ("the books")
    email: str = ""
    avatar_ref: str = ""  # path / url / emoji, resolved by the surface
    voice: str = ""  # short style descriptor for the persona's writing

    @staticmethod
    def from_dict(data: dict) -> Persona:
        if not isinstance(data, dict):
            raise PersonaError("persona definition must be a table/object")
        missing = [k for k in _REQUIRED if not str(data.get(k, "")).strip()]
        if missing:
            raise PersonaError(f"persona missing required field(s): {missing}")
        handle = str(data["handle"]).strip()
        if not _HANDLE_RE.fullmatch(handle):
            raise PersonaError(
                f"persona handle {handle!r} must be a lowercase slug ([a-z0-9] then [a-z0-9_-])"
            )
        return Persona(
            handle=handle,
            name=str(data["name"]).strip(),
            domain=str(data["domain"]).strip(),
            email=str(data.get("email", "")).strip(),
            avatar_ref=str(data.get("avatar_ref", "")).strip(),
            voice=str(data.get("voice", "")).strip(),
        )


def load_persona(path: Path) -> Persona:
    """Load one persona from a ``.toml`` file. Raises :class:`PersonaError` on a missing or
    malformed file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PersonaError(f"could not read persona {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PersonaError(f"invalid TOML in persona {path}: {exc}") from exc
    return Persona.from_dict(data)


@dataclass(frozen=True)
class PersonaRegistry:
    """The org chart: personas keyed by handle. The registry IS the architecture —
    add a colleague by adding a persona."""

    personas: dict[str, Persona]

    @staticmethod
    def from_personas(items: list[Persona]) -> PersonaRegistry:
        registry: dict[str, Persona] = {}
        for p in items:
            if p.handle in registry:
                raise PersonaError(f"duplicate persona handle: {p.handle!r}")
            registry[p.handle] = p
        return PersonaRegistry(personas=registry)

    @staticmethod
    def load_dir(path: Path) -> PersonaRegistry:
        """Load every ``*.toml`` persona in a directory (sorted by filename)."""
        if not path.is_dir():
            raise PersonaError(f"persona dir not found: {path}")
        return PersonaRegistry.from_personas([load_persona(p) for p in sorted(path.glob("*.toml"))])

    def get(self, handle: str) -> Persona | None:
        return self.personas.get(handle)

    def all(self) -> list[Persona]:
        return sorted(self.personas.values(), key=lambda p: p.handle)
