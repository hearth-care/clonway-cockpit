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

**Redelivery + concurrency (read before deploying live).** Google Chat is at-least-once: it
redelivers on a 5xx / cold start. ``ChatRouter`` dedupes only when the worker injects its
``already_handled`` / ``mark_handled`` hooks — **wire them (a durable store) when you use this**, or a
redelivered message records the turn pair twice and corrupts later prompts. Likewise this records a
turn by reading the current max index and writing the next; **v1 assumes a single writer per
(persona, space)** (the reference ``xhr-server`` fast-acks then posts from one background task) —
truly concurrent writers on one thread can collide. See ``docs/thread-memory.md`` → "Scope & limits"
and the design spec ``docs/superpowers/specs/2026-06-10-thread-memory-wiring-design.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from .colleague import ColleagueRegistry, Completer
from .gateway.types import GatewayError, Message
from .group_chat import ChatMessage
from .persona import Persona
from .persona_soul import SoulError
from .private_memory import PersonaMemory, PrivateScope
from .shared_memory import Fact

# Turn roles (the ``kind`` a recorded turn carries on disk, and the basis for the replay role).
USER = "user"
"""A turn the persona received (the owner / inbound message) — replayed as an OpenAI ``user`` turn."""
PERSONA = "persona"
"""A turn the persona itself produced — replayed as an OpenAI ``assistant`` turn."""

DEFAULT_TURNS = 12
"""How many of the most recent turns :meth:`ThreadTranscript.recent` replays by default (≈6
exchanges of context — enough for genuine multi-turn without unbounded prompt growth)."""

MAX_TURNS_ON_DISK = 200
"""Compaction trigger: a thread keeps at most this many unfolded turns before folding."""

KEEP_TURNS = 100
"""How many newest unfolded turns remain after compaction."""

SUMMARY_MAX_CHARS = 4000
"""Maximum rolling summary body size retained per thread."""

SUMMARY_FACT = "thread-summary"
"""Reserved fact name for the rolling per-thread summary."""

SUMMARY_HEADER = "Earlier in this conversation (compacted summary):"
"""System-message header prepended to compacted summary context."""

# A space-id char that is NOT already slug-safe — replaced with "-" before hashing.
_NON_SLUG = re.compile(r"[^a-z0-9_-]")
_MAX_PREFIX = 32
"""Cap the readable prefix so ``<prefix>-<hash16>`` stays well under the slug length bound while
leaving the debuggable head of the space id intact."""

_TURN_PREFIX = "turn-"
_TURN_DIGITS = 6
"""Zero-pad turn indices so a thread's turn files read in chronological order. Ordering is by parsed
*integer* index (:func:`_turn_index`), not raw filename, so it stays correct even past the
zero-pad width; the padding only keeps the common case lexically tidy on disk."""
_PREVIEW_MAX = 120
"""Cap the single-line ``summary`` preview a turn carries (the full text lives in the body)."""
_FOLDED_RE = re.compile(r"folded-through:\s*(\d+)")
_RECORD_LOCK = threading.Lock()
_LOG = logging.getLogger("clonway_cockpit.chat_memory")


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


def _turn_index(name: str) -> int | None:
    """The integer index of a turn filename (``turn-000007`` → ``7``), or ``None`` if ``name`` is not
    a numeric turn. The **single** definition of "what is a turn", used for BOTH ordering and the
    next-index counter so the two can never disagree (a non-numeric ``turn-*`` fact is not a turn —
    it is neither replayed nor counted)."""
    if not name.startswith(_TURN_PREFIX):
        return None
    suffix = name[len(_TURN_PREFIX) :]
    return int(suffix) if suffix.isdigit() else None


