"""The safe-direction reflex — a worker's OWN pre-registered, BLOCKING-ONLY rule reacting to an
agent-claimed fact (hold payroll, pause a send, flag a record). Never money-moving, never
releasing, never deleting: the worst case of a poisoned claim is over-caution the owner lifts.

THE ONE SAFETY IDEA: the reflex is an :data:`~clonway_cockpit.approval.ApprovalPolicy`, not a new
write path. Nothing here executes domain actions — the worker's existing gated drive presents a
proposal at its ``confirm_apply`` gate exactly as today, and :class:`ReflexPolicy` is merely the
policy that may say yes (a stricter sibling of ``approval.AllowlistPolicy``). The other agent's
message never commands anything: the trigger is the receiving worker's own rule firing on data it
heard, so the owner-only-command air-gap is untouched.

Idempotency keys on ``(task_id, capability_key)`` — a task id therefore must be FRESH per
real-world event (a reused id deliberately refuses to re-apply; spec Dragon D14). Marking happens
only AFTER a successful run, and an already-applied reflex is REPORTED (``"previously applied"``)
rather than silently skipped, so a redelivery retry still posts a true audit (spec Dragon D5).

See ``docs/cross-worker-handoffs.md`` and the design spec
``docs/superpowers/specs/2026-06-10-cross-worker-handoffs-design.md``.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .audit_log import AuditEvent, AuditSink
from .handoff import HandoffEnvelope
from .private_memory import PersonaMemory
from .shared_memory import is_safe_slug

_KEY_SLUG = re.compile(r"[^a-z0-9_-]")
_MAX_KEY_SLUG = 48
"""Keeps ``reflex-<task_id 64>-<key>`` under the 128-char memory-note slug bound."""


def _slug_key(key: str) -> str:
    """A capability key (``payroll.hold`` — dots are not slug-safe, spec Dragon D6) as a
    memory-note segment: lower-cased, non-slug chars → ``-``, trimmed, bounded, never empty."""
    slug = _KEY_SLUG.sub("-", key.lower()).strip("-_")[:_MAX_KEY_SLUG]
    return slug or "key"


@dataclass(frozen=True)
class ReflexRule:
    """One registered blocking capability. ``matcher`` is PURE + DETERMINISTIC (no model calls —
    a model must never decide to fire a write path) and returns the EXACT ask text it would act
    on, or ``None``. ``run`` is the worker-injected executor: present the proposal at the
    worker's own write gate, drive the blocking action, return True iff it actually applied."""

    capability_key: str
    description: str
    matcher: Callable[[HandoffEnvelope], str | None]
    run: Callable[[Mapping[str, object]], bool]

    def __post_init__(self) -> None:
        if not self.capability_key.strip():
            raise ValueError("capability_key must be non-empty")


class ReflexBank:
    """One persona's registered reflexes, iterated in registration order (first match per ask
    wins). Registration is the deliberate, reviewed act — there is no way to express a
    non-blocking reflex because the proposal builder hardcodes the direction."""

    def __init__(self) -> None:
        self._rules: dict[str, ReflexRule] = {}

    def register(self, rule: ReflexRule) -> None:
        if rule.capability_key in self._rules:
            raise ValueError(f"duplicate reflex capability {rule.capability_key!r}")
        self._rules[rule.capability_key] = rule

    def rules(self) -> tuple[ReflexRule, ...]:
        return tuple(self._rules.values())

    def keys(self) -> frozenset[str]:
        return frozenset(self._rules)


class ReflexLog:
    """Idempotency state for ONE persona: has ``(task_id, capability_key)`` already applied?
    Always tracked in-memory; when constructed with the persona's :class:`PersonaMemory` it is
    ALSO persisted as a working note (``reflex-<task_id>-<key-slug>``), so idempotency survives a
    process restart. ``mark`` is called only after a successful run (spec Dragon D5)."""

    def __init__(self, memory: PersonaMemory | None = None) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._memory = memory

    @staticmethod
    def _note_name(task_id: str, key: str) -> str:
        return f"reflex-{task_id}-{_slug_key(key)}"

    def seen(self, task_id: str, key: str) -> bool:
        if (task_id, key) in self._seen:
            return True
        if self._memory is not None:
            return self._memory.working.get(self._note_name(task_id, key)) is not None
        return False

    def mark(self, task_id: str, key: str) -> None:
        self._seen.add((task_id, key))
        if self._memory is not None:
            self._memory.working.remember(
                name=self._note_name(task_id, key),
                kind="reflex",
                summary=f"{key} applied for #{task_id}",
            )


