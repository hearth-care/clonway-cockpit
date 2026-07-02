# Persona Google Chat add-on transport

`clonway_cockpit.chat_transport` is the **production surface** for the persona platform's group-chat
wire. The in-memory wire — distributed self-selection, the owner-only-command air-gap, the turn cap —
already lives in [`group_chat.py`](group-chat.md); this module turns an inbound **Google Chat
Workspace add-on** event into that wire's `ChatMessage` and routes it. Platform context:
[`persona-platform-architecture.md`](persona-platform-architecture.md) → "The Chat transport";
design spec:
[`superpowers/specs/2026-06-10-chat-transport-design.md`](superpowers/specs/2026-06-10-chat-transport-design.md).

**The framework owns the transport core and a stdlib reference edge**: normalise → auth → bridge →
route in `chat_transport.py`, plus the WSGI app, outbound Chat REST poster, durable seen store, and
local fake loop in `chat_addon.py`. A worker may front the WSGI callable with its own server, but the
reference path is deployable with `python -m clonway_cockpit.chat_addon --serve`.

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
    # gateway_responder is a FACTORY — call it to get the responder callable (persona → soul →
    # gateway). `colleagues`/`completer` are the worker's fleet + model gateway; `role` picks the
    # gateway model. Tests inject a stub responder instead.
    responder=gateway_responder(colleagues, completer, role="chat"),
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
- `ChatRouter.handle_event` routes a **DM** (`space_type == "DM"`, case-normalised) to the
  persona(s) this deployment serves and a **named space** (`"ROOM"`) through distributed
  self-selection (`GroupChatOrchestrator`). In a DM only the **owner** is answered (a non-operator's
  DM draws no reply — no command, no model turn spent); the @mentioned persona wins, else the sole
  persona, else the domain-relevant one — never a blanket fan-out.

## The air-gap (the headline safety property)

`is_owner` is set **only** for an allowlisted operator email (`is_operator`), and only the owner's
messages are commands (`is_command`). So **no message a persona — or any non-operator — sends through
the transport is ever a command**; it is data. A persona's reply re-enters the room as
`is_owner=False`. There is no path by which Chat traffic triggers a write except the owner's own word;
the write gate (`confirm_apply`) is untouched and downstream. The trust boundary is **fail-closed**: an
unconfigured allowlist (`CLONWAY_CHAT_OPERATORS` unset) trusts **no one**.

The *write* air-gap is the guarantee; in a named space a non-operator can still make a persona
**talk** if it self-selects (data, not a command — by design, the office is a shared room). In a
**DM**, though, a non-operator is ignored entirely (no reply, no model turn) — so an outsider can
neither command nor cost you a DM response.

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
  `mark_handled(message_id)` (keyed on `message.name`); a redelivered id is acked and ignored. The
  event is **marked handled only after routing + delivery succeed** — if the responder or transport
  raises, the event is left un-marked so the redelivery retries (at-least-once on failure: a
  transient error risks a duplicate reply, never a dropped message). Use a **durable** store in
  production (a file / GCS object, as `xhr-server` does); with **no hooks** there is no dedup, so
  delivery is at-least-once (a worker that can't tolerate a duplicate reply must inject a store, and
  a message with no `message.name` is never deduped).

> **Per-space DM memory is available.** Inject `remembering_responder` (`chat_memory.py`) in place of
> `gateway_responder` and each persona remembers earlier turns in the same DM/space — it splices the
> recent transcript between the soul system prompt and the new message, keyed by
> `scope_for_space(message.space)`, isolated per `persona.handle`. No router change; the default
> `gateway_responder` stays stateless for callers that want one-shot. **With memory on, the
> `already_handled`/`mark_handled` dedup below is mandatory** — a redelivered message would otherwise
> record the turn pair twice and corrupt later prompts (not just a duplicate reply). See
> `docs/thread-memory.md`.

## What the worker supplies

Workers supply persona/soul data, gateway config, operator allowlist, the runtime image, and the
Cloud Run / Workspace add-on deployment. They do **not** need to reimplement the route or REST poster
unless they have a worker-specific server stack.

## The shipped edge

`clonway_cockpit.chat_addon` is the framework-owned reference edge:

- `CHAT_EVENTS_PATH = "/chat-events"` and `build_addon_app(router, *, background)` expose the WSGI
  app. `background` is explicit: use `run_inline` for tests/local fake, `spawn_daemon_thread` for the
  deployable reference server.
- `FileSeenStore(path)` persists handled `message.name` values with append + flush + `fsync`, and
  plugs into `ChatRouter(already_handled=store.__contains__, mark_handled=store.add)`.
- `RestChatTransport(metadata_token_supplier)` posts replies to `spaces.messages.create` as
  `{"text": ...}` using the Cloud Run metadata-server access token.