class ThreadTranscript:
    """A turn-by-turn conversation transcript for one (persona, thread/space), projected onto the
    merged #77 per-thread store. The transcript shape #77 deferred ("a separate, later concern") —
    built here on top of its store, not by changing it.

    Turns are stored as ordinary ``Fact`` files (``turn-NNNNNN``) inside the persona's
    ``thread(scope)`` directory, so isolation is inherited: a transcript lives under ``persona.handle``
    and never bleeds across personas or threads. Reads are best-effort and never raise (a persona that
    has never spoken in a space simply has no history)."""

    def __init__(
        self,
        base: Path,
        handle: str,
        scope: str,
        *,
        max_turns: int = MAX_TURNS_ON_DISK,
        keep_turns: int = KEEP_TURNS,
        summary_max_chars: int = SUMMARY_MAX_CHARS,
    ) -> None:
        if not (2 <= keep_turns < max_turns):
            raise ValueError("keep_turns must satisfy 2 <= keep_turns < max_turns")
        if summary_max_chars < 1:
            raise ValueError("summary_max_chars must be >= 1")
        # PersonaMemory validates ``handle`` is a safe slug; ``thread(scope)`` validates the scope on
        # each access and returns a fresh view (so reads reflect on-disk writes — the store's contract).
        self._memory = PersonaMemory(base, handle)
        self._scope = scope
        self._max_turns = max_turns
        self._keep_turns = keep_turns
        self._summary_max_chars = summary_max_chars

    def _view(self) -> PrivateScope:
        return self._memory.thread(self._scope)

    def record(self, role: str, text: str) -> str | None:
        """Append one turn (``role`` is :data:`USER` or :data:`PERSONA`); returns the turn name
        written, or ``None`` if nothing was. Blank text is **not** recorded — an empty model reply or
        a whitespace-only message leaves no turn (so a declined round writes nothing). The returned
        name lets a caller roll the turn back (see :meth:`forget`) if a paired write then fails."""
        body = text.strip()
        if not body:
            return None
        with _RECORD_LOCK:
            view = self._view()
            name = f"{_TURN_PREFIX}{self._next_index(view):0{_TURN_DIGITS}d}"
            view.remember(name=name, kind=role, summary=_preview(body), body=body)
            self._sweep_folded(view)
            self._compact_if_needed(view)
            return name

    def forget(self, name: str) -> bool:
        """Delete one recorded turn by name (used to roll back a half-written turn pair). Returns
        ``True`` if it existed."""
        return self._view().forget(name)

    def forget_thread(self) -> bool:
        """Delete this whole (persona, thread) transcript directory."""
        return self._memory.forget_thread(self._scope)

    def recent(self, limit: int = DEFAULT_TURNS) -> list[Message]:
        """The last ``limit`` turns in **chronological** order as gateway messages — a
        :data:`PERSONA` turn replays as ``assistant``, anything else as ``user`` — ready to splice
        between the system prompt and the current message. Ordered by parsed integer index (correct
        at any scale), and non-turn facts are ignored. A missing/empty thread yields ``[]``."""
        view = self._view()
        self._warn_unreadable_turns(view)
        folded_through = self._folded_through(view)
        indexed = self._unfolded_turns(view, folded_through)
        out: list[Message] = []
        for _idx, fact in indexed[-limit:]:
            role = "assistant" if fact.kind == PERSONA else "user"
            out.append({"role": role, "content": fact.body or fact.summary})
        return out

    def summary(self) -> str | None:
        """The compacted rolling summary body, or ``None`` when absent/unreadable."""
        fact = self._view().get(SUMMARY_FACT)
        return fact.body if fact is not None and fact.body else None

    def context(self, limit: int = DEFAULT_TURNS) -> list[Message]:
        """Compacted summary system message, when present, followed by the recent turn window."""
        messages: list[Message] = []
        body = self.summary()
        if body:
            messages.append({"role": "system", "content": f"{SUMMARY_HEADER}\n{body}"})
        messages.extend(self.recent(limit))
        return messages

    def _next_index(self, view: PrivateScope) -> int:
        """The next monotonic turn index — ``max(existing) + 1``, parsed from the turn filenames via
        :func:`_turn_index`, so a gap never reuses an index and ordering stays stable."""
        indices = [idx for fact in view.all() if (idx := _turn_index(fact.name)) is not None]
        folded_through = self._folded_through(view)
        if folded_through >= 0:
            indices.append(folded_through)
        return max(indices) + 1 if indices else 0

    def _folded_through(self, view: PrivateScope) -> int:
        fact = view.get(SUMMARY_FACT)
        if fact is None or not fact.source:
            return -1
        match = _FOLDED_RE.search(fact.source)
        return int(match.group(1)) if match else -1

    @staticmethod
    def _unfolded_turns(view: PrivateScope, folded_through: int) -> list[tuple[int, Fact]]:
        return sorted(
            (
                (idx, fact)
                for fact in view.all()
                if (idx := _turn_index(fact.name)) is not None and idx > folded_through
            ),
            key=lambda pair: pair[0],
        )

    def _sweep_folded(self, view: PrivateScope) -> None:
        folded_through = self._folded_through(view)
        if folded_through < 0:
            return
        for fact in view.all():
            idx = _turn_index(fact.name)
            if idx is not None and idx <= folded_through:
                view.forget(fact.name)

    def _compact_if_needed(self, view: PrivateScope) -> None:
        turns = self._unfolded_turns(view, self._folded_through(view))
        if len(turns) <= self._max_turns:
            return
        fold_count = len(turns) - self._keep_turns
        to_fold = turns[:fold_count]
        lines = [f"{fact.kind}: {fact.summary}" for _idx, fact in to_fold]
        existing = self.summary()
        body = "\n".join([part for part in (existing, "\n".join(lines)) if part])
        body = self._truncate_summary(body)
        folded_through = to_fold[-1][0]
        view.remember(
            name=SUMMARY_FACT,
            kind="summary",
            summary=body.splitlines()[0],
            body=body,
            source=f"folded-through: {folded_through:0{_TURN_DIGITS}d}",
        )
        for _idx, fact in to_fold:
            view.forget(fact.name)

    def _truncate_summary(self, body: str) -> str:
        if len(body) <= self._summary_max_chars:
            return body
        lines = body.splitlines()
        while len(lines) > 1 and len("\n".join(lines)) > self._summary_max_chars:
            lines.pop(0)
        candidate = "\n".join(lines)
        if len(candidate) <= self._summary_max_chars:
            return candidate
        return candidate[: self._summary_max_chars]

    @staticmethod
    def _warn_unreadable_turns(view: PrivateScope) -> None:
        try:
            turn_files = list(view.path.glob(f"{_TURN_PREFIX}*.md"))
        except (OSError, ValueError):
            return
        parsed_turns = sum(1 for fact in view.all() if _turn_index(fact.name) is not None)
        unreadable = len(turn_files) - parsed_turns
        if unreadable > 0:
            plural = "s" if unreadable != 1 else ""
            _LOG.warning(
                "chat_memory: skipped %d unreadable turn file%s in one thread",
                unreadable,
                plural,
            )


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
    reply** — records the engaged turn pair (the inbound message, then the reply) **atomically**: if
    the reply write fails, the just-written user turn is rolled back so a lone user turn can never
    desync future replay. Each persona's transcript is exactly the conversation *it participated in*,
    isolated under its own handle.

    Boundary-preserving by construction: memory is downstream of routing (the owner-only-command
    air-gap already decided whether this message is acted on), turns reach only the **private** tier
    (a session turn never becomes shared truth — that still requires ``GovernedWriter(source=OWNER)``),
    and an empty ``message.space`` degrades to **stateless** (identical to ``gateway_responder`` — no
    bogus shared bucket). An unknown **or soul-less** colleague stays quiet (``None``) rather than
    raise — an escaping ``SoulError`` would leave the event un-marked and make Chat redeliver forever.
    A ``GatewayError`` under ``quiet_on_error`` (default) makes *that* persona quiet without discarding
    the round's other replies, and records nothing."""

    def respond(persona: Persona, message: ChatMessage) -> str | None:
        col = colleagues.get(persona.handle)
        if col is None:
            return None
        try:
            system_prompt = col.system_prompt
        except SoulError:
            return None  # un-constituted → stays quiet (never crash the round / loop redelivery)
        transcript = (
            ThreadTranscript(memory_base, persona.handle, scope_for_space(message.space))
            if message.space
            else None
        )
        messages: list[Message] = [{"role": "system", "content": system_prompt}]
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
            user_turn = transcript.record(USER, message.text)
            try:
                transcript.record(PERSONA, text)
            except Exception:  # noqa: BLE001 — roll back the orphan, then re-raise (never swallow)
                if user_turn is not None:
                    transcript.forget(user_turn)
                raise
        return text

    return respond


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clonway_cockpit.chat_memory")
    sub = parser.add_subparsers(dest="command", required=True)
    forget = sub.add_parser("forget")
    forget.add_argument("--memory-base", type=Path, required=True)
    forget.add_argument("--handle", required=True)
    forget.add_argument("--space", required=True)
    args = parser.parse_args(argv)

    if args.command == "forget":
        scope = scope_for_space(args.space)
        try:
            deleted = PersonaMemory(args.memory_base, args.handle).forget_thread(scope)
        except ValueError:
            print("invalid handle", file=sys.stderr)
            return 2
        print("forgotten" if deleted else "nothing to forget")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
