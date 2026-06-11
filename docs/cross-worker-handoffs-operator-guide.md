# Operator guide: cross-worker negotiation & handoffs

How to set up the fleet so workers negotiate cross-domain tasks themselves — instead of you
being the switchboard. Companion to [`cross-worker-handoffs.md`](cross-worker-handoffs.md) (the
framework reference) and the design spec
[`superpowers/specs/2026-06-10-cross-worker-handoffs-design.md`](superpowers/specs/2026-06-10-cross-worker-handoffs-design.md)
(invariants S1–S12, dragons D1–D20). Sits alongside the platform on-ramp
[`persona-platform-getting-started.md`](persona-platform-getting-started.md) and the Chat deploy
runbook [`chat-transport.md`](chat-transport.md).

## Status — read this first

Against the repo's four-rung ladder (**designed → coded → deployed → watched-working**):

- The negotiation framework (`handoff.py`, `reflex.py`, `negotiation.py`) is **coded** — merged,
  gated, 46 tests, runs end-to-end **headlessly** (the acceptance test drives the whole worked
  example over an in-memory transport).
- It is **not watched-working** on a live Chat space yet. Two things are deliberately left to the
  worker/operator edge: (1) the **live Google Chat add-on deploy** (shared with the transport
  slice — see [`chat-transport.md`](chat-transport.md)), and (2) **each worker registering its own
  `ReflexRule`s** in its repo. Until both are done, this runs locally/headlessly but no real DM
  triggers it.

So: everything in §1–§5 you can wire and run today (locally, or in tests). §6 is the live deploy,
which carries the same "deployed-but-dead" hazards as any Workspace add-on.

## The mental model in one paragraph

There is **one shared Google Chat space** — you plus every persona, in one room. That room *is*
the channel; the negotiation rides the ordinary chat, it does not add a second bus. When a
worker's domain code detects a cross-domain consequence (xhr: "right-to-work failed for employee
402, payroll should hold"), it posts a **handoff notice** into the room addressed at the persona
who owns the consequence (`@milo`). That persona's own pre-registered **reflex** may take a
*blocking-only* protective action immediately (hold the payroll run), and the model decides the
rest (accept / decline-and-redirect / defer). Everything that needs you converges into a single
**unified plan** posted in the room for your approval. You stop being the router; you supervise
outcomes. The air-gap is intact throughout: **only your messages are commands** — nothing an
agent says can *instruct* another agent to act.

```
xhr domain code detects RTW failure
      │ composes a notice envelope, posts it into the room  ─────────────►  THE GROUP CHAT SPACE
      ▼                                                                     (you + every persona)
  @milo's reflex: hold payroll (blocking-only, through milo's own gate)  ◄─ everyone self-selects
      │ remaining asks negotiated (model: accept / decline+redirect / defer)
      ▼
  unified plan posted for YOU — each step still rides the normal approval gate
```

---

## 1. The channel — one room, owner-gated

All personas speak in a single `space_id` (a Google Chat space id like `spaces/AAAAxxxx`). The
same room the persona platform already uses for standup/triage — see
[`group-chat.md`](group-chat.md). The negotiation protocol is just typed messages in it.

**Who counts as "the owner" is set by one env var.** A message becomes a *command* (`is_owner=True`)
only if its sender email is on the operator allowlist — `chat_transport.py:to_chat_message` →
`is_operator`:

```
CLONWAY_CHAT_OPERATORS="alice@clonwaycare.co.uk,bob@clonwaycare.co.uk"
```

Comma-separated, lower-cased, stripped. **Unset or empty ⇒ no one is trusted (fail-closed).** This
is the air-gap edge: every persona reply, every handoff envelope, every reflex audit, every plan
is *data*; only an allowlisted human's words are commands. Nothing in this feature reads
`is_owner` to authorize an action — confirm it stays that way.

DMs vs the room: in a **DM** only the owner draws a reply; in a **named room** all personas
self-select. Cross-worker negotiation is a **room** behaviour (a notice needs a recipient persona
that others can see), so run it in the shared space, not in DMs.

---

## 2. Config you must set up

### 2a. The model gateway (`role → model`)

Every model call goes through the gateway; provider/model is config, not code (see
[`model-gateway.md`](model-gateway.md)). Write a `GatewayConfig` dict with the roles this feature
uses. **The negotiation decision call uses its own role** (pass whatever role string you like to
`negotiating_responder(role=...)`; `"negotiate"` is the convention).

