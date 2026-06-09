# Getting started: using the persona platform

The operator's on-ramp — what you can use today, the one change that makes it good, and the
pre-launch checklist. Companion to [`persona-platform-architecture.md`](persona-platform-architecture.md)
(the what/why) and the per-module docs ([`personas.md`](personas.md),
[`group-chat.md`](group-chat.md), [`receptionist.md`](receptionist.md),
[`model-gateway.md`](model-gateway.md)). _Status verified against `main` on 2026-06-09._

## The honest status — read this first

Two different things have been built, at two different levels of "done":

1. **The bookkeeping cockpit + the daily digest** (in the xbook worker) — real, mature, in use.
   `xbook` reads live Xero / Lloyds / occupancy through deterministic, gated tools, and the
   chat→actions digest already runs on a schedule. This is the product; you can use it today.
2. **The persona platform** (this repo — model gateway, personas, souls, group chat,
   receptionist, the colleague wire) — **correct, tested libraries plus local demos, _not_ a
   deployed product.** Each piece has been watched working in isolation (including a real model
   via local Ollama), but nothing is wired to a live surface.

**The single most useful change you can make is to switch the model gateway off the
dev-quality local default (`qwen2.5:0.5b`) onto a real model (e.g. Haiku).** Today the
classifiers misclassify and a persona can't really hold a conversation — not because the code
is wrong, but because the default model is a toy. One config change fixes that across the board.

**The one genuinely-unbuilt piece** between "works on my machine" and "I can DM my colleague
from my phone" is the **live Google Chat transport** (a Workspace add-on). It's a real build,
and the one that's been paused. Everything below works _locally_ without it.

## What you can actually use today

| Thing | How to run it | State |
|---|---|---|
| **Daily chat→actions digest** | scheduled (xbook-server) | **Live** — confirm in xops; nothing to do |
| **Bookkeeping cockpit** (gap, forecast, code-gap, watchdog, …) | `uv run xbook <command>` | **Use now** — production-grade, real data, gated writes |
| **Milo, conversational** (multi-turn, tools, approval cards) | `python milo_demo.py` in Auto-Bookkeeper (needs `ANTHROPIC_API_KEY` in `.env`) | **Local demo only** — proven engine, but figures are fixtures and it is **not** a deployed bot (`run_turn` has no live caller; `MILO_ENABLED` off) |
| **Persona group chat / receptionist** | `uv run python examples/fleet_chat_demo.py` (this repo) | **Local demo only** — no Chat transport; runs headless or against local Ollama |
| **Receptionist · souls · colleague wire · seam-fixes** | — | **In this repo only** — xbook pins cockpit at `a75f7a0`, which predates them; needs a rev bump to reach xbook |

## Recommended next steps, in order

1. **Switch the gateway onto a real model.** The highest-leverage single action — it turns the
   dev-quality classifiers and a mute persona into something worth using. See checklist §A; the
   full recipe is in xbook's `docs/model-gateway.md`.
2. **Talk to Milo locally.** With a real model and `ANTHROPIC_API_KEY` set, `python milo_demo.py`
   gives a genuine multi-turn bookkeeping conversation (dry-run, no writes). This is the most
   mature part of the persona work — use it to decide whether a live colleague is worth wiring.
3. **Keep using the cockpit + digest.** They're already the real product; nothing here changes
   them.
4. **Try the persona group chat locally** (`examples/fleet_chat_demo.py`), then decide if the
   live Chat surface is worth the one paused build (checklist §C).

## Pre-launch operator checklist — the things only you can do

### A. To make it _good_ (do this first — small, high-impact)
- [ ] **Pick a real model and get its API key** (e.g. Anthropic Haiku → `ANTHROPIC_API_KEY`).
- [ ] **Make the DPA call.** Hosting model calls sends care-home PII (email bodies, invoice text)
      to a third party — a data processor under GDPR Art. 28. Only once a DPA is in place, set
      `XBOOK_ALLOW_HOSTED_PII=1` (the gateway **fails closed** without it — that's by design).
- [ ] **Install the adapter + point the roles at the model:** `uv add 'clonway-cockpit[litellm]'`,
      then edit xbook's `config/models.yaml` (set `chat_intent` / `inbox_classify` /
      `ledger_period` to `provider: litellm`, `model: anthropic/claude-haiku-4-5`,
      `api_key_env: ANTHROPIC_API_KEY`) and uncomment the `pricing:` block so spend is recorded.
- [ ] **Verify:** `uv run xbook doctor` surfaces the configured backend and warns on an un-gated
      hosted role.

### B. To clear the parked work (two PRs waiting on you)
- [ ] **clonway-cockpit PR #51** — governed-write (owner-only trust boundary). Review and merge,
      or close.
- [ ] **Auto-Orchestrator PR #170** — retire the dead xops-chat router. Merge, then run
      `~/Developer/xops-chat-retire.py` (it prints each command and confirms before any
      prod-mutating step).
- [ ] **xops cost consumer (#171 area)** — so the model spend the gateway now records shows up on
      the xops cost page alongside infra spend (the xbook producer side is already wired).

### C. To actually _go live_ with personas/Milo (the build you paused)
- [ ] **Bump xbook's cockpit pin** `a75f7a0` → latest so the receptionist, souls, colleague wire,
      and the seam-fixes reach xbook — they're cockpit-only today.
- [ ] **Build the Google Chat transport** (a Workspace add-on, modelled on Auto-HR's `xhr-server`;
      see the architecture doc's "The Chat transport" section). The one genuinely-missing piece —
      a real build, not a flag flip.
- [ ] **Wire Milo to a live surface:** give `run_turn` a server entry point, then flip
      `MILO_GATEWAY_ENABLED=1` against the real (tool-capable) model. The code already warns if
      you point it at a model that can't tool-call.

## Bottom line

You can **use the bookkeeping cockpit and the digest now**, and **drive Milo + the personas
locally now** — and the one thing that makes all of it _good_ rather than proof-of-concept is
checklist §A (a real model). Everything in §C is the deferred "go live as a DM-able colleague"
work; none of it is required to start getting value today.
