# Cross-worker task negotiation & handoffs

Personas negotiate cross-domain tasks in the group room instead of the owner routing everything.
The protocol rides the existing chat as data: one message = voice text + exactly one fenced
`handoff` JSON frame. Design spec (read it for the invariants S1–S12 and dragons D1–D20):
`docs/superpowers/specs/2026-06-10-cross-worker-handoffs-design.md`.

## The envelope (`clonway_cockpit.handoff`)

Three kinds, one producer each, all composed by code (a model never authors a frame):

| kind | producer | carries |
|---|---|---|
| `notice` | a worker's domain code | claimed facts (with provenance pointers) + asks, at a named `recipient` |
| `response` | the negotiation layer | per-ask decisions: `reflexed` / `accept` / `decline`(+redirect) / `defer` |
| `plan` | deterministic consolidation | owner-facing steps; **authorizes nothing** |

Load-bearing details:

- **The authoritative sender is `ChatMessage.author`** — every consumer checks
  `envelope.origin == message.author`; a mismatched frame is inert (forged/echoed).
- **`parse_envelope` is total and fail-closed**: zero or two+ fenced blocks, bad JSON, unknown
  `schema_version`, oversize → `None` (ordinary prose). Composition errors raise `HandoffError`.
- **The render carries the mentions**: `@recipient` / `@redirect` in the human text are what make
  the merged `should_respond` engage the right personas — no `group_chat.py` change.
- **Task ids must be fresh per real-world event** — reflex idempotency and the ledger key on them;
  a reused id is deliberately inert.
- The wire is pinned: `schema_version` + a byte-exact shape-pin test force a version bump on any
  breaking change.

(Negotiation, ledger sections land with their PRs.)

## The safe-direction reflex (`clonway_cockpit.reflex`)

A worker's own pre-registered, blocking-only rule reacting to an agent-claimed fact. **The reflex
is an `ApprovalPolicy`, not a new write path** — the worker's gated drive presents a proposal at
its existing `confirm_apply` gate; `ReflexPolicy` is the policy that may say yes. Checks (all
fail-safe, exact-identity): registered capability, `money_movement is False`, `blocking is True`,
non-empty provenance from a fact claimed by the origin, slug task id, not previously applied,
under the session cap. Idempotency keys on `(task_id, capability_key)`, survives restart via a
working-memory note, and an already-applied reflex is *reported* ("previously applied") rather
than skipped — so a redelivered message still posts a true audit. The executor (`ReflexRule.run`)
is worker code; its exceptions are caught and reported as `applied=False`, never crash the round.
Matchers are pure and deterministic — a model never decides to fire a write path.
