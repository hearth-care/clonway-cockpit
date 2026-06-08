"""Group-chat orchestration — distributed self-selection that DISSOLVES the router.

The owner + every persona share one space. The owner asks generally; each persona
independently answers the NARROW, reliable question *"is this mine?"* and either
volunteers or stays quiet. Nothing needs to know everyone's domain, so there is no
fragile central router — a wrong self-selection just means a persona stays quiet (or
the owner re-asks), never a mis-route that DOES the wrong thing.

Three safety traps are built in (the group room is shared blast radius):
- **quiet-by-default** — a persona speaks only when @-addressed or when the owner's
  general message is clearly its domain; agent chatter it isn't addressed in is ignored.
- **owner-only commands** — only the OWNER's messages are *commands* (:func:`is_command`).
  A persona may chat back to another persona, but an agent can never *instruct* it to act:
  agent messages are data, not commands.
- **turn cap** — after ``max_persona_turns`` consecutive persona turns without an owner
  message, persona→persona replies stop (defeats bot↔bot loops). The owner re-engaging
  resets the guard.

The framework owns the *mechanics*. The real Google Chat transport (the live surface) is a
worker/operator deploy; here a :class:`ChatTransport` Protocol + :class:`FakeChatTransport`
let the whole thing run headlessly. How a persona actually composes a reply is an injected
``responder`` (the gateway / a conversational loop in production; a stub in tests).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from .persona import Persona, PersonaRegistry

_MENTION_RE = re.compile(r"@([a-z0-9][a-z0-9_-]*)")
# Cheap domain-keyword stoplist — words that carry no domain signal.
_STOP = frozenset(
    {"the", "and", "for", "you", "your", "with", "who", "what", "where", "keeps", "points", "right"}
)


@dataclass(frozen=True)
class ChatMessage:
    """One message in the space. ``is_owner`` is the trust boundary — only the owner's
    messages are commands. ``mentions`` are the persona handles @-addressed in ``text``."""

    text: str
    author: str  # author id (an owner id, or a persona handle)
    is_owner: bool
    space: str = ""
    mentions: tuple[str, ...] = ()

    @staticmethod
    def from_text(text: str, *, author: str, is_owner: bool, space: str = "") -> ChatMessage:
        return ChatMessage(
            text=text,
            author=author,
            is_owner=is_owner,
            space=space,
            mentions=extract_mentions(text),
        )


@dataclass(frozen=True)
class PostedReply:
    handle: str
    text: str


class ChatTransport(Protocol):
    """Structural type for a chat surface. The real one is a Google Chat add-on (operator
    deploy); :class:`FakeChatTransport` is the in-memory stand-in."""

    def post(self, space: str, text: str) -> None: ...

    def iter_messages(self, space: str) -> Iterable[ChatMessage]: ...


@dataclass
class FakeChatTransport:
    """In-memory transport: ``post`` records, ``iter_messages`` replays seeded messages."""

    seeded: dict[str, list[ChatMessage]] = field(default_factory=dict)
    posted: list[tuple[str, str]] = field(default_factory=list)

    def post(self, space: str, text: str) -> None:
        self.posted.append((space, text))

    def iter_messages(self, space: str) -> Iterable[ChatMessage]:
        return list(self.seeded.get(space, []))


def extract_mentions(text: str) -> tuple[str, ...]:
    """The persona handles @-addressed in ``text`` (e.g. ``"@milo"`` → ``("milo",)``)."""
    return tuple(dict.fromkeys(_MENTION_RE.findall(text.lower())))


def _keyword_domain_match(text: str, persona: Persona) -> bool:
    """Cheap default 'is this mine?' gate: does the message mention a salient word from the
    persona's domain? A placeholder for a real cheap-model gate (inject via ``domain_matches``)."""
    words = {w for w in re.findall(r"[a-z]{4,}", persona.domain.lower()) if w not in _STOP}
    haystack = text.lower()
    return any(w in haystack for w in words)


def is_command(message: ChatMessage) -> bool:
    """Only the OWNER's messages are commands (can trigger an action). Agent chatter — even
    an agent 'asking' for a write — is data, never a command. The owner is the air-gap."""
    return message.is_owner


def should_respond(
    message: ChatMessage,
    persona: Persona,
    *,
    domain_matches: Callable[[str, Persona], bool] | None = None,
) -> bool:
    """Whether ``persona`` should speak to ``message`` — the narrow self-selection gate.

    Yes if the persona is @-addressed (by anyone), OR the owner asked a general question
    that is clearly this persona's domain. Otherwise quiet (the default)."""
    if persona.handle == message.author:
        return False  # never reply to your own message
    if persona.handle in message.mentions:
        return True
    matcher = domain_matches or _keyword_domain_match
    return bool(message.is_owner and matcher(message.text, persona))


@dataclass
class GroupChatOrchestrator:
    """Runs a round of the space: the personas that self-select post replies, with the
    owner-only-command and turn-cap guards enforced. ``responder`` composes a persona's
    reply text (return ``None`` to decline) — injected so production can use a gateway loop
    and tests can stub it."""

    transport: ChatTransport
    registry: PersonaRegistry
    responder: Callable[[Persona, ChatMessage], str | None]
    max_persona_turns: int = 6
    domain_matches: Callable[[str, Persona], bool] | None = None

    def run_round(self, space: str, inbound: list[ChatMessage]) -> list[PostedReply]:
        """Process ``inbound`` (and any persona replies they trigger) until the space goes
        quiet or the turn cap stops persona→persona chatter. Returns the replies posted."""
        queue: list[ChatMessage] = list(inbound)
        posted: list[PostedReply] = []
        turns_since_owner = 0
        while queue:
            msg = queue.pop(0)
            if msg.is_owner:
                turns_since_owner = 0  # the owner re-engaging resets the loop guard
            for persona in self.registry.all():
                if not should_respond(msg, persona, domain_matches=self.domain_matches):
                    continue
                # Loop guard: once the cap is hit, only the OWNER can re-trigger persona turns.
                if turns_since_owner >= self.max_persona_turns and not msg.is_owner:
                    continue
                reply = self.responder(persona, msg)
                if reply is None:
                    continue
                self.transport.post(space, reply)
                posted.append(PostedReply(handle=persona.handle, text=reply))
                turns_since_owner += 1
                # The reply becomes a new message others may answer (capped above).
                queue.append(
                    ChatMessage.from_text(reply, author=persona.handle, is_owner=False, space=space)
                )
        return posted