- `build_serve_app(os.environ)` wires colleagues, the selected responder, REST poster, allowlist,
  durable seen store, and optional per-thread memory into the same WSGI app.
- `python -m clonway_cockpit.chat_addon --fake` runs a zero-Google local loop through the same app;
  add `--memory-dir DIR` to prove multi-turn memory locally.
- `python -m clonway_cockpit.chat_addon --serve --port 8080` starts the reference `wsgiref` server.

Environment contract for `--serve`:

| Env var | Meaning |
|---|---|
| `CLONWAY_CHAT_PERSONAS_DIR` | Directory of persona `.toml` files. |
| `CLONWAY_CHAT_SOULS_DIR` | Directory of matching soul `.md` files. |
| `CLONWAY_CHAT_GATEWAY_CONFIG` | JSON gateway config parsed by `GatewayConfig.from_dict`. |
| `CLONWAY_CHAT_ROLE` | Gateway role, default `chat`. |
| `CLONWAY_CHAT_OPERATORS` | Comma-separated operator allowlist; unset trusts no one. |
| `CLONWAY_CHAT_SEEN_FILE` | Durable dedup file, default `.cockpit/chat-seen.txt`. |
| `CLONWAY_CHAT_MEMORY_DIR` | Optional durable private-memory root; when set, `build_serve_app` uses per-thread memory. Must not be Cloud Run `/tmp`. |
| `PORT` | Cloud Run listen port; `--port` overrides locally. |

Per-space **multi-turn memory** is available framework-side via `CLONWAY_CHAT_MEMORY_DIR`, or by
calling `build_responder(..., memory_dir=Path(...))` directly in tests/custom servers. Keep durable
dedup enabled so redelivery does not record duplicate turns.

## Operator deploy runbook (the load-bearing other half)

A correctly-written transport that is mis-deployed is a dead transport. Deploy it as a **Workspace
add-on**, mirroring `xhr-server`:

1. **Cloud Run service.** Deploy a service that runs
   `python -m clonway_cockpit.chat_addon --serve` with `--allow-unauthenticated` (the IAM invoker
   grant + the email allowlist are the gates, *not* an app token). Region pinned to the fleet's
   region.
2. **IAM invoker.** Grant the Workspace add-on service agent `roles/run.invoker` on the service:
   `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`. Without this, the add-on
   cannot invoke the endpoint.
3. **NO audience / JWT pin.** Do **not** configure an "Authentication Audience" or verify a Bearer
   `aud`/`iss` — that is the *classic* model and it rejects real add-on traffic.
4. **Declare the triggers.** In the add-on deployment manifest (`gcloud workspace-add-ons` /
   `addOns.chat`), declare the message-receipt trigger (the Chat add-on's `MESSAGE` /
   added-to-space events) so the add-on actually dispatches DMs to your endpoint. If it is not
   configured to receive messages, **DMs never reach Cloud Run** — the #1 "deployed but dead" cause.
   Copy the working manifest + deploy steps from the reference, Auto-HR `xhr-server`
   (`src/xhr/chat/`, `src/xhr/webhook/app.py:/chat-events`).
5. **Operator allowlist.** Set `CLONWAY_CHAT_OPERATORS` to the comma-separated operator email(s). An
   empty/unset value trusts no one (fail-closed) — the transport will ack but never treat anything as
   a command.
6. **Runtime config.** Set `CLONWAY_CHAT_PERSONAS_DIR`, `CLONWAY_CHAT_SOULS_DIR`,
   `CLONWAY_CHAT_GATEWAY_CONFIG`, optional `CLONWAY_CHAT_ROLE`, `CLONWAY_CHAT_SEEN_FILE`, and
   `CLONWAY_CHAT_MEMORY_DIR` when memory should be live. Point memory at a durable mount, never
   Cloud Run `/tmp`.
7. **Outbound poster identity.** The reference `RestChatTransport.post` authenticates from Cloud Run's
   metadata-server token (scope `chat.bot`); messages appear from the add-on identity.

Until steps 1–7 are done and a real DM has been **watched landing**, the slice is *built* but not
*demonstrably working* — see the architecture's delivery ladder (exists in code → deployed → enabled →
watched working).

## Robustness & scope

Normalisation never raises (unknown shape → ignored). The router acts only on `MESSAGE` events in v1;
`ADDED_TO_SPACE` / `REMOVED_FROM_SPACE` / `CARD_CLICKED` are surfaced (so a worker can handle them
deliberately) but acked-and-ignored here. Cards/buttons and the live deploy remain worker/operator
work; the reference HTTP route, REST poster, local fake, durable dedup store, and memory selector are
shipped in `chat_addon.py`. Per-space multi-turn memory is documented in `docs/thread-memory.md`.
