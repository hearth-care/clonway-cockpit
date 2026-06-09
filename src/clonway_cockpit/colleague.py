"""Wire a fleet up: bind each persona to its soul and let any of them converse.

A :class:`~clonway_cockpit.persona.Persona` is the face (handle/name/domain/voice); a *soul*
(:mod:`clonway_cockpit.persona_soul`) is the character; the model :mod:`clonway_cockpit.gateway`
is the voice-box. They shipped as three correct but DISCONNECTED libraries — nothing bound a
persona to its soul, and there was no reference ``responder`` that drove a *fleet* through the
gateway (only one hand-wired Milo could talk). This module is that wire.

- :class:`Colleague` reconciles the two character reps — identity (the ``.toml``) and soul (the
  ``.md``) — into ONE thing, so "add a colleague" is one coherent path: drop ``<handle>.toml``
  and ``<handle>.md`` in a pair of dirs and :func:`load_colleagues` pairs them by handle.
- :func:`gateway_responder` is the reference ``responder`` the group room
  (:class:`clonway_cockpit.group_chat.GroupChatOrchestrator`) injects: persona → its soul's
  system prompt → a gateway ``complete`` → the reply text. Swap the ``echo_responder`` stub for
  this and the *whole fleet* converses against a real (or local) model, not just Milo.

The framework owns the *wire*; the souls + identities are per-worker data, and which model a
role resolves to is gateway config. Nothing here can move money or send: a responder only
returns text into the group room, and the room's owner-only-command air-gap
(:func:`clonway_cockpit.group_chat.is_command`) is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .gateway.types import GatewayError, Message
from .group_chat import ChatMessage
from .persona import Persona, PersonaError, PersonaRegistry, load_persona
from .persona_soul import compose_system_prompt, load_soul


class Completer(Protocol):
    """The one method the responder needs from a model gateway — structurally satisfied by
    :class:`clonway_cockpit.gateway.gateway.Gateway`. Kept narrow so a test can inject a fake
    and the wire never imports a concrete adapter."""

    def complete(self, messages: list[Message], *, role: str) -> str: ...


@dataclass(frozen=True)
class Colleague:
    """A persona (the face) bound to its soul (the character) — the unit that "add a colleague"
    deals in, reconciling the two reps that used to live apart (the ``.toml`` and the ``.md``)."""

    persona: Persona
    soul: str

    @property
    def system_prompt(self) -> str:
        """The full system prompt: this colleague's soul stacked on the shared constitution.
        Raises :class:`clonway_cockpit.persona_soul.SoulError` if a guardrail phrase is missing
        (the soul can flavour the voice but never edit away the constitution)."""
        return compose_system_prompt(self.soul)


@dataclass(frozen=True)
class ColleagueRegistry:
    """The fleet: colleagues keyed by handle. Exposes a
    :class:`~clonway_cockpit.persona.PersonaRegistry` (so it drops straight into a group space
    or the receptionist) plus the soul lookup the responder needs."""

    colleagues: dict[str, Colleague]

    @property
    def registry(self) -> PersonaRegistry:
        """The identity-only view — feed this to ``GroupSpace`` / ``route``."""
        return PersonaRegistry.from_personas([c.persona for c in self.colleagues.values()])

    def get(self, handle: str) -> Colleague | None:
        return self.colleagues.get(handle)

    def all(self) -> list[Colleague]:
        return sorted(self.colleagues.values(), key=lambda c: c.persona.handle)


def load_colleague(personas_dir: Path, souls_dir: Path, handle: str) -> Colleague:
    """Load one colleague: ``<handle>.toml`` (identity) + ``<handle>.md`` (soul).

    The filename IS the handle — if a ``.toml``'s declared ``handle`` field disagrees with its
    filename the pairing would silently cross wires, so that mismatch raises rather than loads
    a colleague whose soul belongs to someone else."""
    persona = load_persona(personas_dir / f"{handle}.toml")
    if persona.handle != handle:
        raise PersonaError(
            f"persona handle {persona.handle!r} does not match filename {handle!r} — "
            f"name the file {persona.handle}.toml (+ {persona.handle}.md) so identity and soul pair"
        )
    soul = load_soul(souls_dir / f"{handle}.md")
    return Colleague(persona=persona, soul=soul)


def load_colleagues(personas_dir: Path, souls_dir: Path) -> ColleagueRegistry:
    """Pair every ``<handle>.toml`` in ``personas_dir`` with its ``<handle>.md`` in ``souls_dir``.

    Every identity MUST have a soul: a missing ``<handle>.md`` raises (a colleague booting
    voiceless is a misconfiguration, not a quiet default). Extra souls with no matching identity
    are ignored. Raises :class:`PersonaError` if a dir is missing or no personas are found."""
    if not personas_dir.is_dir():
        raise PersonaError(f"personas dir not found: {personas_dir}")
    if not souls_dir.is_dir():
        raise PersonaError(f"souls dir not found: {souls_dir}")
    colleagues: dict[str, Colleague] = {}
    for toml_path in sorted(personas_dir.glob("*.toml")):
        col = load_colleague(personas_dir, souls_dir, toml_path.stem)
        colleagues[col.persona.handle] = col
    if not colleagues:
        raise PersonaError(f"no personas (*.toml) found in {personas_dir}")
    return ColleagueRegistry(colleagues=colleagues)


def gateway_responder(
    colleagues: ColleagueRegistry,
    completer: Completer,
    *,
    role: str,
    quiet_on_error: bool = True,
) -> Callable[[Persona, ChatMessage], str | None]:
    """The reference ``responder`` for a group space / DM: compose the speaking persona's soul
    into a system prompt, send it plus the inbound message through ``completer`` at ``role``,
    and return the reply text. This is the wire ``GroupChatOrchestrator``/``GroupSpace`` inject
    in place of ``echo_responder`` to make a fleet actually converse.

    Stateless by design — system prompt + the one inbound message. It is the minimal honest
    wire, not a conversation manager; production layers a per-space transcript on top (the
    ``ChatTransport`` already records one). A persona with no loaded soul returns ``None`` — it
    stays quiet rather than speak un-constituted — and an empty model reply also returns
    ``None`` (no blank post).

    ``quiet_on_error`` (default ``True``): a :class:`GatewayError` (model down / timeout / bad
    key) makes *that* persona stay quiet instead of crashing the whole round — one colleague's
    model hiccup must not discard the replies already posted. Only ``GatewayError`` is caught;
    a real bug still raises. Set ``False`` to let model failures propagate."""

    def respond(persona: Persona, message: ChatMessage) -> str | None:
        col = colleagues.get(persona.handle)
        if col is None:
            return None
        messages: list[Message] = [
            {"role": "system", "content": col.system_prompt},
            {"role": "user", "content": message.text},
        ]
        try:
            reply = completer.complete(messages, role=role)
        except GatewayError:
            if quiet_on_error:
                return None
            raise
        return reply.strip() or None

    return respond
