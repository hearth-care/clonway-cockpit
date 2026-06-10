# Persona Google Chat add-on transport

`clonway_cockpit.chat_transport` is the **production surface** for the persona platform's group-chat
wire. The in-memory wire — distributed self-selection, the owner-only-command air-gap, the turn cap —
already lives in [`group_chat.py`](group-chat.md); this module turns an inbound **Google Chat
Workspace add-on** event into that wire's `ChatMessage` and routes it. Platform context:
[`persona-platform-architecture.md`](persona-platform-architecture.md) → "The Chat transport";
design spec:
[`superpowers/specs/2026-06-10-chat-transport-design.md`](superpowers/specs/2026-06-10-chat-transport-design.md).

**The framework owns the transport-agnostic core** (normalise → auth → bridge → route); the **worker**
owns the edge (the HTTP route, the outbound Chat REST poster, the Cloud Run deploy). So the framework
stays `rich`-only and every worker inherits the same envelope handling + trust boundary.

> It is a **Workspace add-on, not a classic HTTP Chat app.** The two are materially different and
> conflating them has burned whole sessions. This module mirrors the *proven* Auto-HR `xhr-server`
> add-on (`src/xhr/chat/`). The deploy runbook below is the load-bearing other half.

## The core API

```python
from clonway_cockpit.chat_transport import (
    normalize_event, load_allowlist, ChatRouter, ack_response,
)
from clonway_cockpit.colleague import gateway_responder        # the production responder
from clonway_cockpit.group_chat import ChatTransport           # your Chat REST poster implements this

router = ChatRouter(
    registry=registry,                 # the personas this deployment serves
    responder=gateway_responder,       # persona → soul → gateway (a stub in tests)
    transport=chat_rest_poster,        # posts replies back to a space (worker-supplied)
    allowlist=load_allowlist(),        # CLONWAY_CHAT_OPERATORS — the operator-email trust boundary
    already_handled=seen.__contains__, # optional idempotency (Chat redelivers)
    mark_handled=seen.add,
)

outcome = router.handle_event(event_dict)   # event_dict = the parsed JSON body Chat POSTed
# outcome.replies — what each self-selecting persona said (already posted via transport)
# outcome.ignored — "" if handled, else "not-a-message" / "duplicate"
```

- `normalize_event(event) -> NormalizedChatEvent` flattens the add-on envelope (nested
  `chat.{messagePayload | addedToSpacePayload | removedFromSpacePayload | buttonClickedPayload}`) —
  or a classic flat event — into `{kind, text, space_id, space_type, sender_email, sender_name,
  message_id, raw}`. It is **best-effort and never-raise**: an unknown/malformed shape →
  `kind="UNKNOWN"`, which the router acks and ignores.
- `ChatRouter.handle_event` routes a **DM** (`space_type == "DM"`) to the persona(s) this deployment
  serves and a **named space** (`"ROOM"`) through distributed self-selection (`GroupChatOrchestrator`).

## The air-gap (the headline safety property)

`is_owner` is set **only** for an allowlisted operator email (`is_operator`), and only the owner's
messages are commands (`is_command`). So **no message a persona — or any non-operator — sends through
the transport is ever a command**; it is data. A persona's reply re-enters the room as
`is_owner=False`. There is no path by which Chat traffic triggers a write except the owner's own word;
the write gate (`confirm_apply`) is untouched and downstream. The trust boundary is **fail-closed**: an
unconfigured allowlist (`CLONWAY_CHAT_OPERATORS` unset) trusts **no one**.

There is deliberately **no JWT / audience / issuer check** at the app layer — pinning an audience
*rejects* the real add-on traffic. The network-layer gate is Cloud Run invoker IAM (below); the
app-layer gate is the email allowlist.

## The two add-on constraints

- **Fast-ack (~30s).** Chat expects a reply within ~30s (the interactive-card budget is stricter,
  ~2s); a cold-worker model turn can exceed that. So in production the worker returns
  `ack_response()` (`{}`) **immediately** and runs `handle_event` in a **background task** that posts
  the persona replies via the Chat REST API (the injected `transport`). The framework provides both
  ends; the *when/how* of the async is the worker's wiring. For a fast/stub responder, call
  `handle_event` synchronously and return `text_response(reply)`.
- **Idempotency.** Chat can redeliver an event. Inject `already_handled(message_id) -> bool` +
  `mark_handled(message_id)` (keyed on `message.name`); a redelivered id is acked and ignored. Use a
  durable store in production (a file / GCS object, as `xhr-server` does); the default (no hooks) does
  no dedup.

## What the worker supplies

This module is transport-agnostic. The worker provides: (1) the **HTTP route** (`POST /chat-events`)
that parses the JSON body and calls `handle_event`; (2) a `ChatTransport` whose `post(space, text)`
calls the Chat REST `spaces.messages.create` as the Chat-app service account; (3) the **deploy**
(below). Per-space **multi-turn memory** is a future slice — the transport is exactly where a later
change attaches `PersonaMemory.thread(slug(space_id))` (the private-memory tier now exists, PR #77),
but it is not wired here.

## Operator deploy runbook (the load-bearing other half)

A correctly-written transport that is mis-deployed is a dead transport. Deploy it as a **Workspace
add-on**, mirroring `xhr-server`:

1. **Cloud Run service.** Deploy with `--allow-unauthenticated` (the IAM invoker grant + the email
   allowlist are the gates, *not* an app token). Region pinned to the fleet's region.
2. **IAM invoker.** Grant the Workspace add-on service agent `roles/run.invoker` on the service:
   `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`. Without this, the add-on
   cannot invoke the endpoint.
3. **NO audience / JWT pin.** Do **not** configure an "Authentication Audience" or verify a Bearer
   `aud`/`iss` — that is the *classic* model and it rejects real add-on traffic.
4. **Declare the triggers.** In the add-on deployment manifest, declare that it **receives messages**
   (and is **added to / removed from spaces** as needed). If it is not configured to receive
   messages, **DMs never reach Cloud Run** — the #1 "deployed but dead" cause.
5. **Operator allowlist.** Set `CLONWAY_CHAT_OPERATORS` to the comma-separated operator email(s). An
   empty/unset value trusts no one (fail-closed) — the transport will ack but never treat anything as
   a command.
6. **Outbound poster identity.** The worker's `ChatTransport.post` authenticates as the Chat-app
   service account (scope `chat.bot`); cards/messages appear "from <persona bot>".

Until step 1–5 are done and a real DM has been **watched landing**, the slice is *built* but not
*demonstrably working* — see the architecture's delivery ladder (exists in code → deployed → enabled →
watched working).

## Robustness & scope

Normalisation never raises (unknown shape → ignored). The router acts only on `MESSAGE` events in v1;
`ADDED_TO_SPACE` / `REMOVED_FROM_SPACE` / `CARD_CLICKED` are surfaced (so a worker can handle them
deliberately) but acked-and-ignored here. Cards/buttons, the outbound Chat REST client, the HTTP
route, the live deploy, and per-space multi-turn memory are out of this slice (worker-side or later).