```python
from pathlib import Path
from clonway_cockpit.gateway.config import GatewayConfig
from clonway_cockpit.gateway.gateway import Gateway

CONFIG = {
    "roles": {
        # conversational replies in the room (the "inner" responder)
        "chat":      {"provider": "litellm", "model": "anthropic/claude-haiku-4-5",
                      "api_key_env": "ANTHROPIC_API_KEY", "params": {"temperature": 0.2}},
        # the cheap "is this mine?" gate (optional; can be local)
        "gate":      {"provider": "openai_compatible", "base_url": "http://localhost:11434/v1",
                      "model": "llama3.1", "api_key_env": None},
        # the per-ask accept/decline/defer decision in a handoff (structured output)
        "negotiate": {"provider": "litellm", "model": "anthropic/claude-haiku-4-5",
                      "api_key_env": "ANTHROPIC_API_KEY", "params": {"temperature": 0.0}},
    },
    "pricing": {  # optional, drives cost telemetry only
        "anthropic/claude-haiku-4-5": {"prompt": 1.0, "completion": 5.0},
    },
}

gateway = Gateway(GatewayConfig.from_dict(CONFIG), telemetry_base=Path(".cockpit/telemetry"))
```

Notes:
- A role's `api_key_env` names the env var holding its key (`None` for keyless/local). The key is
  read at call time; a missing key raises `GatewayError` for that role only.
- The **dev default is a toy** (`qwen2.5:0.5b`). The single most impactful change is pointing
  `chat`/`negotiate` at a real model (e.g. Haiku) — the negotiation decisions are only as good as
  the model behind them. A wrong decision is contained (it just mis-labels an ask in a plan you
  approve), never a wrong *action*, but a real model makes the room actually useful.
- The same `Gateway` instance satisfies both the plain `complete` (for `chat`) and
  `complete_structured` (for `negotiate`) — pass it to both layers.

### 2b. Personas + souls (the colleagues)

Each colleague is a `<handle>.toml` (identity) paired with a `<handle>.md` (soul) by filename.
`load_colleagues(personas_dir, souls_dir)` pairs them; a `.toml` with no matching `.md` raises.
See worked examples in [`examples/personas/`](../examples/personas) and
[`examples/souls/`](../examples/souls) (`milo`, `quill`).

`<handle>.toml` — required `handle`, `name`, `domain`; optional `email`, `avatar_ref`, `voice`:

```toml
handle = "milo"
name = "Milo Garth"
domain = "the books — invoicing, payroll, cash and reconciliation"
email = "milo@clonwaycare.co.uk"
avatar_ref = "🧮"
voice = "warm, precise to the penny"
```

`<handle>.md` — the soul (free-form character). It is stacked on the **shared constitution** by
`compose_system_prompt`, which validates the constitution still carries every required guardrail
phrase (`persona_soul.REQUIRED_PHRASES`): `never fabricate`, `cite their freshness`,
`owner's words are commands`, `approval`, `internal-first`. You write the *soul*; the constitution
is appended automatically — you do not (and cannot quietly) edit those guardrails away.

The `domain` line is load-bearing: it feeds the cheap "is this mine?" self-selection gate, so make
it specific (what this colleague actually owns), not a job title.

```python
from pathlib import Path
from clonway_cockpit.colleague import load_colleagues

colleagues = load_colleagues(Path("personas"), Path("souls"))
```

### 2c. The operator allowlist

`CLONWAY_CHAT_OPERATORS` (see §1). Without it, every message is data and nothing the owner says is
ever a command — the room is inert by design.

### 2d. A memory root

Per-persona working memory + per-thread transcripts live under one base dir you choose
(`PersonaMemory(memory_base, handle)`); isolation is by handle. Reflex idempotency notes live here
too, so it should be **durable** (survives restart) for the idempotency guarantee to hold across a
process bounce.

```python
MEM = Path(".cockpit/memory")
```

---

## 3. Wire the responder

A "responder" is `(Persona, ChatMessage) -> str | None`. You compose three layers, inside-out:

1. an **inner** plain-chat responder (`gateway_responder`, or `remembering_responder` for
   per-thread memory),
2. wrapped by **`negotiating_responder`**, which owns handoff envelopes,
3. injected into the space.

```python
from clonway_cockpit.chat_memory import remembering_responder
from clonway_cockpit.negotiation import negotiating_responder

inner = remembering_responder(colleagues, gateway, role="chat", memory_base=MEM)

responder = negotiating_responder(
    inner,                       # ordinary chat falls through to this, untouched
    colleagues,
    gateway,                     # the StructuredCompleter for the decision call
    role="negotiate",            # the gateway role for per-ask decisions
    memory_base=MEM,
    reflex_kits=reflex_kits,     # handle -> ReflexKit (see §5); None disables reflexes
)
```

