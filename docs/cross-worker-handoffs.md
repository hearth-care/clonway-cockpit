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

## The negotiating responder (`clonway_cockpit.negotiation`)

`negotiating_responder(inner, colleagues, completer, role=..., memory_base=..., reflex_kits=...)`
wraps any plain-chat responder. No envelope → straight to `inner` (ordinary conversation is
untouched). Envelope → this layer fully owns the outcome (a code-composed `response`, or
silence) — never free-form chat. Per inbound notice the persona: fires its registered reflexes
(code, before any model call), consults its private working memory, asks the model for per-ask
accept/decline/defer decisions via `complete_structured`, reconciles them in code
(verbatim-then-positional matching; missing → defer; bad enum → defer; unknown redirect →
dropped), records the task in working memory + the thread transcript (atomic pair + rollback),
and replies. A declined ask may carry a `redirect`; the rendered `@handle` engages the redirect
target, which processes just those asks and answers the ORIGINAL origin. Model down? Reflexes
and the audit still post — defer-all with a canned voice line (a reflex without a posted audit
is forbidden). Forged frames (`origin` ≠ transport author), plans, and responses addressed to
others are inert.

## The ledger, the plan, and the stall (`TaskLedger` / `NegotiatedSpace`)

`NegotiatedSpace` wraps a `GroupSpace`; after every round its `TaskLedger` re-derives task state
purely from the round's messages (same forgery check as the responder). A task resolves when
every ask is terminal: `done` (reflex applied), `accepted`, owner-attention (defer / bare
decline / failed reflex), or redirect-accepted — a redirected ask can only be terminalized by
the redirect target. Newly-resolved tasks with anything for the owner get a deterministic
`plan` envelope posted to the room (it authorizes nothing — execution rides the existing
owner-command + approval surfaces). Unresolved tasks at round end get ONE prose stall notice —
escalate, don't push: a turn-cap-orphaned negotiation lands in the owner's lap by design.
Origin-side, domain code composes a notice, addresses it via `address_notice` (the receptionist
points), and posts through `space.post_notice(handle, env, say)`.

## What v1 deliberately defers

Live ChatRouter wiring + card rendering (worker-edge, after the Chat deploy slice); open
un-addressed offers (needs a deliberate `should_respond` extension); model-assisted reflex
matchers; cross-session ledger persistence; verifiable provenance. See the design spec's
"Deferred" section before reinventing any of these ad hoc.
