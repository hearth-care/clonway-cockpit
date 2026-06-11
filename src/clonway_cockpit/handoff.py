"""Cross-worker handoff envelopes — the typed contract personas negotiate with.

A negotiation message is ordinary chat text plus EXACTLY ONE fenced ```handoff block carrying a
schema-versioned JSON frame. The chat thread is the carrier; this envelope is the contract. Three
kinds, each with ONE producer, all composed by CODE (a model never authors an envelope — it only
contributes a voice line and per-ask decisions that code reconciles):

- ``notice``  — a worker's domain code reports claimed facts + asks at a named recipient.
- ``response`` — the negotiation layer's per-ask decisions (reflexed / accept / decline / defer).
- ``plan``   — the deterministic owner-facing consolidation. It AUTHORIZES NOTHING.

Trust: the authoritative sender is the transport-level ``ChatMessage.author`` — the ``origin``
field is data and every consumer must check ``origin == author`` before honouring a frame (spec
Dragon D1). Parsing is total and fail-closed: anything malformed, oversized, duplicated, or from a
future ``schema_version`` reads as ordinary prose (``None``), never an exception.

Task ids are minted by domain code and must be FRESH per real-world event — reflex idempotency
and the ledger both key on them, so a reused id is deliberately inert (spec Dragon D14).

See ``docs/cross-worker-handoffs.md`` and the design spec
``docs/superpowers/specs/2026-06-10-cross-worker-handoffs-design.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .shared_memory import is_safe_slug

HANDOFF_SCHEMA_VERSION = 1
"""Bumped on any breaking wire change — the shape-pin test in tests/test_handoff.py forces this."""

FENCE = "handoff"
"""The fenced-block language tag a wire frame travels under."""

KINDS = ("notice", "response", "plan")
DECISIONS = ("reflexed", "accept", "decline", "defer")
STEP_STATUSES = ("done", "needs-approval", "unassigned")

MAX_TASK_ID = 64
"""Leaves room for the ``task-``/``reflex-…`` memory-note prefixes under the 128-char slug bound."""
MAX_LINE = 500
MAX_SUMMARY = 200
MAX_ITEMS = 16
MAX_STEPS = 24
_MAX_BLOCK_BYTES = 32 * 1024
"""Parse refuses a fenced block bigger than this before json.loads (length-bomb guard)."""

_FENCE_RE = re.compile(r"```" + FENCE + r"[ \t]*\n(.*?)\n```", re.DOTALL)


class HandoffError(ValueError):
    """An envelope was COMPOSED with invalid fields — a programmer error at a call site.

    Never raised by :func:`parse_envelope`, which converts every failure to ``None`` (wire input
    is untrusted; composition input is our own code)."""


def _check_line(value: object, what: str, max_len: int, *, required: bool) -> str:
    """Validate a single-line, pre-stripped string field. Frozen dataclasses cannot normalise in
    ``__post_init__``, so the contract is validate-don't-rewrite: the caller supplies clean text."""
    if not isinstance(value, str):
        raise HandoffError(f"{what} must be a string")
    if value != value.strip():
        raise HandoffError(f"{what} must be pre-stripped (no leading/trailing whitespace)")
    if "\n" in value or "\r" in value:
        raise HandoffError(f"{what} must be a single line")
    if required and not value:
        raise HandoffError(f"{what} must be non-empty")
    if len(value) > max_len:
        raise HandoffError(f"{what} too long ({len(value)} > {max_len})")
    return value


