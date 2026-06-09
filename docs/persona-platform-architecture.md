# The persona platform — architecture

**Status:** living architecture-decision thread, opened 2026-06-08. The vision is settled; what
is *built* is not. The **Delivery** section at the end is the source of truth for what is
designed vs. coded vs. demonstrably working — read it before assuming any surface here exists.
**Scope:** the platform layer — *this* repo, `clonway-cockpit` — beneath the autoworker fleet.
The persona, the shared memory, the model gateway, and the group-chat transport live here so they
evolve once and reach every worker on a `rev` bump (the [consumption model](../CLAUDE.md)). The
workers (xbook/xhr/xletter/xquill/…) supply the domain toolkits; they do not each reinvent this.
**Companion docs:** [`persona-platform-getting-started.md`](persona-platform-getting-started.md)
(the operator on-ramp — what to use today + the pre-launch checklist),
[`persona-platform-go-live-plan.md`](persona-platform-go-live-plan.md) (the roadmap from local
demos to a live DM-able colleague — slices + risks),
[`agent-screen-model.md`](agent-screen-model.md) (the agent channel this drives through),
[`onboarding-a-worker.md`](onboarding-a-worker.md) (the Fleet Signal layer).

## The north star

Each autoworker becomes a **human-named colleague** — its own name, avatar, email, and voice —
that the owner reaches the way you reach a member of staff: a Chat DM, an email, or a message in a
shared group space. Behind every colleague sits a **real, discrete domain toolkit** (the worker's
repo, its TUI/CLI, its gated integrations) that already exists and is deterministic. The owner can
always step *behind* the persona and drive that toolkit's TUI/CLI directly — same capability, two
projections. That "one description, two projections" is this framework's founding thesis (see the
[agent screen model](agent-screen-model.md)); the persona platform extends it from *human-or-agent*
to *colleague-or-console*.

The unit of new capability is therefore a **hire**, not a feature branch. Adding a function to the
business means giving a toolkit a name, an avatar, and an email, and pointing them at it. The org
chart *is* the architecture.

## Three layers, kept strictly separate

The whole design holds together only if these never bleed into each other:

1. **Persona** — name, email, avatar, voice, and the memory of working with you. Thin,
   worker-agnostic, swappable. This is the *face*.
2. **Toolkit** — the real domain capability: the worker repo, its TUI + CLI, its integrations.
   Thick, per-worker, deterministic, gated, **already built**. This is the *hands*.
3. **Surface** — DM, email, group chat, TUI, CLI. Many surfaces front one persona+toolkit pair.

Two principles police the seams:

- **Hire the persona, not the program.** A new capability is a new hire — a name+avatar+email
  pointed at a toolkit — not a new monolith. Capabilities compose the way an org chart does.
- **The persona is the face; the toolkit is the hands.** A persona *routes to and narrates* its
  own deterministic tools. It does **not** free-form invent domain actions. The instant a persona
  starts *doing* the domain work itself instead of *calling its tools*, you have rebuilt the
  fragile generalist — the thing this architecture exists to avoid.

## No central router — a receptionist, not a GOD

