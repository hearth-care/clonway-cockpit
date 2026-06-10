"""Per-thread/space conversation memory — the wiring that makes a persona remember a conversation.

This is the *conversation-layer wiring* PR #77 deferred. #77 built the **private per-thread store**
(``private_memory.py``: ``PersonaMemory.thread(scope)``) but called the transcript + the
space-id-to-scope normalization "a separate, later concern"; the Chat transport core (#78) then
pointed at the same seam ("the transport is exactly where a future slice attaches
``PersonaMemory.thread(slug(space_id))``"). This module is that slice.

It is **purely additive**: the reply seam already exists. ``ChatRouter`` (``chat_transport.py``) and
``GroupChatOrchestrator`` (``group_chat.py``) inject a ``responder: (Persona, ChatMessage) -> str |
None``; the reference ``gateway_responder`` (``colleague.py``) is "stateless by design … production
layers a per-space transcript on top". :func:`remembering_responder` is that production layer — same
signature, plus per-thread memory — so swapping it in is the entire integration. Nothing here touches
the router, the orchestrator, the owner-only-command air-gap, or the private-memory store.

See ``docs/thread-memory.md`` and the design spec
``docs/superpowers/specs/2026-06-10-thread-memory-wiring-design.md``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from .colleague import ColleagueRegistry, Completer
from .gateway.types import GatewayError, Message
from .group_chat import ChatMessage
from .persona import Persona
from .private_memory import PersonaMemory, PrivateScope

# Turn roles (the ``kind`` a recorded turn carries on disk, and the basis for the replay role).
USER = "user"
"""A turn the persona received (the owner / inbound message) — replayed as an OpenAI ``user`` turn."""
PERSONA = "persona"
"""A turn the persona itself produced — replayed as an OpenAI ``assistant`` turn."""

DEFAULT_TURNS = 12
"""How many of the most recent turns :meth:`ThreadTranscript.recent` replays by default (≈6
exchanges of context — enough for genuine multi-turn without unbounded prompt growth)."""

# A space-id char that is NOT already slug-safe — replaced with "-" before hashing.
_NON_SLUG = re.compile(r"[^a-z0-9_-]")
_MAX_PREFIX = 32
"""Cap the readable prefix so ``<prefix>-<hash16>`` stays well under the slug length bound while
leaving the debuggable head of the space id intact."""

_TURN_PREFIX = "turn-"
_TURN_DIGITS = 6
"""Zero-pad turn indices so the store's name-sorted ``all()`` reads back in chronological order
(``turn-000009`` sorts before ``turn-000010``); 6 digits = 1M turns of headroom per thread."""
_PREVIEW_MAX = 120
"""Cap the single-line ``summary`` preview a turn carries (the full text lives in the body)."""


def scope_for_space(space_id: str) -> str:
    """Normalize a raw Google Chat space id into a value that satisfies ``is_safe_slug`` — the
    contract #77 assigned to the transport slice (``thread(scope)`` validates the slug, it does not
    derive it).

    Returns ``"<prefix>-<hash16>"``: a readable, lower-cased, slugified head of the space id (so the
    on-disk path is debuggable — ``spaces/AAAAbCdEf`` → ``spaces-aaaabcdef-…``) joined to the first
    16 hex of ``sha256`` of the **original** id. The hash makes the scope **case-fold-collision-proof**
    — two distinct space ids that lower-case to the same prefix still get different scopes, so one
    space's memory can never leak into another. Deterministic (no clock, no randomness) and total: any
    input, including ``""``, yields a valid slug."""
    prefix = _NON_SLUG.sub("-", space_id.lower()).lstrip("-_")[:_MAX_PREFIX] or "s"
    digest = hashlib.sha256(space_id.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _preview(text: str) -> str:
    """The single-line ``summary`` for a turn: its first non-blank line, truncated. (The full,
    possibly multi-line, text is stored in the turn's body.)"""
    first = next((line.strip() for line in text.splitlines() if line.strip()), text.strip())
    return first[:_PREVIEW_MAX]


class ThreadTranscript:
    """A turn-by-turn conversation transcript for one (persona, thread/space), projected onto the
    merged #77 per-thread store. The transcript shape #77 deferred ("a separate, later concern") —
    built here on top of its store, not by changing it.

    Turns are stored as ordinary ``Fact`` files (``turn-NNNNNN``) inside the persona's
    ``thread(scope)`` directory, so isolation is inherited: a transcript lives under ``persona.handle``
    and never bleeds across personas or threads. Reads are best-effort and never raise (a persona that
    has never spoken in a space simply has no history)."""

    def __init__(self, base: Path, handle: str, scope: str) -> None:
        # PersonaMemory validates ``handle`` is a safe slug; ``thread(scope)`` validates the scope on
        # each access and returns a fresh view (so reads reflect on-disk writes — the store's contract).
        self._memory = PersonaMemory(base, handle)
        self._scope = scope

    def _view(self) -> PrivateScope:
        return self._memory.thread(self._scope)

    def record(self, role: str, text: str) -> None:
        """Append one turn (``role`` is :data:`USER` or :data:`PERSONA`). Blank text is **not**
        recorded — an empty model reply or a whitespace-only message leaves no turn (so a declined
        round writes nothing)."""
        body = text.strip()
        if not body:
            return
        view = self._view()
        name = f"{_TURN_PREFIX}{self._next_index(view):0{_TURN_DIGITS}d}"
        view.remember(name=name, kind=role, summary=_preview(body), body=body)

    def recent(self, limit: int = DEFAULT_TURNS) -> list[Message]:
        """The last ``limit`` turns in **chronological** order as gateway messages — a
        :data:`PERSONA` turn replays as ``assistant``, anything else as ``user`` — ready to splice
        between the system prompt and the current message. A missing/empty thread yields ``[]``."""
        turns = [f for f in self._view().all() if f.name.startswith(_TURN_PREFIX)]
        out: list[Message] = []
        for fact in turns[-limit:]:
            role = "assistant" if fact.kind == PERSONA else "user"
            out.append({"role": role, "content": fact.body or fact.summary})
        return out

    @staticmethod
    def _next_index(view: PrivateScope) -> int:
        """The next monotonic turn index — ``max(existing) + 1`` parsed from the turn filenames, so a
        gap never reuses an index and ordering stays stable."""
        indices = [
            int(fact.name[len(_TURN_PREFIX) :])
            for fact in view.all()
            if fact.name.startswith(_TURN_PREFIX) and fact.name[len(_TURN_PREFIX) :].isdigit()
        ]
        return max(indices) + 1 if indices else 0


def remembering_responder(
    colleagues: ColleagueRegistry,
    completer: Completer,
    *,
    role: str,
    memory_base: Path,
    history_turns: int = DEFAULT_TURNS,
    quiet_on_error: bool = True,
) -> Callable[[Persona, ChatMessage], str | None]:
    """The production layer over :func:`~clonway_cockpit.colleague.gateway_responder`: same
    ``(Persona, ChatMessage) -> str | None`` signature, plus **per-thread memory** — so dropping it
    into ``ChatRouter``/``GroupChatOrchestrator`` in place of the stateless wire is the entire
    multi-turn integration (no router change).

    Per call it derives the thread scope from ``message.space``, splices the recent transcript between
    the persona's soul system prompt and the incoming message, completes, and — **only on a non-empty
    reply** — records the engaged turn pair (the inbound message, then the reply). So each persona's
    transcript is exactly the conversation *it participated in*, isolated under its own handle.

    Boundary-preserving by construction: memory is downstream of routing (the owner-only-command
    air-gap already decided whether this message is acted on), turns reach only the **private** tier
    (a session turn never becomes shared truth — that still requires ``GovernedWriter(source=OWNER)``),
    and an empty ``message.space`` degrades to **stateless** (identical to ``gateway_responder`` — no
    bogus shared bucket). An unknown/soul-less colleague stays quiet (``None``); a ``GatewayError``
    under ``quiet_on_error`` (default) makes *that* persona quiet without discarding the round's other
    replies, and records nothing."""

    def respond(persona: Persona, message: ChatMessage) -> str | None:
        col = colleagues.get(persona.handle)
        if col is None:
            return None
        transcript = (
            ThreadTranscript(memory_base, persona.handle, scope_for_space(message.space))
            if message.space
            else None
        )
        messages: list[Message] = [{"role": "system", "content": col.system_prompt}]
        if transcript is not None:
            messages.extend(transcript.recent(history_turns))
        messages.append({"role": "user", "content": message.text})
        try:
            reply = completer.complete(messages, role=role)
        except GatewayError:
            if quiet_on_error:
                return None
            raise
        text = reply.strip()
        if not text:
            return None
        if transcript is not None:
            transcript.record(USER, message.text)
            transcript.record(PERSONA, text)
        return text

    return respond
