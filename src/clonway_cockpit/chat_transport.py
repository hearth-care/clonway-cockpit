"""Persona Google Chat add-on transport — the **framework-owned** core (the production surface for
the already-proven group-chat wire in ``group_chat.py``).

The fleet's Chat bots are **Workspace add-ons, not classic HTTP Chat apps** — a materially different
model that has burned whole sessions when conflated (see ``docs/persona-platform-architecture.md`` →
"The Chat transport"). This module mirrors the **proven** Auto-HR ``xhr-server`` add-on
(``src/xhr/chat/``):

- **Auth is Cloud Run invoker IAM + an operator-email allowlist — NOT a JWT/audience check.** Pinning
  an audience *rejects* the real add-on traffic; the app-layer gate is :func:`is_operator` on
  ``event.user.email``. This is the single edge that decides ``is_owner`` — i.e. whether a message can
  ever be a command (the owner-only-command air-gap, lifted to the transport edge).
- **The wire envelope is nested** — top-level ``chat: {messagePayload | addedToSpacePayload | … :
  {message, space, user}}`` + ``commonEventObject``, with **no** top-level ``type``.
  :func:`normalize_event` detects and flattens it before anything else looks at it.

The framework owns the transport-agnostic core (normalise → auth → bridge → route); the **worker**
owns the edge (the HTTP route, the outbound Chat REST poster, the Cloud Run deploy), so the framework
stays ``rich``-only. See ``docs/chat-transport.md`` and the design spec
``docs/superpowers/specs/2026-06-10-chat-transport-design.md``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from .group_chat import (
    ChatMessage,
    ChatTransport,
    GroupChatOrchestrator,
    PostedReply,
    domain_match,
    is_command,
)
from .persona import Persona, PersonaRegistry

# Event kinds (the classifier output). MESSAGE is the only kind v1 acts on; the rest are
# surfaced so a worker can log/ignore them deliberately rather than mis-handling an unknown shape.
MESSAGE = "MESSAGE"
ADDED_TO_SPACE = "ADDED_TO_SPACE"
REMOVED_FROM_SPACE = "REMOVED_FROM_SPACE"
CARD_CLICKED = "CARD_CLICKED"
UNKNOWN = "UNKNOWN"

# Which `chat.<key>` add-on payload is present → the event kind it denotes.
_ADDON_PAYLOAD_KINDS = {
    "messagePayload": MESSAGE,
    "addedToSpacePayload": ADDED_TO_SPACE,
    "removedFromSpacePayload": REMOVED_FROM_SPACE,
    "buttonClickedPayload": CARD_CLICKED,
}

_OPERATORS_ENV = "CLONWAY_CHAT_OPERATORS"


@dataclass(frozen=True)
class NormalizedChatEvent:
    """A Chat event flattened to a transport-agnostic shape — whatever the wire envelope, downstream
    code reads these fields. ``raw`` is the untouched original (for the worker / audit)."""

    kind: str
    text: str = ""
    space_id: str = ""
    space_type: str = ""  # "DM" | "ROOM" | ""
    sender_email: str = ""
    sender_name: str = ""
    message_id: str = ""
    raw: dict = field(default_factory=dict)


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    """A string field from an untrusted envelope — only a real ``str`` is kept; anything else
    (a dict/list/int Google never sends here, or a malicious payload) becomes ``""`` rather than
    a surprising ``repr`` that could leak structure or falsely match downstream."""
    return value if isinstance(value, str) else ""


def _extract(*, kind: str, source: dict, raw: dict) -> NormalizedChatEvent:
    """Pull the common ``{message, space, user}`` fields out of ``source`` (the add-on inner payload,
    or the classic flat event) into a :class:`NormalizedChatEvent`."""
    message = _as_dict(source.get("message"))
    space = _as_dict(source.get("space"))
    user = _as_dict(source.get("user"))
    sender = _as_dict(message.get("sender"))
    return NormalizedChatEvent(
        kind=kind,
        text=_text(message.get("text")),
        space_id=_text(space.get("name")),
        # case-normalised so a "dm"/"Dm" can't slip past the "DM" routing check downstream.
        space_type=_text(space.get("type")).upper(),
        # user.email is the add-on sender; fall back to message.sender.email (classic shape).
        sender_email=_text(user.get("email")) or _text(sender.get("email")),
        sender_name=_text(user.get("displayName")) or _text(sender.get("displayName")),
        message_id=_text(message.get("name")),
        raw=raw,
    )


def normalize_event(event: dict) -> NormalizedChatEvent:
    """Normalise an inbound Chat event (Workspace add-on **or** classic flat) into a
    :class:`NormalizedChatEvent`. Best-effort and never-raise: an unrecognised / malformed shape
    yields ``kind="UNKNOWN"`` rather than an exception (a transport must degrade, not fall over).

    Detection mirrors ``xhr-server``: a truthy top-level ``type`` is the classic flat event (read
    directly); otherwise a ``chat`` dict carrying one of the ``*Payload`` keys is the add-on
    envelope (flatten its inner ``{message, space, user}``)."""
    if not isinstance(event, dict):
        return NormalizedChatEvent(kind=UNKNOWN)
    top_type = event.get("type")
    if top_type:  # classic flat event
        return _extract(kind=str(top_type), source=event, raw=event)
    chat = _as_dict(event.get("chat"))
    for key, kind in _ADDON_PAYLOAD_KINDS.items():
        inner = chat.get(key)
        if isinstance(inner, dict):
            return _extract(kind=kind, source=inner, raw=event)
    return NormalizedChatEvent(kind=UNKNOWN, raw=event)


# --- operator trust boundary (mirrors xhr `operator_auth.py`) --------------------------------


def parse_allowlist(raw: str) -> frozenset[str]:
    """Parse a comma-separated operator-email list into a normalised (lower-cased, stripped) set."""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def load_allowlist(env: str = _OPERATORS_ENV) -> frozenset[str]:
    """The operator allowlist from ``env`` (default ``CLONWAY_CHAT_OPERATORS``). Unset → empty set
    → trusts no one (fail-closed)."""
    return parse_allowlist(os.environ.get(env, ""))


def is_operator(email: str, allowlist: frozenset[str]) -> bool:
    """Whether ``email`` is an allowlisted operator. **Fail-closed**: an empty email *or* an empty
    allowlist → ``False``. No JWT / audience / issuer check — that belongs to the classic model and
    would reject the real add-on traffic; the network gate is Cloud Run invoker IAM."""
    if not email or not allowlist:
        return False
    return email.strip().lower() in allowlist


def to_chat_message(event: NormalizedChatEvent, allowlist: frozenset[str]) -> ChatMessage:
    """Bridge a normalised event to a :class:`~clonway_cockpit.group_chat.ChatMessage`. ``is_owner``
    is set **only** for an allowlisted operator email — the air-gap edge: only the owner's word is
    ever a command, so no message a persona or any non-operator sends through the transport can be."""
    return ChatMessage.from_text(
        event.text,
        author=event.sender_email,
        is_owner=is_operator(event.sender_email, allowlist),
        space=event.space_id,
    )


# --- routing into the proven group-chat wire ------------------------------------------------


@dataclass(frozen=True)
class ChatOutcome:
    """The result of handling one inbound event: the replies the self-selecting personas produced
    (also delivered via the transport), and ``ignored`` (empty if handled, else why)."""

    kind: str
    replies: list[PostedReply]
    space_id: str
    ignored: str = ""


def _responds_in_dm(
    message: ChatMessage,
    persona: Persona,
    *,
    sole: bool,
    matcher: Callable[[str, Persona], bool],
) -> bool:
    """Whether ``persona`` replies in a DM. DMs engage **only the owner**: a non-operator's DM is
    data (``is_command`` is False), so it draws no reply — the air-gap holds, and no model turn is
    spent on an outsider. For the owner: an explicit @mention wins; otherwise the **sole** persona
    this deployment serves answers (the common 1:1 DM), or — in a multi-persona DM — only the
    **domain-relevant** persona (not a blanket fan-out to everyone)."""
    if persona.handle == message.author:
        return False
    if not is_command(message):
        return False
    if persona.handle in message.mentions:
        return True
    return sole or matcher(message.text, persona)


@dataclass
class ChatRouter:
    """Routes a normalised Chat event into the proven ``group_chat`` wire: a **DM** to the
    persona(s) this deployment serves, a **named space** through distributed self-selection. The
    air-gap is enforced upstream (``is_owner`` only for an allowlisted operator); the write gate is
    untouched and downstream. ``responder`` composes a persona's reply (inject the gateway loop in
    production, a stub in tests); ``transport`` delivers replies (the worker's Chat REST poster).

    Two add-on constraints are injectable hooks: ``already_handled``/``mark_handled`` dedupe a
    redelivered ``message.name`` (Chat can redeliver); fast-ack is the worker's concern — it returns
    :func:`ack_response` immediately and runs :meth:`handle_event` in a background task that posts the
    replies (this core stays synchronous and transport-agnostic)."""

    registry: PersonaRegistry
    responder: Callable[[Persona, ChatMessage], str | None]
    transport: ChatTransport
    allowlist: frozenset[str]
    max_persona_turns: int = 6
    domain_matches: Callable[[str, Persona], bool] | None = None
    already_handled: Callable[[str], bool] | None = None
    mark_handled: Callable[[str], None] | None = None

    def handle_event(self, event: dict) -> ChatOutcome:
        """Normalise, dedupe, bridge, and route one inbound event. Never raises on a malformed
        envelope (a non-message / unknown shape is acked and ignored); a failure from the injected
        ``responder``/``transport`` **does** propagate — the event is left un-marked so Chat's
        redelivery retries it, rather than being silently dropped."""
        norm = normalize_event(event)
        if norm.kind != MESSAGE:
            # v1 acts only on messages; everything else is acked and ignored, never mis-handled.
            return ChatOutcome(norm.kind, [], norm.space_id, ignored="not-a-message")
        if (
            norm.message_id
            and self.already_handled is not None
            and self.already_handled(norm.message_id)
        ):
            return ChatOutcome(MESSAGE, [], norm.space_id, ignored="duplicate")
        message = to_chat_message(norm, self.allowlist)
        if norm.space_type == "DM":
            replies = self._handle_dm(message)
        else:
            replies = self._handle_space(message)
        # Mark handled ONLY after routing + delivery succeeded. If the responder or transport.post
        # raised above, this line is skipped and the event stays un-marked, so a redelivery retries
        # it — at-least-once on failure (a transient error risks a duplicate reply, never a dropped
        # message). Marking *before* delivery would silence a message whose delivery failed.
        if norm.message_id and self.mark_handled is not None:
            self.mark_handled(norm.message_id)
        return ChatOutcome(MESSAGE, replies, norm.space_id)

    def _handle_dm(self, message: ChatMessage) -> list[PostedReply]:
        personas = self.registry.all()
        sole = len(personas) == 1
        matcher = self.domain_matches or domain_match
        replies: list[PostedReply] = []
        for persona in personas:
            if not _responds_in_dm(message, persona, sole=sole, matcher=matcher):
                continue
            reply = self.responder(persona, message)
            if reply is None:
                continue
            self.transport.post(message.space, reply)
            replies.append(PostedReply(handle=persona.handle, text=reply))
        return replies

    def _handle_space(self, message: ChatMessage) -> list[PostedReply]:
        orchestrator = GroupChatOrchestrator(
            transport=self.transport,
            registry=self.registry,
            responder=self.responder,
            max_persona_turns=self.max_persona_turns,
            domain_matches=self.domain_matches,
        )
        return orchestrator.run_round(message.space, [message])


def ack_response() -> dict:
    """The Chat HTTP reply that acknowledges an event with no message — ``{}``. A worker returns this
    immediately (fast-ack) and posts the real replies asynchronously via the transport."""
    return {}


def text_response(text: str) -> dict:
    """A synchronous Chat text reply — ``{"text": text}`` (e.g. a bounded "still working…")."""
    return {"text": text}