The owner's strongest conviction here: **specialists stay in their own lanes, and there is no
single "sophisticated central router" that categorises an arbitrary message across N domains.** A
cross-domain classifier has to be flawless to be safe — one mis-categorisation drives the wrong
toolkit — and it grows more brittle with every worker added. That router was the **xops-chat
mistake** (a fleet-level entry point that had to understand everyone's domain; see
[Delivery](#delivery--agile-thin-slices-the-running-thread), slice 2 retires it).

The real-world model is simpler: you DM whoever owns the domain. If there is a front door at all,
it is a **receptionist that points** — "that's a bookkeeping one, talk to Milo" — never a **GOD
that does**. The distinction is the whole point:

| | Router (rejected as a front door) | Receptionist (accepted) |
|---|---|---|
| Job | categorise + execute across all domains | recognise + redirect |
| Failure mode | drives the *wrong* toolkit (acts wrongly) | mis-directs (says the wrong name) |
| Required quality | flawless | merely helpful |
| Robustness | fragile, worsens with scale | robust, degrades gracefully |

The natural receptionist is the **secretary** (Auto-Secretary / xquill) — the colleague who knows
who does what. Crucially, a receptionist's worst case is a wrong *suggestion*, which the owner
shrugs off; a router's worst case is a wrong *action*. We build the robust one.

### What we keep from WS-D, and what we drop

The merged WS-D conversational core (`clonway_cockpit/conversation.py`) already provides the
machinery a persona needs: the **trust boundary** (`OPERATOR` vs `QUOTED`), `Conversation.handle`
(route → resolve argv → drive the worker over `CockpitClient` → narrate), and the write-gate
routing to an `ApprovalPolicy`. **We keep all of that and instantiate it per-persona.** What we
drop is using its `Router` seam as a *fleet-wide* front door that classifies across every worker.
Per persona, the `Router` only ever interprets messages for **its own** domain (a narrow, robust
job) and its `launch` is pinned to **one** worker. The group-chat "is this mine?" gate (below) is a
cheap per-persona self-check, not a central dispatcher. Same code, inverted topology: many small
single-domain conversations instead of one omniscient router.

## Two-tier memory — "tell once, all learn", done safely

The value the owner wants: say a fact once and every relevant colleague knows it. The risk: shared
memory is shared blast radius. The resolution is two tiers plus a write boundary.

- **Shared company memory** — a CRM / staff handbook. It holds *facts about the shared world*: the
  **people** (residents, families, suppliers, staff), the calendar, and the owner's preferences
  (how to be addressed). Readable by **all** specialists. It deliberately does **not** hold domain
  *skills* — put skills in here and you have rebuilt the generalist blob one fact at a time.
- **Private per-persona working memory** — the bookkeeper's Xero notes, the marketer's campaign
  state. Each persona owns its own; nobody else reads it.

Both tiers use the same markdown-memory-plus-index pattern the framework and CLAUDE memory already
use (the [munder-difflin reference](#reference--munder-difflin) calls this the markdown-first
long-term memory + recall index, and we adopt that shape).

**The write trust-boundary is the load-bearing rule.** Only the **owner's** word — or a fact the
owner has confirmed — becomes shared truth. Anything an *outsider* said, or any *quoted/forwarded*
content, stays quarantined to the conversation that received it and is **never auto-promoted** to
shared memory. One poisoned fact — "the home's bank details have changed" — must not be able to
infect five agents at once. This is the same confused-deputy guard the WS-D trust boundary enforces
at the message edge (`OPERATOR` commands vs `QUOTED` data), lifted up to the memory-write edge.

## The group chat — distributed self-selection

The "buzz" of the office is a **Google Chat space** — the owner plus every persona in one room.
There is no gamified avatar-walking visualisation; Chat and Gmail *are* the office. (When we build
the transport, it is a Workspace add-on — see [The Chat transport](#the-chat-transport--a-workspace-add-on-not-a-classic-app).)

The space is what *dissolves* the router instead of reintroducing it. The owner asks the room a
general question; **each specialist independently answers the narrow, reliable question "is this
mine?"** and either volunteers or stays quiet. Nothing in the system needs a map of everyone's
domain — self-selection is distributed across the specialists who each only know their own lane.
Agents may also talk to each other.

Three traps to design against from the start:

- **Bot↔bot loops.** Personas are **quiet by default** — they speak only when addressed by the
  owner or when a task is clearly theirs — with turn caps to bound any exchange.
- **Cost.** A **cheap "is this mine?" gate runs before any full response**, so a roomful of
  colleagues isn't each paying for a full model turn on every message. (The [model gateway](#the-model-gateway--provider-agnostic)
  routes this gate to a cheap/local model.)
- **Trust in a multi-party room.** **Only the owner's messages are commands; everything an agent
  says is data.** An agent cannot be *talked into* a write by another agent — the `OPERATOR`/
  `QUOTED` boundary holds inside the group exactly as it does in a DM.

The division of labour: **the group is for standup, triage, and capturing shared facts; DMs are for
deep work.** Saying "call me Mr Page" or "this resident always pays late" in the space is the
natural "tell once" write to shared memory (subject to the owner-only write boundary above).

## The model gateway — provider-agnostic

A hard constraint, not a nicety: **no Anthropic lock-in.** Anthropic is moving subscription users
onto forced API rates, and a fleet of personas chatting all day is a real per-token cost. The
gateway is the answer and it is the **only chokepoint** through which every model call passes.

- **One thin port** in `clonway-cockpit`: `complete(messages) -> text` plus a structured-output
  variant. That is the entire interface the rest of the platform sees.
- **Interchangeable adapters** behind it: Anthropic, OpenAI/Codex, Gemini, MiniMax, local
  Ollama/vLLM.
- **Config maps role → provider/model.** The *gate* gets a cheap or local model, *chat* gets a
  cheap-but-good one, a *router/classifier* gets something like Haiku. Responding to a cost spike is
  an **edit to config + redeploy — no code change.**
- **Default adapter = LiteLLM** (OpenAI-shaped, 100+ providers, with cost/budget/fallback) — but
  **behind our own thin interface.** We do not trade Anthropic lock-in for LiteLLM lock-in; the
  OpenAI-compatible shape is the zero-dependency fallback if LiteLLM ever has to go.
- **The gateway owns cost.** Per-agent/per-day **cost caps + a circuit-breaker** (Milo already has
  a crude daily-call cap to fold in), and **per-call usage telemetry** emitted on every call.

Caveats we hold from the start: models are **not drop-in equal** (validate per model; routing and
the cheap "is this mine?" gate are the *safe* places to put cheap models — a wrong gate answer
mis-directs, it doesn't mis-act); tool-call and structured-output **formats differ** between
providers (the gateway normalises them); local hosting is the **cheapest tokens but the highest ops
cost**. Existing call sites migrate onto it: Milo's Haiku NL fallback, the WS-D router's LLM, the
weekly report.

The gateway also feeds two other layers directly: each **persona's `Router` seam** (the LLM that
interprets a DM) is injected from the gateway, and its **per-call usage telemetry** is what makes
model spend visible in xops (next section). Note that `clonway_cockpit/usage.py` today records only
*screen-open* counts — model-token telemetry is genuinely new and lands with the gateway.

## xops — the owner's oversight pane, not a router

Retiring xops-chat does not shrink xops; it **sharpens** it to the back-office view. xops is the
**owner's oversight pane** — fleet logs and cost — and explicitly **not** a conversational router
or a colleague. (For the same reason, **xops / Auto-Orchestrator gets no soul**: it is a dashboard,
not staff.)

There is a concrete gap the gateway closes. `xops.clonwaycare.co.uk`'s cost page
(`xops/web/routes/cost.py` → `signals.gcp_billing.fetch_daily_spend`) today shows **only GCP
billing per project** — infrastructure pounds. It structurally **cannot see model API spend**,
because Anthropic / OpenAI / Gemini bill *outside* GCP. So the cost of all this agent chatter is
currently **invisible**. The model gateway is the one chokepoint that can capture it: every call
emits usage, and xops surfaces a **second cost dimension** in the same pane — infra £ *and* model
£, broken down by worker/persona/model. That dependency is why the gateway is an early slice:
live-Milo and the cost dashboard both wait on it.

## Personas and souls

The personality mechanism already exists and has been watched working (see [Delivery](#delivery--agile-thin-slices-the-running-thread)).
Each worker's persona is a YAML config — `config/<persona>.yaml` with `persona_version`, `model`,
`tools`, and `system_prompt` — loaded by `xbook.agent.milo.load_config`. **The `system_prompt` *is*
the soul.** The loader already enforces required guardrail phrases, so personality can flavour the
voice but cannot override the guardrails. Structure each `system_prompt` as two layers:

- **Soul** (per worker, free, swappable) — the character. The starters below.
- **Constitution** (shared, mandatory, validated) — never fabricate · cite data freshness
  ("as of …") · the operator/quoted trust boundary · money-direction safety · internal-first tone.
  Every persona inherits this base; the soul sits on top, and the loader checks the base is present.

The principle: **personality lives in the face, not the hands.** A pernickety inspector and a
breezy marketer call the *same* gated deterministic tools — voice is pure presentation, near-zero
cost, and the persona (name + voice) is the identity that memory attaches to. Keep flair
**internal-first**: a "hard taskmaster" tone is fine for the owner, but the bar changes the moment a
persona faces an employee, a family, or a supplier.

Starter souls (drafts to refine — one per worker; the **CQC inspector is the owner's and kept
verbatim**):

| Persona / worker | Soul (starter) |
|---|---|
| **Milo** — bookkeeper (xbook / Auto-Bookkeeper) | Has a working soul in `config/milo.yaml` already (warm, precise-to-the-penny, "shall I also…"). **Keep it.** |
| **CQC inspector** — (xhr / Auto-Inspector) **[verbatim]** | "You are a meticulous, world-weary CQC inspector who's seen every failed inspection and trusts nothing until he's checked it twice. Pernickety about detail, sparing with praise, a hard taskmaster — but fair. You'd rather flag a small gap now than explain a big one to a regulator later." |
| **Marketer** — (xletter / Auto-Marketer) | "You are the marketer — fun, creative, a magpie for a good idea. Warm, upbeat, quick with an angle or a turn of phrase, allergic to dull copy. You bring energy — but you know the difference between flair and a promise the home can actually keep." |
| **Secretary** — (xquill / Auto-Secretary) *the receptionist* | "You are the office secretary — unflappable, organized, the one who knows who does what and where everything is. Friendly and efficient; when something isn't yours you point cleanly to whoever owns it ('that's one for Milo') rather than guess. You keep the diary, the threads, and the team tidy." |
| **Admissions** — (Auto-Admissions) | "You are the admissions lead — warm and reassuring with worried families, unhurried, but quietly rigorous about eligibility, funding, and the paperwork that has to be right before a placement." |

Seven to eight colleagues are intended; add more as workers gain personas. When we build the
persona slice, study `openclaw`'s `soul.md` persona file alongside munder-difflin's flair for
specific patterns.

## What exists, and what doesn't — the discipline

The governing rule on this project: **nothing is claimed to work until it has been watched
working.** Reading source proves code *exists*; a green Cloud Run revision proves infra is
*deployed*; neither proves the capability *runs end-to-end*. Four distinct claims, never conflated:
**exists in code → deployed → enabled → demonstrably working.** (This rule has its own memory and
is non-negotiable here — it was earned by twice over-claiming.)

Against that bar, as of 2026-06-08:

- **The conversational engine is watched working.** `xbook/agent/milo.py` (`run_turn`) is a real
  Claude tool-use loop with `ThreadMemory` multi-turn and a YAML persona. Driven locally
  (`Auto-Bookkeeper/milo_demo.py`) against real `claude-sonnet-4-6` with 14 tools, dry-run, it held
  a genuine 3-turn conversation — cash position (£41,820, fixture data), then bills due (none), then
  "schedule the urgent one" → it *remembered* there were none and explained when an approval card
  would appear. So the **engine** (multi-turn + tools + text + cards) is real and proven. The
  figures are `make_state()` fixtures, not live Xero, and it called `get_bills_due` seven times in
  one turn — rough edges, not blockers.
- **The Chat surface is not built.** xbook *also* has older per-worker bot code — "Milo" /
  `xbook-server`, `POST /chat/events`, nine read intents → Card V2, HMAC-signed approval-link
  writes — but `MILO_ENABLED` is **unset** in prod (the handler takes the legacy ack path) and there
  has been **zero `/chat/events` traffic** for seven days. Deployed, switched off, unused — **not a
  bot you can DM today.** Treat the conversational surface as **unbuilt** until watched working. The
  gap from the proven engine to a real DM is *production wiring* (`run_turn` → a server runner + a
  real model client = the gateway, `MILO_ENABLED` on, the add-on message trigger) — integration
  slices, not a rewrite.
- **The foundation is real and merged.** The WS-A/B/C/D gated-write + approval framework, the
  autonomy launcher, and the Milo audit digest are merged and FBA-hardened. That is what the
  persona platform builds *on*.
- **The persona platform's own spine is built, and the fleet wire is watched working (2026-06-09).**
  The model gateway (`complete`/`complete_structured`/`complete_tools` + telemetry), the persona
  identity + registry, the two-layer soul/constitution, the group-chat self-selection room, and
  the receptionist are all merged. The seams between them were FBA-hardened (PR #61). The missing
  piece — a reference `responder` that drives a *fleet* through the gateway, not just one
  hand-wired Milo — now exists as `clonway_cockpit.colleague.gateway_responder`, with
  `Colleague`/`load_colleagues` reconciling the identity (`.toml`) and soul (`.md`) reps into one
  "add a colleague" path. Driven live through a `GroupSpace` against a local Ollama
  (`qwen2.5:0.5b`), two colleagues (`@milo`, `@quill`) each self-selected, composed their **own**
  soul, and replied in voice through the gateway; per-call telemetry was recorded content-free.
  Still **not** built: the live Google Chat transport (a Workspace add-on — see below) and
  per-space multi-turn memory. The wire is proven; the production *surface* is the next slice.

Project: `clonway-care-bookkeeper`, region `europe-west2`.

## The Chat transport — a Workspace add-on, not a classic app

When the group-chat / DM transport slice arrives, build it as a **Google Workspace add-on**, the
way the rest of the fleet's Chat bots are built — **not** as a classic standalone HTTP Chat app.
The two models are materially different and getting it wrong has burned whole sessions before. The
working reference is **Auto-HR `xhr-server`** (`src/xhr/chat/`, `src/xhr/webhook/app.py:/chat-events`).
In brief:

1. **Auth is Cloud Run IAM, not an app-level token check.** The add-on invokes the endpoint as the
   add-on service agent (`service-<PROJECT_NUMBER>@gcp-sa-gsuiteaddons.iam.gserviceaccount.com`);
   grant it `roles/run.invoker`. The app does **no** JWT/audience verification — an audience pin
   *rejects* the real add-on traffic. Trust = the operator-email allowlist on `event.user.email`.
2. **The wire envelope is nested** (`{commonEventObject, chat:{messagePayload|buttonClickedPayload|
   …:{message,space,user}}}`), not the flat classic shape — normalise it.
3. **There is no "Authentication Audience" step** — that belongs to the classic model.
4. **An add-on only dispatches the triggers its deployment declares.** If it isn't configured to
   *receive messages*, DMs never reach Cloud Run — the #1 "deployed but dead" cause.
5. Services run `--allow-unauthenticated`; IAM invoker + the email allowlist are the gates.

Two known constraints to design for (carried from the WS-D backlog): each Chat DM is currently a
**fresh one-shot** conversation — per-space/thread session memory is needed for true multi-turn —
and Chat apps must reply **within ~30s**, so driving a cold worker needs a fast-ack + async
follow-up (or a bounded "still working…" reply).

## Reference — munder-difflin

`github.com/chaitanyagiri/munder-difflin` (shared by the owner). An office-cast of avatar agents
with markdown-first per-agent long-term memory, a semantic recall index, a memory reflector,
atomic-file mailboxes, and a cost circuit-breaker — agents are real `claude` PTY sessions on a local
Electron + Pixi office floor.

- **Steal:** the avatar/persona layer; the markdown-memory + recall + reflector pattern (same shape
  as ours); the mailboxes.
- **Diverge:** its agents are *faces on clones* (one generic `claude`, differentiated only
  visually) with a "GOD" supervisor (the router we reject) and full-autonomy sessions on a
  local-desktop Pixi viz. **We do faces on *specialists*, no GOD, gated deterministic toolkits, a
  Chat/Gmail surface, and no visualisation.**

## Delivery — agile thin slices (the running thread)

Agile, not waterfall. **One feature = one PR, with that feature's docs inside the same PR.** This
document is the running architecture-decision thread so nothing is lost between slices; build a
walking skeleton first, then thicken; **lock only the next slice** and re-plan after each. Work in a
worktree on a `claude/*` branch, gated PRs (ruff / format / mypy / pytest), squash-merge.

| # | Slice | Status |
|---|---|---|
| 1 | **Architecture design doc** (this document) | **DONE** (#48) |
| 2 | **Retire xops-chat** — the dead fleet-router service + its IAM + the `xops.converse` chat code | queued — needs the operator (Auto-Orchestrator PR #170 + the `xops-chat-retire.py` run) |
| 3 | **Model gateway** — the config-driven, cost-capped port + adapters | **DONE** (#49 port+telemetry, #52 fleet fan-in, #53 multimodal+caching, #54 LiteLLM adapter, #55 tool-use `complete_tools`) |
| 4 | **Shared-memory format + read** | **DONE** (#50 — `shared_memory.py`: handbook format + read/recall API) |
| 5 | **Milo reads shared memory** | **DONE** — the read/recall API (#50) + Milo's `recall_shared_memory` tool wired in xbook (#664) |
| 6 | **Governed write** (the owner-only trust boundary) | designed; **PR #51 open, parked on the owner** (not merged) |

**Built beyond the original locked horizon** (each its own PR + docs, FBA-hardened):

| Slice | Status |
|---|---|
| **Persona identity** (name / handle / domain / email / avatar / voice) — `persona.py` | **DONE** (#56) |
| **Soul + shared constitution** (the two-layer system prompt) — `persona_soul.py` | **DONE** (#59) |
| **Group-chat space** (distributed self-selection + orchestration + `GroupSpace`) — `group_chat.py` | **DONE** (#57, #58) |
| **Receptionist** (the front door that points, never does) — `receptionist.py` | **DONE** (#60) |
| **Seam-hardening** (the audit's cheap correctness/safety cluster: matcher, constitution check, mentions) | **DONE** (#61) |
| **The colleague wire** (`gateway_responder` + `load_colleagues` — a *fleet* converses persona → soul → gateway) — `colleague.py` | **DONE** (#62) |

Still ahead: **per-persona multi-turn memory**; the **live Google Chat transport** (a Workspace
add-on — the in-memory wire is proven, the production surface is not built); and **surfacing
model spend in the xops cost page** (the gateway already emits the telemetry). Each gets its own
slice, its own PR, and its own design note linked back here. **Lock only the next slice.**
