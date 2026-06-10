# Persona Google Chat add-on transport — framework core (design)

**Status:** approved-to-build (owner: "go after the highest-value recommended one" → PR #73, the
Chat transport, 2026-06-10). Autonomous design grounded in the persona-platform architecture and
the **proven** Auto-HR `xhr-server` add-on (mirrored, not reinvented). The implementation PR is left
**open for the owner's review**; the live deploy + "watch a real DM" step is operator-gated.
**Slice:** realizes the "live Google Chat transport (a Workspace add-on)" line in
[`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md) → *Still ahead*.
The **in-memory wire is already proven** (`group_chat.py`: `GroupSpace`, distributed self-selection,
the owner-only-command air-gap); this slice builds the **production transport surface** that feeds it.
**Goal:** a framework-owned, dependency-free **transport core** that turns an inbound Google Chat
**Workspace add-on** event into the framework's `ChatMessage`, enforces the operator trust boundary,
and routes it — a **DM** to the addressed persona, a **named space** through distributed
self-selection — returning the persona replies for delivery. The HTTP endpoint, the Chat REST
outbound client, and the Cloud Run deploy are the **worker's** side (documented runbook), so the
framework stays `rich`-only.

## Why a Workspace add-on, and what the framework owns

The fleet's Chat bots are **Workspace add-ons, not classic HTTP Chat apps** — getting this wrong has
burned whole sessions (see the architecture's "Chat transport" section). The load-bearing facts,
mirrored from the working `xhr-server` reference (`src/xhr/chat/`):

- **Auth is Cloud Run IAM + an operator-email allowlist — NOT a JWT/audience check.** The add-on
  invokes the endpoint as its service agent (`service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam`);
  grant it `roles/run.invoker`. **Pinning an audience *rejects* the real add-on traffic.** Trust at
  the app layer is the allowlist on `event.user.email`.
- **The wire envelope is nested** — top-level `chat: {messagePayload | addedToSpacePayload |
  removedFromSpacePayload | buttonClickedPayload: {message, space, user}}` + `commonEventObject`,
  with **no** top-level `type`. Normalise it before anything else looks at it.
- **An add-on only dispatches the triggers its deployment declares** — if it isn't configured to
  *receive messages*, DMs never reach Cloud Run (the #1 "deployed but dead" cause).

The framework owns the **transport-agnostic core** (normalise → auth → route → replies); the worker
owns the **edge** (the web route, the outbound Chat REST post, the deploy). This mirrors how the
agent channel is split (`serve_agent_stdio` worker-side, the protocol framework-side): the parsing +
trust + routing live here so every worker inherits them; the I/O lives in the worker.

## Scope

**In** (`clonway_cockpit/chat_transport.py`, stdlib + `group_chat`/`persona` only):
- `normalize_event(event: dict) -> NormalizedChatEvent` — the add-on envelope normaliser (detects
  the nested format, classifies the event kind, lifts `message`/`space`/`user`), mirroring xhr.
- `is_operator(email, allowlist)` + `load_allowlist(env=…)` — the fail-closed operator allowlist
  (no JWT/audience), the app-layer trust boundary.
- `to_chat_message(norm, allowlist) -> ChatMessage` — bridges a normalised event to the existing
  `group_chat.ChatMessage`, setting `is_owner` **only** for an allowlisted operator email (the
  air-gap edge: only the owner's word is ever a command).
- `ChatRouter` — `handle_event(event_dict) -> ChatOutcome`: a **DM** routes to the persona(s) this
  deployment serves; a **named space** routes through `GroupChatOrchestrator.run_round` (distributed
  self-selection). Replies are delivered via the injected `ChatTransport` and returned for
  observability. Idempotency + fast-ack are injectable hooks (below).
- Reply-shape helpers `ack_response()` / `text_response(text)` for the worker's HTTP response.
- An operator IAM/deploy runbook + a usage doc + this spec.

**Out (worker-side or a later slice):** the HTTP route (`/chat-events`) and web framework; the
outbound Chat REST client (`spaces.messages.create`, service-account auth) and the live Cloud Run
deploy; cards/buttons (v1 is **text**); a real model responder (inject
`colleague.gateway_responder`); **per-space multi-turn memory** — the transport is exactly where a
future slice attaches `PersonaMemory.thread(slug(space_id))` (now that the private-memory tier
exists, PR #77), but wiring it is its own slice; observability/run-session plumbing.

## Envelope normalization (mirrors `xhr-server` `events.py`)

```python
ADDON_PAYLOAD_KINDS = {           # which chat.<key>Payload is present → the event kind
    "messagePayload": "MESSAGE",
    "addedToSpacePayload": "ADDED_TO_SPACE",
    "removedFromSpacePayload": "REMOVED_FROM_SPACE",
    "buttonClickedPayload": "CARD_CLICKED",
}

@dataclass(frozen=True)
class NormalizedChatEvent:
    kind: str                     # one of the values above, or "UNKNOWN"
    text: str                     # message.text (full, incl. any @mention); "" when not a message
    space_id: str                 # space.name, e.g. "spaces/AAAA"
    space_type: str               # "DM" | "ROOM" | "" (unknown)
    sender_email: str             # user.email (or message.sender.email); "" when absent
    sender_name: str              # user.displayName; ""
    message_id: str               # message.name (e.g. "spaces/AAAA/messages/BBBB") — the dedup key
    raw: dict                     # the original event, untouched (for the worker / audit)
```

Detection rule (exactly xhr's): the add-on format is "**no** truthy top-level `type` **and** a
`chat` dict". Pick the first present `*Payload`, map to `kind`, and lift `{message, space, user}`
from it. A classic flat event (top-level `type` present) is read directly. An unrecognised shape →
`kind="UNKNOWN"` (the router ignores it with an ack — never raises). Text comes from `message.text`;
space id/type from `space.name`/`space.type`; email from `user.email` falling back to
`message.sender.email`.

## Operator trust boundary (mirrors `operator_auth.py`)

```python
def load_allowlist(env: str = "CLONWAY_CHAT_OPERATORS") -> frozenset[str]: ...  # comma-sep emails
def is_operator(email: str, allowlist: frozenset[str]) -> bool: ...             # fail-closed
```

`is_operator` lower/strip-normalises and returns `False` for an empty email **or** an empty
allowlist (fail-closed — an unconfigured deployment trusts no one). **No JWT, no audience, no `iss`
verification** — that belongs to the classic model and would reject the real add-on traffic; the
network-layer gate is Cloud Run invoker IAM. This is the single edge that decides `is_owner`, and so
the single edge that decides whether a message can ever be a command.

## Routing & the air-gap

`to_chat_message` sets `is_owner = is_operator(sender_email, allowlist)`. Then:

- **DM** (`space_type == "DM"`): a DM is implicitly addressed to the persona this deployment serves,
  so a persona responds to the **owner's** DM (or an @mention) without needing a domain-keyword hit —
  `should_respond_dm = is_command(msg) or persona.handle in msg.mentions`. (A non-operator in a DM →
  `is_owner=False` → data, never a command.)
- **Named space** (`space_type == "ROOM"`): `GroupChatOrchestrator.run_round` — the existing proven
  distributed self-selection (quiet-by-default, owner-only-command, turn-cap). Unchanged.

**The air-gap is the headline acceptance criterion** ("a persona cannot perform cross-domain writes
through the transport"): because `is_owner` is `True` **only** for an allowlisted operator email,
and `is_command` keys on `is_owner`, no message a persona (or any non-operator) sends through the
transport is ever a command — it is data. A persona's reply re-enters as `is_owner=False`. There is
no path by which transport traffic triggers a write except the owner's own word; the write gate
(`confirm_apply`) is untouched and downstream.

## Fast-ack & idempotency (the two known add-on constraints, as injectable hooks)

- **Fast-ack.** Chat expects a reply within **~30s** (and the interactive card budget is stricter,
  ~2s). A cold-worker model turn can exceed that. So `handle_event` computes the replies and
  **delivers them via the injected `ChatTransport`** (the worker's Chat REST poster in production);
  the worker returns `ack_response()` *immediately* and runs `handle_event` in a background task —
  exactly xhr's "respond fast, post the real reply async" pattern. The framework provides both ends
  (`ack_response()` and the reply-producing `handle_event`); the *when/how* of the async is the
  worker's wiring (documented). For a fast/stub responder (tests) `handle_event` is simply called
  synchronously.
- **Idempotency.** Chat can redeliver an event. `ChatRouter` takes an optional
  `already_handled: Callable[[str], bool]` + `mark_handled: Callable[[str], None]` keyed on the
  message id (`message.name`); a redelivered event is ignored with an ack. **Marked only after
  routing + delivery succeed** — a responder/transport failure leaves the event un-marked so the
  redelivery retries (at-least-once on failure; never a silently-dropped message). With **no hooks**
  there is no dedup (at-least-once); a worker injects a durable store, like xhr's file/GCS
  idempotency, and a message with no `message.name` is never deduped.

## API (`clonway_cockpit/chat_transport.py`)

```python
@dataclass(frozen=True)
class ChatOutcome:
    kind: str                         # the event kind handled
    replies: list[PostedReply]        # what each self-selecting persona said (also posted via transport)
    space_id: str
    ignored: str = ""                 # "" if handled; else why (e.g. "not-a-message", "duplicate")

@dataclass
class ChatRouter:
    registry: PersonaRegistry
    responder: Callable[[Persona, ChatMessage], str | None]
    transport: ChatTransport
    allowlist: frozenset[str]
    max_persona_turns: int = 6
    domain_matches: Callable[[str, Persona], bool] | None = None
    already_handled: Callable[[str], bool] | None = None
    mark_handled: Callable[[str], None] | None = None
    def handle_event(self, event: dict) -> ChatOutcome: ...

def ack_response() -> dict: ...        # {} — Chat's "ack, no message"
def text_response(text: str) -> dict:  # {"text": text} — a synchronous text reply
```

## Testing & acceptance

Fully self-verifiable with **synthetic add-on envelopes** + a stub responder + `FakeChatTransport`
(no Google, no model) — so the slice reaches a green, mergeable PR; the owner reviews because it is a
trust edge, and runs the live deploy. Maps to PR #73's acceptance:

- **"A named persona can receive a real Google Chat DM"** → a synthetic add-on `messagePayload` with
  `space.type=DM` and an operator sender normalises, bridges to a `ChatMessage(is_owner=True)`, and
  the persona's responder reply is delivered via the transport.
- **"A group-space message can be handled by distributed self-selection"** → a `messagePayload` with
  `space.type=ROOM` runs `run_round`; the domain-matching persona self-selects and replies, others
  stay quiet.
- **"A persona cannot perform cross-domain writes through the transport"** → a message from a
  non-allowlisted email (incl. one *claiming* to be the owner, and an agent/persona reply) yields
  `is_owner=False` / `is_command=False`; no command is produced. Fail-closed: an empty allowlist
  trusts no one.
- Robustness: malformed/partial/unknown envelopes → `kind="UNKNOWN"`, ignored with an ack, never
  raise. Idempotency: a redelivered message id is ignored.

**Docs in the PR:** this spec + `docs/chat-transport.md` (the core API, the air-gap, the fast-ack +
idempotency contracts) + an operator **IAM/deploy runbook** (the gsuiteaddons SA `run.invoker`,
`--allow-unauthenticated`, *declare it receives messages*, the allowlist env, **no audience**) + a
Delivery-table row marked **IN REVIEW** (code + tests; the production surface is not watched-working
until the operator deploys).
