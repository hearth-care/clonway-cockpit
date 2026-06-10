# Per-thread/space conversation memory — the wiring (design)

**Status:** approved-to-build (owner picked PR #74 "per-persona multi-turn memory" to drive to
completion, 2026-06-10). Autonomous design grounded in the two-tier-memory architecture decision and
the Chat-transport core. The implementation PR is left **open for the owner's review** because it
touches the memory boundary.

**Slice:** the *conversation-layer wiring* of the private memory tier — the half PR #77 deliberately
deferred. #77 built the **per-thread store** (`private_memory.py`: `PersonaMemory.thread(scope)`) and
called out, by name, two later concerns it did **not** do:

> "**'True multi-turn' here is a per-thread fact ledger, not a transcript accumulator.** … a
> transcript store … is a separate, later concern, and is *not* a goal of this slice."

> **Out (later / not this slice):** "the conversation-layer wiring that constructs a persona's
> `thread(scope)` from a real Chat space id (that arrives with the transport slice, PR #73)."

The Chat-transport core (#78) then merged and pointed at the same seam:

> "**per-space multi-turn memory** — the transport is exactly where a future slice attaches
> `PersonaMemory.thread(slug(space_id))` (now that the private-memory tier exists, PR #77), but
> wiring it is its own slice."

This is that slice. It connects the two merged cores so a persona **remembers a conversation within
its own thread/space across turns** — realizing PR #74's headline acceptance criterion end-to-end.

## Why this slice, and why it is purely additive

The reply seam already exists and was *designed* for exactly this. `ChatRouter`
(`chat_transport.py`) and `GroupChatOrchestrator` (`group_chat.py`) both inject a `responder:
Callable[[Persona, ChatMessage], str | None]`. The reference responder `gateway_responder`
(`colleague.py`) is documented as:

> "Stateless by design — system prompt + the one inbound message. It is the minimal honest wire, not
> a conversation manager; **production layers a per-space transcript on top**."

So multi-turn memory is **not** a change to the router, the orchestrator, the air-gap, or the
private-memory store. It is a **new, memory-aware responder** with the *same signature*, that loads
prior turns before the model call and records the new turn after. Swapping `gateway_responder` →
`remembering_responder` is the entire integration. One new module, zero edits to merged code.

```
inbound event ─▶ ChatRouter.handle_event ─(unchanged)─▶ responder(persona, message)
                                                              │
                                          remembering_responder (NEW)
                                              │  scope = scope_for_space(message.space)
                                              │  history = ThreadTranscript(persona, scope).recent()
                                              ▼
                          [system(soul)] + history + [user(message.text)] ─▶ completer.complete
                                              │
                                              ▼  record(user, message.text); record(persona, reply)
                                            reply ─▶ (router posts it via the transport, unchanged)
```

## Components (`clonway_cockpit/chat_memory.py`)

A single new framework module, `rich`-only, stdlib + the two merged cores. Three units:

### 1. `scope_for_space(space_id: str) -> str`

Normalizes a **raw Google Chat space id** (`spaces/AAAAbCdEf`, mixed-case, contains `/`) into a value
that satisfies `is_safe_slug` (`^[a-z0-9][a-z0-9_-]*$`, ≤128). #77 explicitly assigned this
normalization contract to the transport slice — `private_memory.thread(scope)` validates the slug but
does not derive it.

The output is **readable + collision-safe**: `"<prefix>-<hash16>"` where

- `prefix` is the lower-cased space id with every char outside `[a-z0-9_-]` replaced by `-`, leading
  non-alphanumerics stripped, truncated to 32 chars (empty/unsluggable → `"s"`); and
- `hash16` is the first 16 hex chars of `sha256(space_id)` of the **original** id.

The hash makes the scope **case-fold-collision-proof** (two distinct space ids that lower-case to the
same prefix still get different scopes — a memory cross-leak would be a real bug), while the readable
prefix keeps the on-disk path debuggable (`spaces-aaaabcdef-1f3a…`). Deterministic, no clock, no
randomness. Total function: any input (including `""`) yields a valid slug.

### 2. `ThreadTranscript` — a transcript projection over the #77 store

A thin wrapper over one `PersonaMemory(base, handle).thread(scope)` `PrivateScope`. It does **not**
reimplement storage — it reuses the merged `Fact` format and the per-(persona, scope) directory #77
already gives, adding only the transcript shape #77 deferred.

- `record(role, text)` appends one turn as a `Fact`: name `turn-NNNNNN` (zero-padded, monotonic — the
  next index is `max(existing)+1`, parsed from the turn filenames so gaps never reuse an index);
  `kind` is the role (`"user"` | `"persona"`); `summary` is a single-line preview (first non-empty
  line, truncated — satisfies the format's single-line frontmatter rule); `body` is the full text
  (may be multi-line). Empty/blank text is not recorded.
- `recent(limit=DEFAULT_TURNS)` returns the last `limit` turns **in chronological order** as gateway
  `Message`s: `kind="persona"` → `{"role": "assistant", "content": text}`, otherwise
  `{"role": "user", "content": text}`. `content` is `body` (full text) falling back to `summary`.
  Best-effort and never-raise (inherits `PrivateScope`'s posture): a missing scope → `[]`.

Turn ordering relies on `PrivateScope.all()` returning facts sorted by name; `turn-000007` sorts
after `turn-000006`, so zero-padding (6 digits → 1M turns headroom) keeps lexical order = chronological
order.

### 3. `remembering_responder(...)` — the memory-aware reference responder

```python
def remembering_responder(
    colleagues: ColleagueRegistry,
    completer: Completer,
    *,
    role: str,
    memory_base: Path,
    history_turns: int = DEFAULT_TURNS,
    quiet_on_error: bool = True,
) -> Callable[[Persona, ChatMessage], str | None]
```

Same signature and contract as `gateway_responder`, plus per-thread memory. For each call:

1. **Scope.** If `message.space` is empty, degrade to **stateless** (no scope to key on → identical to
   `gateway_responder`: a synthetic/spaceless message gets no bogus shared bucket). Otherwise
   `scope = scope_for_space(message.space)` and `txn = ThreadTranscript(memory_base, persona.handle,
   scope)`.
2. **Compose.** `messages = [system(colleague.system_prompt)] + txn.recent(history_turns) +
   [user(message.text)]`. A persona with no loaded soul returns `None` (stays un-constituted-silent —
   same as `gateway_responder`).
3. **Complete.** `completer.complete(messages, role=role)`; a `GatewayError` under
   `quiet_on_error=True` returns `None` (that persona stays quiet; the round's other replies stand).
4. **Record on success only.** A non-empty reply records the **engaged turn pair** —
   `record("user", message.text)` then `record("persona", reply)` — so each persona's transcript is
   exactly the conversation *it participated in*. An empty reply or a model error records **nothing**
   (no half-turn; mirrors the router's "mark handled only after success" posture). Returns the reply.

This is a sibling of `gateway_responder`, not an edit of it — `colleague.py` (merged #62) is
untouched. It re-derives the small soul-compose + quiet-on-error logic (≈10 lines) rather than
refactoring the merged "stateless minimal wire", keeping blast radius to the new module.

## How a worker wires it (the only consumer change)

```python
# before (stateless):
router = ChatRouter(registry=..., responder=gateway_responder(cols, gw, role="chat"), ...)
# after (per-thread memory):
router = ChatRouter(
    registry=...,
    responder=remembering_responder(cols, gw, role="chat", memory_base=PRIVATE_MEMORY_ROOT),
    ...,
)
```

Both DM and named-space paths flow through `responder(persona, message)` with `message.space`
populated (`to_chat_message` sets it from `event.space_id`; re-queued persona replies carry it too),
so **both surfaces inherit per-conversation memory** with no path-specific code.

## Invariants preserved (the tests that matter)

- **Per-persona isolation.** Memory is keyed by `persona.handle` via `PersonaMemory`, so persona A's
  transcript is structurally invisible to persona B (inherits #77's hard boundary). Test: two personas
  in one space → each has only its own turns.
- **The owner-only-command air-gap is untouched.** Memory is *downstream* of routing — `is_command` /
  `is_owner` decide whether a message is acted on *before* the responder runs. Recording a turn is not
  an action and cannot become one. A non-owner DM still draws no reply (so nothing is recorded for it).
- **The shared-write boundary holds.** `ThreadTranscript.record` only ever calls
  `PrivateScope.remember` (the private tier). Regression test: after a full conversation, a
  `SharedMemory` pointed at the shared dir sees **nothing**; promotion to shared truth still requires
  `GovernedWriter(source=OWNER)`. (Answers PR #74's "tests for quoted content not becoming shared
  memory": private session turns never cross into shared memory.)
- **Never-crash.** A missing/corrupt scope yields `[]` history (the persona just answers
  context-free); no read raises.

## End-to-end acceptance (maps to PR #74)

- **"A persona can remember context within its own thread/space"** → an end-to-end test drives a real
  `ChatRouter` with `remembering_responder` and a recording fake completer: turn 1 (owner asks),
  turn 2 (owner follows up) — the completer **receives turn 1's exchange in its message list on turn
  2**, proving the persona remembers. A second space for the same persona starts empty (thread
  scoping).
- **"Private memory does not leak across personas"** → the isolation test above.
- **"Shared memory writes require owner confirmation"** → the shared-boundary regression above.

## Scope

**In:** `chat_memory.py` (the three units above); `tests/test_chat_memory.py` (round-trips,
ordering, scope normalization + collision-safety, isolation, shared-boundary, empty-space stateless,
quiet-on-error-records-nothing, and the end-to-end router drive); `docs/thread-memory.md`; a wiring
note in `docs/chat-transport.md`; a Delivery-table update in
`docs/persona-platform-architecture.md`.

**Out (later / not this slice):** a memory *reflector/summariser* (compacting an old transcript into
notes); semantic/embedding recall (keyword `recall` already exists on the store); recording turns a
persona stayed *quiet* on (v1 remembers only conversations it engaged in); cross-space memory; a
memory eviction/retention policy beyond `recent(limit)` at read time (the store keeps every turn on
disk — a retention sweep is its own slice); persisting the transcript through the live Chat REST
deploy (operator-gated, unchanged by this slice).

## Dependency packaging

**Zero new runtime dependency** — stdlib (`hashlib`, `pathlib`) + the merged `private_memory`,
`shared_memory`, `group_chat`, `colleague` modules. The framework stays `rich`-only.
