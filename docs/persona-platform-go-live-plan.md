# Persona platform — what it takes to go live

Companion to [`persona-platform-architecture.md`](persona-platform-architecture.md) (the what/why)
and [`persona-platform-getting-started.md`](persona-platform-getting-started.md) (what's usable
today). This is the **roadmap from "works on a laptop" to "a live, DM-able AI colleague"** —
grounded in the current code/infra state, not aspiration. Per-slice specs + TDD plans live under
[`docs/superpowers/`](superpowers/).

## The one-line truth

The conversational **engine is already proven** — Milo's `run_turn` tool-use loop, the persona /
soul / group-chat / receptionist libraries, the gateway on Haiku in prod. What's missing is
**production wiring + one genuinely-new build (the Google Chat transport)** — and, for the *fleet*
specifically, a deeper prerequisite: each colleague needs a real toolkit. So this is mostly
integration slices, with one real build and one open-ended program.

## The keystone

**The Google Chat transport (a Workspace add-on).** Nothing goes green without it — it's the
surface that lets you DM a colleague and get a reply. The framework reference edge is now coded in
`clonway_cockpit.chat_addon` (`python -m clonway_cockpit.chat_addon --serve`, plus `--fake` for local
checks), but the worker/server wiring and operator deployment are still not watched-working. The
architecture doc's [Chat-transport section](persona-platform-architecture.md) has the recipe
(modelled on Auto-HR's `xhr-server`): Cloud Run IAM auth (not an app token), the nested event
envelope, the **message-receive trigger must be declared in the add-on deployment** (the #1
"deployed but dead" cause), and a ~30s reply window that forces a fast-ack + async-follow-up pattern.

## Two tracks — NOT the same size

- **Milo-first (contained):** make ONE colleague — Milo — a real, DM-able AI bookkeeper on live
  data. Milo is the *only* persona with a real toolkit today, so this is achievable and is the
  genuine "wow".
- **The fleet (open-ended):** the group chat with many personas self-selecting and *doing* things.
  Gated on a hard prerequisite — **each persona needs a real worker/toolkit to be useful**, and
  most don't exist yet. A persona with no toolkit can chat but can't act — the exact "fragile
  generalist" the architecture rejects. So the group chat is a *program*, not a slice.

## The slices

### Slice A — Milo on live data (kills the "fixture figures" caveat)
- **Does:** wire `run_turn`'s `ctx_factory` to the real synced state (Xero/Lloyds) instead of
  `make_state()` fixtures. The job already syncs real state; Milo reads from it.
- **Greens:** upgrades the local Milo demo from "real model, fake numbers" to "real model, real
  books" — provable locally *before* any transport exists.
- **Takes:** an integration PR + a watched run. Low risk; no new infra. **The recommended first
  green.**

### Slice B — The Google Chat transport (the keystone build)
- **Does:** use the coded framework edge (`chat_addon.py`) to expose `/chat-events`; wire the
  worker/xbook responder to Milo's `run_turn`; IAM auth + operator-email allowlist; fast-ack +
  async follow-up for the 30s window; declare the message-receive trigger; flip it on. Lands on the
  existing `xbook-server`.
- **Greens:** you can DM Milo from Chat/your phone and he answers about the real books.
- **Takes:** remaining worker integration plus operator deployment. Reference: Auto-HR `xhr-server`
  + the architecture transport section. Highest-risk slice until a real DM is watched landing.

### Slice C — Per-space session memory (true multi-turn) — **in review (#79)**
- **Does:** persist a transcript keyed by Chat space/thread, so a conversation remembers across
  messages instead of each DM being a fresh one-shot.
- **Greens:** makes Milo feel like a colleague, not a stateless Q&A box.
- **Status:** the framework wiring is built — `chat_memory.py` (`remembering_responder` +
  `ThreadTranscript` over the merged #77 store), in review as #79 ([`thread-memory.md`](thread-memory.md)).
  Remaining before it's *watched-working*: the live transport deploy (Slice B) wiring in
  `remembering_responder` + its dedup hooks, and a worker pin bump.

### Slice D — The group chat, live (the fleet) — a PROGRAM, not a slice
- **Does:** a real `ChatTransport` backed by the Chat API (the framework has the Protocol +
  `FakeChatTransport`); a `GroupSpace` wired to a real Chat space with the colleague registry +
  `gateway_responder`; the receptionist front door.
- **Gated on:** each colleague having a real toolkit. With only Milo today, the honest first version
  is "Milo + face-only personas that route/redirect but don't act" — useful as a receptionist demo,
  but the full vision needs more workers built, each its own project. **Scope explicitly before
  starting.**

### Slice E — Production hardening (before unsupervised trust)
- Soul/constitution enforced in the live path (it is, via `gateway_responder` — verify end-to-end);
  the owner-only-command air-gap live; per-agent/per-day **cost caps + circuit-breaker** on the
  gateway; xops surfacing chat activity + model spend; the approval-card write gate verified
  end-to-end through the chat flow on real data.

## The honest risks / unknowns

1. **The transport is the keystone and historically painful** — but there's a working in-family
   reference (Auto-HR). De-risk by copying that shape exactly.
2. **The fleet is gated on toolkits.** "Personas conversing and *doing* things" is a much bigger
   lift than "DM Milo" — it scales with the number of real workers, most of which don't exist.
3. **The 30s Chat reply window vs cold-start + a multi-turn tool loop** → must fast-ack then
   follow up async, or replies time out.
4. **Live data + real writes** → the approval gate must hold inside the chat flow. Structural, but
   verify it on real data, not fixtures.

## Recommended path

Do **A → B → C for Milo only**. That gets you a real, DM-able AI bookkeeper colleague on live
books — the genuine demo — and it's contained precisely because Milo is the one colleague with a
real toolkit. Treat **D (the fleet)** as a separate, explicitly-scoped program you start only after
deciding how many real colleagues you're willing to build. **E** rides alongside B–D.

So: the "DM an AI colleague" demo goes green with **A + B (+ C)** — a finite, mostly-wiring effort
with one real build. The group-chat demos go green with **D**, which is open-ended and depends on
building more workers, not just wiring.
