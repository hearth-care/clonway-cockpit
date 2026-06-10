# Per-thread/space conversation memory

The wiring that makes a persona **remember a conversation within its own thread/space across turns** —
the production layer over the stateless `gateway_responder`. It connects the two merged cores: the
private per-thread store (`private_memory.py`, PR #77) and the Chat transport (`chat_transport.py`,
PR #78). Platform context: [`persona-platform-architecture.md`](persona-platform-architecture.md) →
"Two-tier memory" and "The Chat transport". Design: the spec under
[`superpowers/specs/2026-06-10-thread-memory-wiring-design.md`](superpowers/specs/2026-06-10-thread-memory-wiring-design.md).

## Why it is a thin, additive slice

The reply seam was built for this. `ChatRouter` and `GroupChatOrchestrator` inject a
`responder: (Persona, ChatMessage) -> str | None`, and `gateway_responder` is documented as
*"stateless by design … production layers a per-space transcript on top."* This module is that layer.
It adds nothing to the router, the orchestrator, the owner-only-command air-gap, or the private store
— a worker just chooses a different responder.

```python
import os
from pathlib import Path
from clonway_cockpit.chat_memory import remembering_responder
from clonway_cockpit.chat_transport import ChatRouter

# A durable, cockpit-owned, gitignored directory — NOT a repo path, and NOT Cloud Run's
# ephemeral /tmp (wiped on every cold start → silent amnesia). Mount a persistent volume / GCS
# FUSE / a host path and point this at it. See docs/private-memory.md → "directory discipline".
memory_base = Path(os.environ["COCKPIT_PRIVATE_ROOT"])

router = ChatRouter(
    registry=colleagues.registry,
    responder=remembering_responder(colleagues, gateway, role="chat", memory_base=memory_base),
    transport=chat_rest_poster,
    allowlist=load_allowlist(),
    # REQUIRED with memory: Chat is at-least-once (it retries on 5xx / cold start). Without these
    # dedup hooks a redelivered message records the turn pair TWICE and corrupts later prompts.
    # Back them with a DURABLE store (a file / GCS object), as xhr-server does — an in-memory set
    # is lost on restart, which is exactly when Chat redelivers.
    already_handled=seen.contains,   # def contains(message_id) -> bool
    mark_handled=seen.add,           # def add(message_id) -> None
)
```

Swap `gateway_responder(…)` → `remembering_responder(…)` and DMs **and** named spaces both gain
per-conversation memory, because both flow through `responder(persona, message)` with `message.space`
populated. Keep `gateway_responder` where one-shot replies are wanted. **Wiring the router's
`already_handled`/`mark_handled` dedup is not optional once memory is on** — see "Scope & limits".

## The three units (`clonway_cockpit/chat_memory.py`)

### `scope_for_space(space_id) -> str`

Normalizes a raw Google Chat space id (`spaces/AAAAbCdEf`, mixed-case, has `/`) into a value that
satisfies `is_safe_slug` — the normalization PR #77 assigned to the transport slice. The result is
`"<prefix>-<hash16>"`: a readable, slugified head of the space id (the on-disk path stays debuggable)
joined to the first 16 hex of `sha256` of the **original** id. The hash makes the scope
**case-fold-collision-proof** — two distinct space ids that lower-case to the same prefix still get
different scopes, so one space's memory can never leak into another. Deterministic and total (any
input, including `""`, yields a valid slug).

### `ThreadTranscript(base, handle, scope)`

A turn-by-turn transcript **projected onto** the #77 store — it reuses that store, it does not change
it. Turns are ordinary `Fact` files (`turn-NNNNNN`) under the persona's `thread(scope)` directory.

- `record(role, text)` — append one turn (`role` is `USER` or `PERSONA`). Zero-padded, monotonic
  index so the store's name-sorted reads come back in chronological order. **Blank text records
  nothing.**
- `recent(limit=12)` — the last `limit` turns in chronological order as gateway `Message`s
  (`PERSONA` → `assistant`, otherwise `user`). A missing/empty thread yields `[]` (never raises).

### `remembering_responder(colleagues, completer, *, role, memory_base, history_turns=12, quiet_on_error=True)`