class ReflexPolicy:
    """The ApprovalPolicy a worker wires at its write gate for reflex-initiated drives. ALL
    checks must hold; each is fail-safe in the ``AllowlistPolicy`` style — exact-identity, never
    truthiness, so a malformed/crafted proposal (``money_movement=[]``, ``blocking="yes"``) is
    refused rather than slipping through. The policy only READS the log; marking and the success
    counter are :func:`fire_reflexes`'s job, only after a successful run (spec Dragon D5)."""

    def __init__(
        self,
        keys: frozenset[str],
        log: ReflexLog,
        *,
        max_applies: int | None = None,
    ) -> None:
        self._keys = frozenset(keys)
        self._log = log
        self._max = max_applies
        self._applied = 0

    def __call__(self, proposal: Mapping[str, object]) -> bool:
        if proposal.get("money_movement", False) is not False:
            return False
        if proposal.get("blocking") is not True:
            return False
        key = proposal.get("capability_key")
        if not (isinstance(key, str) and key in self._keys):
            return False
        provenance = proposal.get("provenance")
        if not (isinstance(provenance, str) and provenance.strip()):
            return False
        task_id = proposal.get("task_id")
        if not (isinstance(task_id, str) and is_safe_slug(task_id)):
            return False
        if self._log.seen(task_id, key):
            return False
        # Final gate: allow when there is no session cap, or we are still under it. Stated as a
        # positive condition (clearest for a safety auditor and avoids the SIM103 if/return-bool).
        return self._max is None or self._applied < self._max

    def note_applied(self) -> None:
        """Bump the success counter — called by :func:`fire_reflexes` after a successful run."""
        self._applied += 1


def build_proposal(env: HandoffEnvelope, rule: ReflexRule, ask: str) -> dict:
    """The gate proposal for one (envelope, rule, ask). Direction is HARDCODED here —
    ``blocking: True, money_movement: False`` — and the policy re-checks both against the actual
    proposal it is handed, so neither a rule nor a worker enrichment can flip it quietly.
    Provenance comes ONLY from a fact claimed by the envelope's origin (spec Dragon D7) — a
    notice quoting some third party's provenance must not fire on the origin's authority."""
    provenance = next(
        (f.provenance for f in env.facts if f.claimant == env.origin and f.provenance), ""
    )
    return {
        "capability_key": rule.capability_key,
        "money_movement": False,
        "blocking": True,
        "task_id": env.task_id,
        "ask": ask,
        "summary": env.summary,
        "provenance": provenance,
        "origin": env.origin,
    }


@dataclass(frozen=True)
class ReflexFiring:
    """One reflex outcome, reported into the response envelope as a ``reflexed`` decision."""

    ask: str
    capability_key: str
    applied: bool
    note: str = ""


@dataclass(frozen=True)
class ReflexKit:
    """One persona's reflex wiring (bank + policy + log), keyed by handle at the responder."""

    bank: ReflexBank
    policy: ReflexPolicy
    log: ReflexLog
    audit: AuditSink | None = None
    audit_worker: str = "cockpit"


def _reflex_ref(task_id: str, capability_key: str) -> str:
    return ReflexLog._note_name(task_id, capability_key)


def _audit_reflex(
    kit: ReflexKit,
    event: str,
    *,
    capability_key: str,
    outcome: str,
    ref: str,
) -> None:
    if kit.audit is None:
        return
    with contextlib.suppress(Exception):
        kit.audit(
            AuditEvent(
                ts=datetime.now(UTC),
                worker=kit.audit_worker,
                run_id=None,
                event=event,
                capability_key=capability_key,
                actor="reflex",
                dry_run=False,
                money_movement=False,
                outcome=outcome,
                equivalent_cli=None,
                focus=None,
                ref=ref,
            )
        )


def fire_reflexes(env: HandoffEnvelope, kit: ReflexKit) -> list[ReflexFiring]:
    """Evaluate every registered rule against ``env`` and execute the approved ones. At most one
    firing per ask (first registered rule wins). The seen-precheck REPORTS an already-applied
    reflex (``"previously applied"``) instead of silently skipping it, so a redelivery retry's
    audit stays true (spec Dragon D5). A policy refusal records nothing — the ask falls through
    to the model-decision path. A worker executor exception is caught and reported honestly
    (``applied=False``), never allowed to crash the chat round (spec Dragon D11)."""
    firings: list[ReflexFiring] = []
    covered: set[str] = set()
    for rule in kit.bank.rules():
        ask = rule.matcher(env)
        if ask is None or ask not in env.asks or ask in covered:
            continue
        if kit.log.seen(env.task_id, rule.capability_key):
            firings.append(
                ReflexFiring(
                    ask=ask,
                    capability_key=rule.capability_key,
                    applied=True,
                    note="previously applied",
                )
            )
            covered.add(ask)
            continue
        proposal = build_proposal(env, rule, ask)
        if not kit.policy(proposal):
            _audit_reflex(
                kit,
                "reflex.refused",
                capability_key=rule.capability_key,
                outcome="refused",
                ref=_reflex_ref(env.task_id, rule.capability_key),
            )
            continue
        _audit_reflex(
            kit,
            "reflex.approved",
            capability_key=rule.capability_key,
            outcome="approved",
            ref=_reflex_ref(env.task_id, rule.capability_key),
        )
        note = ""
        try:
            applied = bool(rule.run(proposal))
            if not applied:
                note = "executor reported not applied"
        except Exception as exc:  # noqa: BLE001 — worker code must never crash the round (D11)
            applied = False
            note = f"reflex execution failed: {type(exc).__name__}"
        if applied:
            kit.log.mark(env.task_id, rule.capability_key)
            kit.policy.note_applied()
        firings.append(
            ReflexFiring(ask=ask, capability_key=rule.capability_key, applied=applied, note=note)
        )
        covered.add(ask)
    return firings