def _check_handle(value: object, what: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise HandoffError(f"{what} must be a string")
    if value == "" and allow_empty:
        return value
    if not is_safe_slug(value):
        raise HandoffError(f"{what} {value!r} must be a lower-case slug [a-z0-9][a-z0-9_-]*")
    return value


@dataclass(frozen=True)
class ClaimedFact:
    """One fact asserted inside a notice. ``provenance`` is an AUDIT POINTER (e.g.
    ``xhr:rtw-checks/RTW-2026-0142``), not verifiable proof — what bounds a false claim is the
    blocking-only reflex direction, not this string."""

    text: str
    claimant: str  # persona handle asserting the fact
    provenance: str = ""

    def __post_init__(self) -> None:
        _check_line(self.text, "fact text", MAX_LINE, required=True)
        _check_handle(self.claimant, "fact claimant")
        _check_line(self.provenance, "fact provenance", MAX_SUMMARY, required=False)


@dataclass(frozen=True)
class AskDecision:
    """One per-ask decision inside a response. ``ask`` is the ORIGINAL ask text VERBATIM — the
    ledger joins responses to notices by exact string match (spec Dragon D9)."""

    ask: str
    decision: str  # one of DECISIONS
    redirect: str = ""  # only with decision="decline": suggested owner handle
    note: str = ""
    capability: str = ""  # only with decision="reflexed": the capability key that fired
    applied: bool = False  # only with decision="reflexed": whether the gated action applied

    def __post_init__(self) -> None:
        _check_line(self.ask, "decision ask", MAX_LINE, required=True)
        if self.decision not in DECISIONS:
            raise HandoffError(f"unknown decision {self.decision!r} (expected one of {DECISIONS})")
        _check_handle(self.redirect, "decision redirect", allow_empty=True)
        if self.redirect and self.decision != "decline":
            raise HandoffError("redirect travels only with decision='decline'")
        _check_line(self.note, "decision note", MAX_LINE, required=False)
        if not isinstance(self.applied, bool):
            raise HandoffError("applied must be a bool")
        if self.decision == "reflexed":
            _check_line(self.capability, "decision capability", MAX_SUMMARY, required=True)
        else:
            if self.capability != "":
                raise HandoffError("capability travels only with decision='reflexed'")
            if self.applied is not False:
                raise HandoffError("applied travels only with decision='reflexed'")


@dataclass(frozen=True)
class PlanStep:
    """One owner-facing step. ``owner=""`` means unassigned (owner attention needed)."""

    owner: str
    action: str
    status: str  # one of STEP_STATUSES

    def __post_init__(self) -> None:
        _check_handle(self.owner, "step owner", allow_empty=True)
        _check_line(self.action, "step action", MAX_LINE, required=True)
        if self.status not in STEP_STATUSES:
            raise HandoffError(f"unknown step status {self.status!r}")


@dataclass(frozen=True)
class HandoffEnvelope:
    """One wire frame. Per-kind shape rules are enforced here so an invalid frame can neither be
    composed (HandoffError) nor parsed (parse_envelope -> None) — the table lives in the spec."""

    kind: str
    task_id: str
    origin: str
    summary: str
    recipient: str = ""
    facts: tuple[ClaimedFact, ...] = ()
    asks: tuple[str, ...] = ()
    decisions: tuple[AskDecision, ...] = ()
    steps: tuple[PlanStep, ...] = ()
    schema_version: int = HANDOFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise HandoffError(f"unknown kind {self.kind!r} (expected one of {KINDS})")
        _check_handle(self.task_id, "task_id")
        if len(self.task_id) > MAX_TASK_ID:
            raise HandoffError(f"task_id too long ({len(self.task_id)} > {MAX_TASK_ID})")
        _check_handle(self.origin, "origin")
        _check_line(self.summary, "summary", MAX_SUMMARY, required=True)
        if self.schema_version != HANDOFF_SCHEMA_VERSION:
            raise HandoffError(
                f"cannot compose schema_version {self.schema_version!r} "
                f"(this code speaks {HANDOFF_SCHEMA_VERSION})"
            )
        for ask in self.asks:
            _check_line(ask, "ask", MAX_LINE, required=True)
        if len(self.facts) > MAX_ITEMS or len(self.asks) > MAX_ITEMS:
            raise HandoffError(f"too many facts/asks (max {MAX_ITEMS})")
        if len(self.decisions) > MAX_ITEMS:
            raise HandoffError(f"too many decisions (max {MAX_ITEMS})")
        if len(self.steps) > MAX_STEPS:
            raise HandoffError(f"too many steps (max {MAX_STEPS})")
        if self.kind == "notice":
            _check_handle(self.recipient, "notice recipient")
            if self.decisions or self.steps:
                raise HandoffError("a notice carries no decisions/steps")
        elif self.kind == "response":
            _check_handle(self.recipient, "response recipient")
            if self.facts or self.asks or self.steps:
                raise HandoffError("a response carries no facts/asks/steps")
            if not self.decisions:
                raise HandoffError("a response needs at least one decision")
        else:  # plan
            if self.recipient != "":
                raise HandoffError("a plan is owner-facing — recipient must be ''")
            if self.facts or self.asks or self.decisions:
                raise HandoffError("a plan carries no facts/asks/decisions")
            if not self.steps:
                raise HandoffError("a plan needs at least one step")


def to_payload(env: HandoffEnvelope) -> dict:
    """The JSON-ready dict for one envelope — the inverse of :func:`from_payload`."""
    return {
        "kind": env.kind,
        "task_id": env.task_id,
        "origin": env.origin,
        "recipient": env.recipient,
        "summary": env.summary,
        "schema_version": env.schema_version,
        "facts": [
            {"text": f.text, "claimant": f.claimant, "provenance": f.provenance} for f in env.facts
        ],
        "asks": list(env.asks),
        "decisions": [
            {
                "ask": d.ask,
                "decision": d.decision,
                "redirect": d.redirect,
                "note": d.note,
                "capability": d.capability,
                "applied": d.applied,
            }
            for d in env.decisions
        ],
        "steps": [{"owner": s.owner, "action": s.action, "status": s.status} for s in env.steps],
    }


def _str_field(data: dict, key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise HandoffError(f"{key} must be a string")
    return value


def _items(data: dict, key: str) -> list[dict]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise HandoffError(f"{key} must be a list of objects")
    return value


def from_payload(data: object) -> HandoffEnvelope:
    """Decode one payload. Raises :class:`HandoffError` on anything invalid. Unknown keys are
    ignored (additive forward-compat); ``schema_version`` must be EXACTLY the int 1 — a future
    version must read as invalid, not best-effort (spec Dragon D3). ``type(...) is int`` also
    rejects ``True`` (bool is an int subclass that would otherwise pass ``== 1``)."""
    if not isinstance(data, dict):
        raise HandoffError("payload must be a JSON object")
    version = data.get("schema_version")
    if type(version) is not int or version != HANDOFF_SCHEMA_VERSION:
        raise HandoffError(f"unsupported schema_version {version!r}")
    asks = data.get("asks", [])
    if not isinstance(asks, list) or any(not isinstance(a, str) for a in asks):
        raise HandoffError("asks must be a list of strings")
    applied_ok = all(isinstance(d.get("applied", False), bool) for d in _items(data, "decisions"))
    if not applied_ok:
        raise HandoffError("decision applied must be a bool")
    return HandoffEnvelope(
        kind=_str_field(data, "kind"),
        task_id=_str_field(data, "task_id"),
        origin=_str_field(data, "origin"),
        recipient=_str_field(data, "recipient"),
        summary=_str_field(data, "summary"),
        schema_version=version,
        facts=tuple(
            ClaimedFact(
                text=_str_field(f, "text"),
                claimant=_str_field(f, "claimant"),
                provenance=_str_field(f, "provenance"),
            )
            for f in _items(data, "facts")
        ),
        asks=tuple(asks),
        decisions=tuple(
            AskDecision(
                ask=_str_field(d, "ask"),
                decision=_str_field(d, "decision"),
                redirect=_str_field(d, "redirect"),
                note=_str_field(d, "note"),
                capability=_str_field(d, "capability"),
                applied=bool(d.get("applied", False)),
            )
            for d in _items(data, "decisions")
        ),
        steps=tuple(
            PlanStep(
                owner=_str_field(s, "owner"),
                action=_str_field(s, "action"),
                status=_str_field(s, "status"),
            )
            for s in _items(data, "steps")
        ),
    )


def _human(env: HandoffEnvelope) -> str:
    """The deterministic human-readable section. LOAD-BEARING: must contain the literal
    ``@{recipient}`` and every ``@{redirect}`` — that is what makes ``extract_mentions`` fire and
    the existing ``should_respond`` engage the right personas with zero group_chat changes
    (spec Dragon D4). Don't 'tidy' the @ signs away."""
    if env.kind == "notice":
        lines = [
            f"handoff notice #{env.task_id} from @{env.origin} → @{env.recipient}: {env.summary}"
        ]
        for f in env.facts:
            prov = f.provenance or "none"
            lines.append(f"fact: {f.text} (claimant @{f.claimant}; provenance: {prov})")
        lines.extend(f"ask: {a}" for a in env.asks)
        return "\n".join(lines)
    if env.kind == "response":
        lines = [f"response #{env.task_id} from @{env.origin} → @{env.recipient}: {env.summary}"]
        for d in env.decisions:
            suffix = f" ({d.note})" if d.note else ""
            if d.decision == "reflexed" and d.applied:
                lines.append(f"[done] {d.ask} — reflexed via {d.capability}{suffix}")
            elif d.decision == "reflexed":
                lines.append(f"[failed] {d.ask} — reflex did not apply{suffix}")
            elif d.decision == "accept":
                lines.append(f"[mine] {d.ask}{suffix}")
            elif d.decision == "decline" and d.redirect:
                lines.append(f"[not mine] {d.ask} → @{d.redirect}{suffix}")
            elif d.decision == "decline":
                lines.append(f"[not mine] {d.ask}{suffix}")
            else:
                lines.append(f"[needs owner] {d.ask}{suffix}")
        return "\n".join(lines)
    lines = [f"unified plan #{env.task_id} — for the owner: {env.summary}"]
    for i, s in enumerate(env.steps, 1):
        owner = f"@{s.owner}" if s.owner else "unassigned"
        lines.append(f"{i}. [{s.status}] {owner}: {s.action}")
    lines.append("every step executes through the approval gate — this plan authorizes nothing")
    return "\n".join(lines)


def render_envelope(env: HandoffEnvelope, say: str = "") -> str:
    """One chat message: sanitized voice line, human-readable section, then the fenced frame.

    ``say`` is model-authored and untrusted: every ``\\u0060\\u0060\\u0060`` run is defanged so a
    voice line can never smuggle a second parseable block (spec Dragon D8 / invariant S8). The
    fenced JSON uses ``sort_keys=True`` so the wire is byte-deterministic (the shape-pin test)."""
    parts: list[str] = []
    voice = say.replace("```", "'''").strip()
    if voice:
        parts.append(voice)
    parts.append(_human(env))
    payload = json.dumps(to_payload(env), sort_keys=True, ensure_ascii=False)
    parts.append(f"```{FENCE}\n{payload}\n```")
    return "\n\n".join(parts)


def parse_envelope(text: str) -> HandoffEnvelope | None:
    """Total, fail-closed wire parse: EXACTLY ONE fenced block (zero → prose; two+ → an echoed or
    quoted frame, treated as prose — spec Dragon D2), bounded size, valid JSON, valid payload.
    Any failure → ``None``, never an exception (a malformed frame must read as ordinary chat)."""
    if not isinstance(text, str):
        return None
    blocks = _FENCE_RE.findall(text)
    if len(blocks) != 1:
        return None
    block = blocks[0]
    if len(block.encode("utf-8")) > _MAX_BLOCK_BYTES:
        return None
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return None
    try:
        return from_payload(data)
    except (HandoffError, ValueError, TypeError):
        return None
