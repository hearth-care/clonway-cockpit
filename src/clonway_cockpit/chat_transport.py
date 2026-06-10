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
from dataclasses import dataclass, field

from .group_chat import ChatMessage

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


def _extract(*, kind: str, source: dict, raw: dict) -> NormalizedChatEvent:
    """Pull the common ``{message, space, user}`` fields out of ``source`` (the add-on inner payload,
    or the classic flat event) into a :class:`NormalizedChatEvent`."""
    message = _as_dict(source.get("message"))
    space = _as_dict(source.get("space"))
    user = _as_dict(source.get("user"))
    sender = _as_dict(message.get("sender"))
    return NormalizedChatEvent(
        kind=kind,
        text=str(message.get("text") or ""),
        space_id=str(space.get("name") or ""),
        space_type=str(space.get("type") or ""),
        # user.email is the add-on sender; fall back to message.sender.email (classic shape).
        sender_email=str(user.get("email") or sender.get("email") or ""),
        sender_name=str(user.get("displayName") or sender.get("displayName") or ""),
        message_id=str(message.get("name") or ""),
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