What `negotiating_responder` does (so you know what you're turning on): an ordinary message goes
straight to `inner`. A message carrying a handoff envelope is **fully owned** by this layer — it
fires the recipient's reflexes (code, before any model call), asks the model for per-ask decisions
via `complete_structured`, **reconciles them in code**, records the task in memory, and replies
with a code-composed `response` envelope (or stays silent). The model never authors an envelope and
its raw output never reaches the wire unreconciled. Forged frames (envelope `origin` ≠ transport
sender), plans, and responses addressed elsewhere are inert.

---

## 4. Run it in the room — `NegotiatedSpace`

`NegotiatedSpace` wraps the platform's `GroupSpace` and adds the after-round **sweep** (post the
unified plan for resolved tasks; escalate unresolved ones to you once).

```python
from clonway_cockpit.negotiation import NegotiatedSpace

space = NegotiatedSpace(
    space_id="spaces/AAAAxxxx",            # the shared Google Chat space id
    registry=colleagues.registry,
    transport=transport,                   # your Chat REST poster (or FakeChatTransport in tests)
    responder=responder,
    owner_line="@alice",                   # how a stall notice addresses you
    max_persona_turns=6,                   # loop-guard for agent↔agent chatter
)
```

- `space.owner_says(text)` — you post; personas self-select and the sweep runs.
- `space.post_notice(handle, env, say="")` — **origin-side** entry point: a worker's domain code
  composes a `notice` envelope and posts it as that persona. Asserts `env.origin == handle`.
- `address_notice(text, registry)` — sender-side helper: the receptionist *points* at the handle
  that owns some text (returns `None` if ambiguous, so the worker can fall back to asking you).

After every round the sweep posts a `plan` envelope for any newly-resolved task that has something
for you, and **one** prose stall notice per task still unresolved at the turn cap. The plan
**authorizes nothing** — every step still executes through the normal approval gate.

A complete, runnable trace of all of this (notice → reflex hold → redirect → accept → plan) is the
acceptance test `tests/test_negotiation_drive.py::test_worked_example_end_to_end` — read it as the
executable reference, and adapt [`examples/group_space_demo.py`](../examples/group_space_demo.py)
to drive a `NegotiatedSpace` locally.

---

## 5. Give a worker reflexes (per-worker, in the worker repo)

A **reflex** is a worker's own pre-registered, **blocking-only** rule that may react to an
agent-claimed fact without waiting for you — hold payroll, pause a send, flag a record. **Never**
money-moving, never releasing a hold, never deleting. The worst case of a poisoned claim is
over-caution you can lift. This is the one place the air-gap is relaxed, and only in the
safe direction: the trigger is *the receiving worker's own rule firing on data it heard*, never the
other agent commanding it.

The reflex is an `ApprovalPolicy`, **not a new write path** — it is consumed at the worker's
existing `confirm_apply` gate, exactly like `AllowlistPolicy`.

```python
from clonway_cockpit.private_memory import PersonaMemory
from clonway_cockpit.reflex import ReflexBank, ReflexRule, ReflexLog, ReflexPolicy, ReflexKit

def hold_matcher(env):
    # PURE + deterministic — no model call. Return the exact ask text to act on, or None.
    return next((a for a in env.asks if "hold" in a.lower() and "payroll" in a.lower()), None)

def run_hold(proposal):
    # The worker's gated executor. `proposal` is built by the framework with the direction
    # HARD-CODED (blocking=True, money_movement=False) and provenance taken ONLY from a fact
    # claimed by the notice's origin. Present it at THIS worker's own write gate, drive the
    # BLOCKING action (set a hold flag on the payroll run), and return True iff it actually applied.
    return my_payroll_toolkit.hold(proposal["task_id"])  # -> bool

bank = ReflexBank()
bank.register(ReflexRule(
    capability_key="payroll.hold",          # non-empty, unique per bank
    description="hold a payroll run pending review",
    matcher=hold_matcher,
    run=run_hold,
))

milo_mem = PersonaMemory(MEM, "milo")
log = ReflexLog(milo_mem)                    # persisted -> idempotent across restart
policy = ReflexPolicy(bank.keys(), log, max_applies=5)   # optional per-session cap
milo_kit = ReflexKit(bank=bank, policy=policy, log=log)

reflex_kits = {"milo": milo_kit}            # handle -> ReflexKit, passed to negotiating_responder
```

