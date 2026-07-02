# [Plan] Google Chat Workspace add-on transport edge (persona go-live Slice B)

- **Date:** 2026-07-02 · **Branch:** `claude/plan-chat-addon-transport` · **Status:** plan ready — doc-only, plan-signalled, builder implements on this branch
- **Binding companions:** [`docs/chat-transport.md`](../../chat-transport.md) (core API + operator deploy runbook), [`docs/superpowers/specs/2026-06-10-chat-transport-design.md`](../specs/2026-06-10-chat-transport-design.md) (core design), [`docs/persona-platform-go-live-plan.md`](../../persona-platform-go-live-plan.md) (Slice B), [`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md) ("The Chat transport" + delivery table)

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task (Claude: superpowers:subagent-driven-development or superpowers:executing-plans; Codex: the same phase/TDD/verification discipline). Steps use checkbox (`- [ ]`) syntax for tracking. Tick checkboxes as work lands and commit this plan with the code.

## Why (problem & goal)

The go-live plan calls the Google Chat transport **the keystone: "Nothing goes green without it."**
The transport **core** merged in #78 (`src/clonway_cockpit/chat_transport.py`: envelope
normalisation, operator allowlist, `ChatRouter`, ack/text responses) and per-space memory in #79 —
but **no deployable edge exists anywhere**: there is no HTTP surface that receives a real Workspace
add-on POST, no outbound Chat REST poster, no durable dedup store, and no way to run the transport
locally. Personas remain laptop-local demos.

**Goal:** ship the framework-owned, stdlib-only **add-on transport edge** —
`src/clonway_cockpit/chat_addon.py` — wired end-to-end to the merged `chat_transport` core at a
production call site in this repo (`python -m clonway_cockpit.chat_addon --serve`, the deployable
reference server), with a local-dev fake (`--fake`) that exercises the same WSGI app, a durable
idempotency store, and a test per event type built on real add-on envelope shapes.

## Current-state evidence (read before coding)

- Core (merged, do not modify semantics): `src/clonway_cockpit/chat_transport.py` —
  `normalize_event`, `parse_allowlist`/`load_allowlist`/`is_operator` (env `CLONWAY_CHAT_OPERATORS`,
  fail-closed), `to_chat_message`, `ChatRouter.handle_event` (DM/ROOM routing, dedup hooks,
  mark-handled-only-after-delivery), `ack_response()` (`{}`), `text_response(text)`.
- Core tests + envelope fixtures: `tests/test_chat_transport.py` (`addon_message(...)` — the nested
  `chat.messagePayload.{message,space,user}` add-on shape).
- Production wiring seams (verified signatures):
  `colleague.load_colleagues(personas_dir: Path, souls_dir: Path) -> ColleagueRegistry`,
  `ColleagueRegistry.registry -> PersonaRegistry` (property),
  `colleague.gateway_responder(colleagues, completer, *, role, quiet_on_error=True)`,
  `gateway.Gateway(GatewayConfig.from_dict(cfg), telemetry_base=...)`, `Gateway.validate(...) -> list[str]`.
- Proven in-family reference (cite, mirror, do not import): Auto-HR `xhr-server` —
  `src/xhr/webhook/app.py` (`POST /chat-events`: 422 on malformed JSON/envelope, background task for
  the slow write so the ack meets the interactive window), `src/xhr/chat/operator_auth.py`
  (fail-closed email allowlist), `src/xhr/chat/events.py` (accepts both the classic flat event and
  the nested Workspace add-on envelope), `src/xhr/chat/dispatch.py` (audit + text responses).
- Salvaged from stale branch `Codex/quarter-plan-workspace-addon-transport` (2026-06-10, doc-only
  brief; its core scope has since merged as #78): **kept** — the edge acceptance criteria (a named
  persona can receive a real DM; a group-space message routes by self-selection; no cross-domain
  write path through the transport), the fast-ack requirement, "use xhr's envelope/auth model", and
  the no-central-router non-goal. **Dropped** — its work items "define envelope normalization" and
  "add operator allowlist" (both shipped in #78), and its docs-only-brief framing (superseded by
  this stricter plan).

## Binding decisions (do not re-litigate)

- **It is a Workspace add-on, not a classic HTTP Chat app.** Auth is **Cloud Run invoker IAM + the
  operator-email allowlist. There is NO JWT / audience / issuer check at the app layer** — an
  audience pin rejects real add-on traffic (`docs/chat-transport.md` → "The air-gap";
  `chat_transport.py` module docstring; mirrored from Auto-HR `xhr-server`, whose production v1
  trusts Cloud Run IAM + `XHR_OPS_OPERATORS` and performs no bearer-token verification —
  `src/xhr/webhook/app.py` module docstring notes JWT only as a possible v2). The edge therefore
  serves requests **without** requiring an `Authorization` header, and a test proves it.
- **Framework owns a stdlib-only reference edge.** No new runtime dependencies: WSGI (PEP 3333) app
  + `wsgiref.simple_server` + `urllib.request` + `threading`. Workers MAY front the app callable
  with their own server (xhr uses FastAPI); the framework module must not import any web framework.
- **Fast-ack is an explicit, required choice.** `build_addon_app(router, *, background)` — the
  `background` executor is a required argument with two shipped implementations: `run_inline`
  (synchronous; tests/local fake) and `spawn_daemon_thread` (production). No silent default.
- **Idempotency key = Chat's `message.name`** (a stable Google-issued content id, never a uuid/run
  id), persisted in a durable `FileSeenStore`; marking stays **after** delivery (core behaviour) so
  a failed delivery is retried by Chat's redelivery — at-least-once, never silently dropped (HR4:
  no money is written; the only durable writes are the seen-file append and the outbound Chat POST,
  whose partial-failure path is exactly this un-marked-retry window).
- **Content-free logging.** The edge never logs message text, sender emails, or space ids — same
  telemetry discipline as the gateway. A test asserts it.
- **Cross-repo work stays out.** Wiring Milo on `xbook-server` (go-live says Slice B "lands on the
  existing `xbook-server`") is an auto-bookkeeper change; the console/deploy steps are operator
  work. Both are named follow-ups/OPERATOR TODOs — nothing here depends on them (HR11).

## Non-goals (out of scope for this PR)

- Slice D group-chat go-live (live space provisioning, multi-worker fleet rooms). `ChatRouter`'s
  existing ROOM path is exercised through the edge, but no new group features.
- Slice C memory wiring (`remembering_responder` + its mandatory dedup in a live deploy) — the
  responder seam accepts it unchanged; choosing it is deploy configuration.
- Gateway/model changes of any kind. Cards/buttons UI (CARD_CLICKED is acked + surfaced only, as in
  core v1). Worker-template chat-edge scaffolding (named follow-up). The actual Cloud Run deploy,
  IAM grant, and add-on manifest (OPERATOR TODO).

## Functional contract — `src/clonway_cockpit/chat_addon.py`

Public API (all covered by tests):

| Name | Contract |
|---|---|
| `CHAT_EVENTS_PATH = "/chat-events"` | single source of truth for the route (docs/tests import it) |
| `MAX_BODY_BYTES = 1_048_576` | request-body cap; constraint: must exceed the largest real Chat envelope (tens of KB) by a wide margin |
| `build_addon_app(router: ChatRouter, *, background, max_body: int = MAX_BODY_BYTES) -> WSGI app` | the edge; `background(fn)` schedules `router.handle_event(event)` |
| `run_inline(fn)` / `spawn_daemon_thread(fn)` | the two executors (sync; daemon `threading.Thread`) |
| `FileSeenStore(path: Path)` | durable dedup: loads ids at init, `add(id)` appends+flushes+fsyncs; supports `id in store` / `.add` so it plugs into `already_handled=store.__contains__, mark_handled=store.add` |
| `RestChatTransport(token_supplier, base_url="https://chat.googleapis.com/v1", timeout=10.0, opener=urllib.request.urlopen)` | implements `group_chat.ChatTransport`: `post(space, text)` → POST `{base_url}/{space}/messages` with JSON `{"text": text}` and `Authorization: Bearer {token_supplier()}`; non-2xx raises (so the core leaves the event un-marked); `iter_messages(space)` returns an empty iterator (push transport — inbound arrives as events) |
| `metadata_token_supplier() -> str` | Cloud Run metadata-server token: GET `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token`, header `Metadata-Flavor: Google`, returns `access_token` |
| `fake_dm_envelope(text, *, email="owner@clonway.example", space_id="spaces/LOCAL", space_type="DM", msg_id=...) -> dict` | builds a real nested add-on MESSAGE envelope; single source for `--fake` input AND the new edge tests; a boundary test pins `normalize_event(fake_dm_envelope("x")).kind == MESSAGE` so it can never drift off the core's contract (HR6) |
| `build_serve_app(environ: Mapping[str, str]) -> WSGI app` | pure env→app wiring (below); `main()` = argparse (`--serve`/`--fake`/`--port`) around it |

HTTP contract (the full route/method/body state set — each row is an acceptance checkbox in Task 1/2):

| Request | Response |
|---|---|
| `POST /chat-events`, valid JSON add-on envelope | `200 OK`, body exactly `json.dumps(ack_response())` = `{}` (single source of truth: `ack_response()` from core — never a literal), `Content-Type: application/json` |
| `POST /chat-events`, malformed JSON | `400 Bad Request`; body content-free; router never called |
| `POST /chat-events`, body > `max_body` or missing/invalid `CONTENT_LENGTH` | `413 Payload Too Large` / `400 Bad Request`; router never called |
| `GET /chat-events` | `405 Method Not Allowed` |
| `GET /healthz` | `200 OK`, body `ok` |
| any other path | `404 Not Found` |
| request without `Authorization` header | served normally (IAM is the network gate; no app-layer token check) |

Env contract for `build_serve_app` (names are the contract; `CLONWAY_CHAT_OPERATORS` is owned by
core `load_allowlist()` — the edge never redefines it):

| Env var | Meaning |
|---|---|
| `CLONWAY_CHAT_PERSONAS_DIR` / `CLONWAY_CHAT_SOULS_DIR` | dirs for `load_colleagues` (identity `.toml` + soul `.md`) |
| `CLONWAY_CHAT_GATEWAY_CONFIG` | path to a JSON file parsed with `GatewayConfig.from_dict` |
| `CLONWAY_CHAT_ROLE` | gateway role for `gateway_responder` (default `"chat"`) |
| `CLONWAY_CHAT_OPERATORS` | operator allowlist (existing core contract, fail-closed) |
| `CLONWAY_CHAT_SEEN_FILE` | `FileSeenStore` path (default `.cockpit/chat-seen.txt`) |
| `PORT` | listen port (Cloud Run convention; `--port` overrides) |

Startup is fail-closed: `Gateway.validate(roles=[role])` problems → print problems (content-free)
and exit non-zero; never serve a half-configured persona.

## Safety invariants (cell table — every row bound to a named test; HR3)

| # | State | Required behaviour | Test (in `tests/test_chat_addon.py`) |
|---|---|---|---|
| 1 | add-on MESSAGE, DM, allowlisted operator | 200 `{}`; exactly one reply posted via transport to the event's space | `test_owner_dm_is_acked_and_reply_posted` |
| 2 | add-on MESSAGE, DM, non-operator sender | 200 `{}`; **zero** transport posts; responder never invoked (the air-gap + no model spend) | `test_non_operator_dm_is_acked_but_draws_no_reply` |
| 3 | add-on MESSAGE, ROOM, operator | 200 `{}`; replies only from domain-selecting personas (core self-selection through the edge) | `test_room_message_routes_by_self_selection` |
| 4 | `addedToSpacePayload` | 200 `{}`; no reply, no responder call | `test_event_kind_matrix[ADDED_TO_SPACE]` |
| 5 | `removedFromSpacePayload` | 200 `{}`; no reply, no responder call | `test_event_kind_matrix[REMOVED_FROM_SPACE]` |
| 6 | `buttonClickedPayload` | 200 `{}`; no reply, no responder call | `test_event_kind_matrix[CARD_CLICKED]` |
| 7 | valid JSON, unknown/malformed envelope (`{}`, `{"chat": {}}`, `{"chat": "nope"}`, `[1,2]`) | 200 `{}` (UNKNOWN is acked, never 5xx) | `test_unknown_envelope_is_acked_not_5xx` |
| 8 | malformed JSON body | 400; router untouched | `test_malformed_json_is_400_never_500` |
| 9 | redelivered `message.name` (same envelope twice, seen-store injected) | second POST → 200 `{}`, zero additional transport posts | `test_redelivery_is_deduped_through_the_edge` |
| 10 | responder raises during background handling | HTTP already acked 200; event **not** marked in the seen store (redelivery will retry); exception surfaced content-free | `test_background_failure_leaves_event_unmarked` |
| 11 | process restart (new `FileSeenStore` on same path) | previously-marked id still deduped | `test_seen_store_survives_restart` |
| 12 | request without `Authorization` header | served (no app-layer JWT/audience check — the add-on IAM model) | `test_no_auth_header_required_iam_model` |
| 13 | fast-ack: responder blocked on an event | POST returns 200 `{}` while the responder is still blocked; reply posted after unblock | `test_fast_ack_returns_before_responder_completes` |
| 14 | any request/handling | no message text / sender email / space id in log output | `test_edge_logging_is_content_free` |
| 15 | outbound post fails (non-2xx / URLError) | `RestChatTransport.post` raises; nothing marked handled | `test_rest_transport_error_propagates` |

## Real-contract grounding (HR12)

- Envelope fixtures use the **nested Workspace add-on shape** (`chat.{messagePayload|addedToSpacePayload|removedFromSpacePayload|buttonClickedPayload}` + `commonEventObject`, no
  top-level `type`) exactly as already pinned in the merged core fixtures
  (`tests/test_chat_transport.py::addon_message`) and as observed in production by Auto-HR
  (`src/xhr/chat/events.py` normalises the same four `*Payload` keys; its golden CARD_CLICKED
  fixture lives in `tests/test_chat_events_models.py`). Google's reference: Chat app interaction
  events (Workspace add-on event schema) — the four payload keys above.
- QA acceptance line: **fixtures verified against the add-on payload-key set the core already
  normalises (`_ADDON_PAYLOAD_KINDS` in `chat_transport.py`) — no invented event kinds, no
  hand-built flat shapes pretending to be add-on events.**
- The outbound REST contract is `spaces.messages.create`: POST
  `https://chat.googleapis.com/v1/{space}/messages` with `{"text": ...}` as the Chat-app service
  account (scope `chat.bot`) — the shape `docs/chat-transport.md` §"What the worker supplies"
  already binds.

## Worked example (pinned to the real fixture; HR7)

Fixture: `fake_dm_envelope("reconcile the bank?")` → space `spaces/LOCAL`, sender
`owner@clonway.example`; registry `[Persona(handle="milo", name="Milo", domain="the books — invoicing, payroll, cash")]`; allowlist `{"owner@clonway.example"}`; stub responder
`f"{persona.name}: on it."`; `background=run_inline`.

Expected, exactly: HTTP `200 OK`; response body parses to `{}`;
`transport.posted == [("spaces/LOCAL", "Milo: on it.")]` (sole-persona DM → milo answers; reply
delivered to the event's space). The non-operator variant (`email="evil@x.com"`) yields the same
`200 OK` + `{}` and `transport.posted == []`.

---

## Implementation plan

**Goal:** the deployable add-on edge, wired end-to-end and provably drivable with zero Google.

**Architecture:** `chat_addon.py` (edge: WSGI app + executors + seen store + REST poster + env
wiring + CLI) sits strictly downstream of `chat_transport.py` (core: normalise → auth → bridge →
route). Pure request parsing is separated from I/O: the WSGI app never talks to Google; only
`RestChatTransport`/`metadata_token_supplier` do, behind injectable seams.

**Tech stack:** Python stdlib only (`wsgiref`, `urllib.request`, `json`, `threading`, `os`,
`pathlib`). **No new dependencies.**

### Global constraints

- Safety invariants: the cell table above — one test per cell, all on the edge path (not core-only).
- Sources of truth (HR6): ack body = `ack_response()`; route = `CHAT_EVENTS_PATH`; allowlist env
  name = core `load_allowlist()`; fake envelope = `fake_dm_envelope` with its on-contract
  normaliser test.
- Repo rules: single write gate untouched (this PR adds **no** write/apply path — replies are
  plain messages); model calls only via the gateway; content-free telemetry/logging;
  changelog: add an `## [Unreleased]` entry (release-policy.md — `src/` change with worker-visible
  surface).
- Operator-facing: **yes** (new deployable entrypoint + env contract + console registration) ⇒
  post a `RUNBOOK DELTA` comment on `hearth-care/auto-orchestrator#196` and repeat it in the DONE
  comment (HR1) — checkbox in Task 6.
- **Depends on: nothing unmerged.** Core #78/#79 are on `origin/main`. No `[Wave N]` tag (HR11).
- Gates (exact canonical commands QA re-runs, verbatim, full scope — paste output tails):
  `make lint`, `make format`, `make typecheck`, `make test` (or the one-shot `make check`).

### Task 1 — module skeleton: route/method/body edge + the on-contract fake envelope

**Files:** create `src/clonway_cockpit/chat_addon.py`; create `tests/test_chat_addon.py`.
**Production call site (HR9):** `build_addon_app` is the app every later task wires; this task pins
its HTTP contract.
**Interfaces:** `CHAT_EVENTS_PATH`, `MAX_BODY_BYTES`, `build_addon_app`, `run_inline`,
`fake_dm_envelope`.

- [x] **Step 1 — failing tests.** WSGI-level, no server socket; assert observable status + body
  (HR8). Embed verbatim:

```python
import io
import json

from clonway_cockpit.chat_addon import (
    CHAT_EVENTS_PATH,
    MAX_BODY_BYTES,
    build_addon_app,
    fake_dm_envelope,
    run_inline,
)
from clonway_cockpit.chat_transport import MESSAGE, ChatRouter, normalize_event, parse_allowlist
from clonway_cockpit.group_chat import FakeChatTransport
from clonway_cockpit.persona import Persona, PersonaRegistry


def _milo() -> Persona:
    return Persona.from_dict(
        {"handle": "milo", "name": "Milo", "domain": "the books — invoicing, payroll, cash"}
    )


def _stub_responder(persona: Persona, message) -> str:
    return f"{persona.name}: on it."


def _make_app(transport: FakeChatTransport, *, background=run_inline, **router_kw):
    router = ChatRouter(
        registry=PersonaRegistry.from_personas([_milo()]),
        responder=_stub_responder,
        transport=transport,
        allowlist=parse_allowlist("owner@clonway.example"),
        **router_kw,
    )
    return build_addon_app(router, background=background)


def _call(app, method: str, path: str, body: bytes = b"") -> tuple[str, bytes]:
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status

    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    out = b"".join(app(env, start_response))  # run the app BEFORE reading captured["status"]
    return captured["status"], out


def test_fake_envelope_is_on_contract_with_the_core_normaliser():
    assert normalize_event(fake_dm_envelope("x")).kind == MESSAGE  # HR6 boundary validator


def test_routing_edge_states():
    app = _make_app(FakeChatTransport())
    assert _call(app, "GET", "/healthz")[0] == "200 OK"
    assert _call(app, "GET", CHAT_EVENTS_PATH)[0] == "405 Method Not Allowed"
    assert _call(app, "POST", "/nope", b"{}")[0] == "404 Not Found"
    assert _call(app, "POST", CHAT_EVENTS_PATH, b"{not json")[0] == "400 Bad Request"


def test_oversized_body_is_rejected_without_reading():
    app = _make_app(FakeChatTransport())
    big = b"x" * (MAX_BODY_BYTES + 1)  # the constraint, not a magic number
    assert _call(app, "POST", CHAT_EVENTS_PATH, big)[0] == "413 Payload Too Large"
```

- [x] **Step 2 — run, confirm RED:** `uv run pytest tests/test_chat_addon.py -q` → expect
  `ImportError: cannot import name 'build_addon_app'` (proves load-bearing).
- [x] **Step 3 — implement minimal:** the WSGI callable dispatching on
  `(REQUEST_METHOD, PATH_INFO)`; `CONTENT_LENGTH` parsed defensively (absent/non-int → 400);
  length > `max_body` → 413 **before** reading the body; JSON parse failure → 400; valid JSON →
  `background(lambda: router.handle_event(event))` then respond
  `json.dumps(ack_response()).encode()` with `Content-Type: application/json`. `fake_dm_envelope`
  mirrors the core fixture's nested shape exactly.
- [x] **Step 4 — verify:** `uv run pytest tests/test_chat_addon.py -q` → `3 passed` (the route-state cases are grouped in one test).
- [x] **Step 5 — commit:** `feat(chat-addon): WSGI edge skeleton — routing, body guards, on-contract fake envelope`

### Task 2 — event flow: ack + per-kind matrix + air-gap + dedup + fast-ack + failure path

**Files:** modify `src/clonway_cockpit/chat_addon.py`; extend `tests/test_chat_addon.py`.
**Production call site (HR9):** the `POST /chat-events` handler calling
`router.handle_event` — cells 1–10, 12–13 of the invariant table all pass through it.

- [x] **Step 1 — failing tests.** Add, at minimum (names bound in the cell table): the worked
  example pair (verbatim below), `test_room_message_routes_by_self_selection` (two personas,
  payroll question, only milo replies — mirror `test_group_space_distributed_self_selection`
  through the edge), parametrised `test_event_kind_matrix` over
  `addedToSpacePayload` / `removedFromSpacePayload` / `buttonClickedPayload` (200 `{}` + zero
  posts + a spy responder proving zero invocations), `test_unknown_envelope_is_acked_not_5xx`
  (`{}`, `{"chat": {}}`, `{"chat": "nope"}`, `[1, 2]`),
  `test_redelivery_is_deduped_through_the_edge` (inject `seen: set` via
  `already_handled=seen.__contains__, mark_handled=seen.add`; POST the same envelope twice; one
  post total), `test_background_failure_leaves_event_unmarked` (raising responder + `run_inline`
  wrapped to swallow at the executor boundary — assert `seen == set()` after the failed delivery),
  `test_fast_ack_returns_before_responder_completes` (responder blocks on a `threading.Event`;
  `background=spawn_daemon_thread`; assert the POST returns `200 OK` while blocked, then release
  and join and assert the post landed), `test_no_auth_header_required_iam_model` (no
  `HTTP_AUTHORIZATION` in environ — still 200), and `test_edge_logging_is_content_free` (caplog/
  capsys: no `"reconcile"`, no `owner@clonway.example`, no `spaces/` in log output).

```python
def test_owner_dm_is_acked_and_reply_posted():
    transport = FakeChatTransport()
    app = _make_app(transport)
    body = json.dumps(fake_dm_envelope("reconcile the bank?")).encode()
    status, out = _call(app, "POST", CHAT_EVENTS_PATH, body)
    assert status == "200 OK"
    assert json.loads(out) == {}  # exactly ack_response()
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]


def test_non_operator_dm_is_acked_but_draws_no_reply():
    transport = FakeChatTransport()
    app = _make_app(transport)
    body = json.dumps(fake_dm_envelope("pay everyone now", email="evil@x.com")).encode()
    status, out = _call(app, "POST", CHAT_EVENTS_PATH, body)
    assert status == "200 OK" and json.loads(out) == {}
    assert transport.posted == []  # the air-gap holds at the edge
```

- [x] **Step 2 — run, confirm RED** (`uv run pytest tests/test_chat_addon.py -q`; the new tests
  fail — e.g. the executor seam and spy assertions don't exist yet).
- [x] **Step 3 — implement:** background-executor error handling (exception → content-free
  one-line stderr log, never a 5xx since the ack already went out), `spawn_daemon_thread`
  (`threading.Thread(target=fn, daemon=True).start()`), structured dispatch of parsed events into
  `router.handle_event`. Do **not** re-implement any routing/auth — the router owns it.
- [x] **Step 4 — verify:** `uv run pytest tests/test_chat_addon.py -q` → `18 passed`.
- [x] **Step 5 — commit:** `feat(chat-addon): event flow — ack, kind matrix, air-gap, dedup seam, fast-ack`

### Task 3 — durable idempotency: `FileSeenStore`

**Files:** modify `src/clonway_cockpit/chat_addon.py`; extend `tests/test_chat_addon.py`.
**Production call site (HR9):** `build_serve_app` (Task 5) injects it as
`already_handled=store.__contains__, mark_handled=store.add`; Task 3's tests plug it through
`build_addon_app` the same way.

- [x] **Step 1 — failing tests:** `test_seen_store_survives_restart` (mark via a POST through the
  edge, rebuild a new `FileSeenStore(tmp_path / "seen.txt")` on the same path, POST the same
  envelope → zero new posts); `test_seen_store_tolerates_missing_file` (fresh path → empty, no
  raise).
- [x] **Step 2 — RED**, then **Step 3 — implement:** load ids into a set at init (missing file →
  empty), `add()` appends a line, flushes, `os.fsync`. Idempotency key = the event's
  `message.name` exactly as the core hands it (`NormalizedChatEvent.message_id`); no hashing, no
  uuid (HR4).
- [x] **Step 4 — verify** (`uv run pytest tests/test_chat_addon.py -q`), **Step 5 — commit:**
  `feat(chat-addon): durable FileSeenStore dedup`

### Task 4 — outbound: `RestChatTransport` + `metadata_token_supplier`

**Files:** modify `src/clonway_cockpit/chat_addon.py`; extend `tests/test_chat_addon.py`.
**Production call site (HR9):** `build_serve_app` (Task 5) passes it as the router's `transport`.

- [ ] **Step 1 — failing tests** (fake `opener` injected; no network): `test_rest_transport_posts_message_create` — `RestChatTransport(token_supplier=lambda: "tok", opener=fake).post("spaces/AAA", "hi")` asserts exactly one request to
  `https://chat.googleapis.com/v1/spaces/AAA/messages`, method POST, header
  `Authorization: Bearer tok`, `Content-Type: application/json`, body `{"text": "hi"}`;
  `test_rest_transport_error_propagates` (opener raising / returning 500 → `post` raises);
  `test_rest_transport_iter_messages_is_empty` (push model);
  `test_metadata_token_supplier_shape` (fake opener: asserts URL + `Metadata-Flavor: Google`
  header, returns parsed `access_token`).
- [ ] **Step 2 — RED**, **Step 3 — implement** with `urllib.request.Request`; never log text/space/
  email (extend `test_edge_logging_is_content_free` to cover the failure log line).
- [ ] **Step 4 — verify**, **Step 5 — commit:** `feat(chat-addon): Chat REST poster + Cloud Run metadata token supplier`

### Task 5 — the production call site: `build_serve_app` + `main()` (`--serve` / `--fake`)

**Files:** modify `src/clonway_cockpit/chat_addon.py` only — the entrypoint is module-local
(`python -m clonway_cockpit.chat_addon` via `main()` + an `if __name__ == "__main__":` block in
`chat_addon.py`; do **not** add a package-level `__main__.py`). Extend `tests/test_chat_addon.py`.
**Production call site (HR9):** `main()` → `build_serve_app(os.environ)` →
`wsgiref.simple_server.make_server("", port, app).serve_forever()`. This is the deployable
reference entrypoint the runbook names; every deliverable above is wired through it.

- [ ] **Step 1 — failing tests:**
  `test_build_serve_app_wires_env_to_app` — monkeypatched env pointing
  `CLONWAY_CHAT_PERSONAS_DIR`/`CLONWAY_CHAT_SOULS_DIR` at `examples/personas`/`examples/souls`
  (real repo fixtures), `CLONWAY_CHAT_GATEWAY_CONFIG` at a tmp JSON
  `{"roles": {"chat": {"provider": "openai_compatible", "model": "m", "base_url": "http://localhost:1"}}}`,
  `CLONWAY_CHAT_OPERATORS=owner@clonway.example`, `CLONWAY_CHAT_SEEN_FILE` in tmp_path — asserts
  the returned app answers `GET /healthz` → `200 OK` and a POSTed non-operator DM with `200 OK` +
  zero outbound calls (inject a recording opener seam; no network, no model call);
  `test_build_serve_app_fail_closed_on_gateway_problems` (config whose `api_key_env` is unset →
  raises/exits with the problems, never serves);
  `test_run_fake_repl_round_trip` — `run_fake(["hi milo"], ...)` (the `--fake` loop factored as a
  pure function over input lines) returns output containing the echo persona's reply and posts it
  through a `FakeChatTransport`, exercising the SAME `build_addon_app` app via an in-process POST.
- [ ] **Step 2 — RED**, **Step 3 — implement:**

```python
# build_serve_app (env-wired; verified signatures — builders: copy this shape)
colleagues = load_colleagues(Path(env["CLONWAY_CHAT_PERSONAS_DIR"]), Path(env["CLONWAY_CHAT_SOULS_DIR"]))
gateway = Gateway(GatewayConfig.from_dict(json.loads(Path(env["CLONWAY_CHAT_GATEWAY_CONFIG"]).read_text())))
role = env.get("CLONWAY_CHAT_ROLE", "chat")
problems = gateway.validate(roles=[role])
if problems:
    raise ChatAddonConfigError("; ".join(problems))  # fail-closed startup
seen = FileSeenStore(Path(env.get("CLONWAY_CHAT_SEEN_FILE", ".cockpit/chat-seen.txt")))
router = ChatRouter(
    registry=colleagues.registry,
    responder=gateway_responder(colleagues, gateway, role=role),
    transport=RestChatTransport(token_supplier=metadata_token_supplier),
    allowlist=load_allowlist(),
    already_handled=seen.__contains__,
    mark_handled=seen.add,
)
return build_addon_app(router, background=spawn_daemon_thread)
```

  `--fake`: inline `Persona.from_dict({"handle": "demo", "name": "Demo", "domain": "local dev"})`,
  echo responder, `FakeChatTransport`, `run_inline`; each stdin line → `fake_dm_envelope(line)` →
  in-process POST to the same app → print the posted replies. Zero Google, zero model.
- [ ] **Step 4 — verify:** `uv run pytest tests/test_chat_addon.py -q`; manual smoke:
  `echo "hi" | uv run python -m clonway_cockpit.chat_addon --fake` prints a reply.
- [ ] **Step 5 — commit:** `feat(chat-addon): env-wired serve entrypoint + local-dev fake REPL`

### Task 6 — docs, changelog, delivery table, full gates, RUNBOOK DELTA

**Files:** modify `docs/chat-transport.md` (add "The shipped edge" section: module API, env
contract, `--serve`/`--fake`, and fold the existing operator runbook steps around the new
entrypoint), `docs/persona-platform-architecture.md` (delivery table: add the row
`Chat add-on edge (deployable reference server: WSGI app, REST poster, durable dedup, local fake) — chat_addon.py | yes | yes | no | no | <this PR #>` — per the table's own update rule; do NOT
flip deployed/watched-working), `docs/persona-platform-go-live-plan.md` (Slice B: note the
framework edge is coded; remaining = worker/xbook wiring + operator deploy),
`CHANGELOG.md` (`## [Unreleased]` entry), and this plan (tick boxes, HANDOFF NOTES).

- [ ] Docs above updated; delivery-table row added in the same PR (the table's update rule).
- [ ] Full gates, run verbatim from repo root, paste output tails in the DONE comment (HR2):
  `make lint` · `make format` · `make typecheck` · `make test`
- [ ] Post the `RUNBOOK DELTA` comment on `hearth-care/auto-orchestrator#196` (new operator
  surface: `python -m clonway_cockpit.chat_addon --serve` env contract, `--fake` local check,
  deploy prerequisites below) and repeat it in the DONE comment (HR1).
- [ ] **Step 5 — commit:** `docs(chat-addon): shipped-edge docs, delivery-table row, changelog`

## OPERATOR TODO (not builder work; the edge is complete and testable without these)

1. Cloud Run: deploy a service running `python -m clonway_cockpit.chat_addon --serve` (or a worker
   image embedding it) with `--allow-unauthenticated`, region per fleet convention.
2. IAM: grant `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`
   `roles/run.invoker` on the service. **No** "Authentication Audience" configuration.
3. Add-on deployment manifest: declare the Chat message-receive trigger (the #1 "deployed but
   dead" cause — `docs/chat-transport.md` runbook step 4).
4. Set `CLONWAY_CHAT_OPERATORS`, persona/soul dirs, gateway config, seen-file path on the service.
5. Watch one real DM land and get a reply (delivery ladder: only then is Slice B
   *watched-working*; update the delivery table in that PR/note, not this one).

## Named follow-ups (out of scope here)

- Worker-template chat-edge scaffolding (`worker-template/` chat serve entry + template test).
- Milo-on-`xbook-server` wiring (repo `auto-bookkeeper`; uses this module unchanged).
- Live-deploy memory wiring: `remembering_responder` + mandatory dedup store (Slice C config).

## Self-Review

- Spec coverage: HTTP contract → Task 1; invariant cells 1–10, 12–13 → Task 2; cell 11 → Task 3;
  cell 15 (+14 failure-line) → Task 4; production wiring + fake → Task 5; docs/runbook/gates →
  Task 6.
- Safety invariants: 15-row cell table, each row names its test; idempotency key = `message.name`
  via durable `FileSeenStore`; partial-failure = mark-after-delivery, un-marked retry (HR3/HR4).
- Tests load-bearing: all assert HTTP status/body and `transport.posted` (rendered, observable
  output) and go red without the implementation (HR8); no substring-in-markup assertions.
- Wired end-to-end: every deliverable reaches `main()`/`build_serve_app` or the `--fake` REPL —
  no dead helpers (HR9).
- Snippets: signatures verified against `colleague.py` / `gateway/gateway.py` /
  `gateway/config.py` / `persona.py` / `group_chat.py` on `origin/main` @ `904e4ab`; constraints
  stated (body cap must exceed real envelope sizes), no magic paddings (HR10).
- Gates: `make lint` / `make format` / `make typecheck` / `make test`, verbatim (HR2).
- Operator-facing: yes → RUNBOOK DELTA task + OPERATOR TODO list (HR1).
- Dependencies: none unmerged; no wave tag (HR11).
- Deferred: the three named follow-ups + the operator deploy — none block this PR.

## HANDOFF NOTES

- Current phase: Task 3 complete; Task 4 not started.
- Next concrete step: Task 4 Step 1 (write the failing REST poster and metadata token tests).
- Decisions taken: stdlib-only edge; `background` required (no default); IAM+allowlist auth model
  (no JWT — binding); idempotency key = `message.name`; content-free logs. Task 1 groups the
  route-state cases into one test, so the narrow verification is `3 passed` rather than the
  plan's original `4 passed`. Task 2 RED failed at the missing `spawn_daemon_thread` import;
  GREEN verification was `uv run pytest tests/test_chat_addon.py -q` → `18 passed`. Task 3 RED
  failed at the missing `FileSeenStore` import; GREEN verification was
  `uv run pytest tests/test_chat_addon.py -q` → `20 passed`.
- Known failing tests: none.
- Dependencies/operator TODOs: see OPERATOR TODO above; nothing blocks the build.