Same `(Persona, ChatMessage) -> str | None` contract as `gateway_responder`, plus memory. Per call it:

1. derives the scope from `message.space` (an **empty** space → stateless, identical to
   `gateway_responder` — no bogus shared bucket);
2. builds `[system(soul)] + recent(history_turns) + [user(message.text)]` and completes it;
3. **on a non-empty reply only**, records the engaged turn pair (`user`: the inbound message, then
   `persona`: the reply). An empty reply or a `GatewayError` (under `quiet_on_error`) returns `None`
   and records nothing.

So each persona's transcript is exactly the conversation *it engaged in* — and a persona that stayed
quiet in a group round stores nothing for that turn (a v1 boundary; see below).

## Invariants it preserves

- **Per-persona isolation.** Memory is keyed by `persona.handle` via `PersonaMemory`, so persona A's
  transcript is structurally invisible to persona B (the #77 hard boundary, inherited).
- **The owner-only-command air-gap is untouched.** Memory is *downstream* of routing — whether a
  message is acted on (`is_command` / `is_owner`) is decided before the responder runs. Recording a
  turn is not an action and cannot become one; a non-owner DM draws no reply, so nothing is recorded.
- **The shared-write boundary holds.** Turns reach only the **private** tier. A session turn never
  becomes shared truth — promotion still requires `GovernedWriter(source=OWNER)`. (A regression test
  asserts a full conversation leaves a `SharedMemory` reader empty.)

## Data at rest

Conversation turns are persisted as **plaintext markdown** under `<memory_base>/<handle>/threads/<scope>/`
— a new disclosure surface the stateless `gateway_responder` did not have (it kept nothing). Turns may
contain PII. Keep `memory_base` **cockpit-owned and gitignored**, never a repo path; encryption-at-rest
and a retention sweep are the consumer's directory discipline / a later slice (same posture as the
shared handbook — see [`private-memory.md`](private-memory.md)).

## Deploy prerequisites (must be true before the live transport carries this)

The live Chat transport is operator-gated and not yet deployed, so these cannot bite until it ships —
but they are **required** when it does:

- **Redelivery dedup is mandatory.** Chat is at-least-once. Wire the router's
  `already_handled`/`mark_handled` with a **durable** store (see the snippet above). Without it a
  redelivered message records the turn pair twice and the duplicate evicts real history from the
  `recent(limit)` window. (Memory raises the stakes of a gap the stateless responder merely showed as
  a duplicate *reply*.)
- **Single writer per (persona, space).** `record` reads the current max turn index and writes the
  next; v1 assumes one writer at a time per thread (the reference `xhr-server` fast-acks then posts
  from a single background task). Genuinely concurrent writers on the *same* thread (≥2 Cloud Run
  instances handling one space at once) can collide on an index. Coordinated/atomic appends land with
  the live-deploy slice.
- **Append cost is O(turns-in-thread) per message** (a turn is recorded by scanning the thread's
  existing turns). It is dwarfed by the per-turn model completion at realistic conversation lengths;
  unbounded growth is the retention/compaction slice's job.

## Scope & limits (v1)

- **Engaged-only memory.** A persona remembers only conversations it **replied in** (a turn it stayed
  quiet on is not stored). So in a group space a persona does *not* recall an exchange between the
  owner and another colleague: if you then say *"Milo, invoice for what we just discussed"*, Milo is
  amnesiac about it — repeat the context in a DM, or promote the fact to shared memory.
- **Per-`(persona, space)` silos — separate from each other and from email.** The *same* Milo has a
  DM transcript and a group-space transcript, each isolated; there is no cross-space recall. *"Like we
  discussed in our DM"* said from the group room gets a blank stare. To carry a fact across surfaces,
  promote it to **shared** memory via `GovernedWriter` (owner-gated).
- **`history_turns` (default 12 ≈ 6 exchanges)** bounds the replayed window. Raise it (e.g. 20–30) for
  a long single task — mind the token cost — or, better, promote recurring facts to
  `PersonaMemory.working` so they persist regardless of window. Every turn is still kept on disk; only
  the *replayed* window is bounded.
- No memory *reflector/summariser* (compacting an old transcript into durable notes) and no
  semantic/embedding recall — the store's keyword `recall` already exists for the latter.