The policy refuses unless **all** hold: registered capability, `money_movement is False`,
`blocking is True`, non-empty provenance from a fact the origin itself claimed, a safe `task_id`,
not already applied for `(task_id, capability_key)`, and under the cap. An already-applied reflex is
*reported* ("previously applied") rather than re-run, so a redelivered message still posts a true
audit and never double-holds. A `run` that raises is caught and reported `applied=False` — it never
crashes the room.

**Design discipline for whoever writes a `ReflexRule`:** every rule lands in a worker PR and is
reviewed as a safety change. If you cannot say "the worst case of this firing on a false claim is an
over-cautious hold the owner lifts in seconds," it is not a reflex — make it a plan step instead.

Workers with no kit simply have no reflexes; the negotiation still works (everything goes to the
model decision + the plan).

---

## 6. Go live — the Chat add-on deploy (the deferred half)

Everything above runs locally/headlessly today. To make a real message in a real Google Chat space
trigger it, you deploy the persona Chat transport as a **Google Workspace add-on** (NOT a classic
HTTP Chat app — the two are materially different and conflating them has burned sessions). The full
runbook is [`chat-transport.md`](chat-transport.md) → "Operator deploy runbook"; the load-bearing
points:

1. **Cloud Run service, `--allow-unauthenticated`.** The gates are IAM invoker + the email
   allowlist, **not** an app-level token. Pin the fleet region.
2. **Grant the add-on service agent `roles/run.invoker`** on the service:
   `service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`. Without it the add-on
   can't invoke the endpoint.
3. **No "Authentication Audience" / JWT `aud` pin.** That's the classic model and *rejects* real
   add-on traffic. Trust = Cloud Run invoker IAM + `CLONWAY_CHAT_OPERATORS`.
4. **Declare the message-receive trigger** in the add-on deployment. If it isn't configured to
   receive messages, messages never reach Cloud Run — the #1 "deployed but dead" cause. Mirror the
   proven Auto-HR `xhr-server` manifest (`src/xhr/chat/`).
5. **Set `CLONWAY_CHAT_OPERATORS`** in the service env (§1/§2c).
6. **Wire the worker edge:** the worker's `/chat-events` route normalizes the event, builds the
   `ChatRouter`/`NegotiatedSpace` with the §3 responder, fast-acks within ~30 s, and posts replies
   asynchronously via its Chat REST poster. Inject the redelivery dedup hooks
   (`already_handled`/`mark_handled` over a durable store) per [`thread-memory.md`](thread-memory.md)
   — at-least-once delivery will otherwise double-record turns.

The negotiation framework needs **no** change for this; it's already injected through the same
`responder`/`transport` seams the live edge uses.

---

## Pre-flight checklist

- [ ] `CLONWAY_CHAT_OPERATORS` set to the real operator email(s); confirmed empty ⇒ inert.
- [ ] Gateway `chat` and `negotiate` roles point at a real model (not the `qwen2.5:0.5b` toy);
      API-key env vars present.
- [ ] `personas/` + `souls/` paired; every soul composes (constitution phrases intact); domains are
      specific.
- [ ] Durable `memory_base` chosen (reflex idempotency depends on it surviving restart).
- [ ] Responder composed: `negotiating_responder(remembering_responder(...), …, reflex_kits=…)`.
- [ ] `NegotiatedSpace` constructed with the real `space_id`, the registry, the Chat poster
      transport, and your `owner_line`.
- [ ] Each worker that should auto-protect has registered its blocking-only `ReflexRule`s (reviewed
      as safety changes) and they're mapped `handle -> ReflexKit`.
- [ ] (Live) Chat add-on deployed per §6: invoker IAM granted, message trigger declared, no audience
      pin, dedup hooks wired.
- [ ] Smoke: drive `tests/test_negotiation_drive.py::test_worked_example_end_to_end` green, then a
      real notice in the room produces a reflex hold + a unified plan addressed to you.

## What this does **not** do (v1)

Open un-addressed offers (every notice names a recipient); model-assisted reflex matchers (matchers
are deterministic); cross-session ledger persistence (the task ledger is per-process); verifiable
provenance (a provenance string is an audit pointer, not proof — the blocking-only direction is what
bounds a false claim); and Chat *card* rendering of envelopes (they render as text). See the design
spec's "Deferred" section before building any of these.
