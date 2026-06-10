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
from pathlib import Path
from clonway_cockpit.chat_memory import remembering_responder
from clonway_cockpit.chat_transport import ChatRouter

router = ChatRouter(
    registry=colleagues.registry,
    responder=remembering_responder(colleagues, gateway, role="chat", memory_base=Path("…/private")),
    transport=chat_rest_poster,
    allowlist=load_allowlist(),
)
```

Swap `gateway_responder(…)` → `remembering_responder(…)` and DMs **and** named spaces both gain
per-conversation memory, because both flow through `responder(persona, message)` with `message.space`
populated. Keep `gateway_responder` where one-shot replies are wanted.

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

## Scope & limits (v1)

- Remembers only conversations a persona **engaged in** (a turn it stayed quiet on is not stored).
- `recent(limit)` bounds the prompt window at read time; every turn is still kept on disk — a
  retention/eviction sweep is a later slice.
- No memory *reflector/summariser* (compacting an old transcript into durable notes) and no
  semantic/embedding recall — the store's keyword `recall` already exists for the latter.
- Memory is per `(persona, space)`; there is no cross-space recall.
