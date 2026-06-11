# Getting started: using the persona platform

The operator's on-ramp — what you can use today, the one change that makes it good, and the
pre-launch checklist. Companion to [`persona-platform-architecture.md`](persona-platform-architecture.md)
(the what/why) and the per-module docs ([`personas.md`](personas.md),
[`group-chat.md`](group-chat.md), [`receptionist.md`](receptionist.md),
[`model-gateway.md`](model-gateway.md)). _Status verified against this repo's `main` and fetched
sibling repo `origin/main` refs on 2026-06-09._

## Current status — read this first

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
| **Milo, conversational** (multi-turn, tools, approval cards) | `python milo_demo.py` in Auto-Bookkeeper (needs `ANTHROPIC_API_KEY` in `.env`) | **Local / flag-gated only** — proven engine and xbook server seams exist, but this repo has not watched a deployed persona Chat surface; live-data and Chat-transport slices remain separate |
| **Persona group chat / receptionist** | `uv run python examples/fleet_chat_demo.py` (this repo) | **Local demo only** — no Chat transport; runs headless or against local Ollama |
| **Cross-worker negotiation & handoffs** (workers hand tasks off + take blocking-only reflex actions) | wire per the [operator guide](cross-worker-handoffs-operator-guide.md); drive `tests/test_negotiation_drive.py` | **Coded, runs headless** — not watched-working until the live Chat transport carries it |
| **Receptionist · souls · colleague wire · seam-fixes** | — | **In this repo** — consumers inherit them only after a cockpit rev bump |

## Fleet adoption matrix

_Observed from fetched sibling repo `origin/main` refs on 2026-06-09. This is repo state, not a
production traffic claim._

| Worker | Repo | Package | Cockpit pin | Agent channel | Platform adoption note |
|---|---|---|---|---|---|
| Bookkeeper | Auto-Bookkeeper | `xbook` | `a75f7a02e9da214d6eb55cd6b6f444d03251b114` | `xbook --agent-stdio` + `--allow-apply` | Has xbook Chat bot, model gateway config, Milo gateway/shared-memory work; needs pin rollout for newest cockpit platform slices |
| Orchestrator | Auto-Orchestrator | `xops` | `200493cc77d4c3aa0bcb2a8d27ae1cc7f198a259` | `xops bridge --agent-stdio` | Drives workers via `CockpitClient`; oversight pane, not a persona |
| HR | Auto-HR | `xhr` | `21d68b3527fb37f6f6082324643cc68cf9cd11de` | `xhr --agent-stdio` + `--allow-apply` | Strong cockpit adoption; no live persona surface observed |
| Marketer | Auto-Marketer | `xletter` | `991b639e2f9d89544f831604c1419a03c877dd8f` | No `--agent-stdio` marker observed | Has Google Chat intake and model gateway telemetry; not yet a cockpit/persona adoption proof |
| Secretary | Auto-Secretary | `xquill` | `21597f4` | No `--agent-stdio` marker observed | Has its own live Milo forward-concierge and Chat digest; not this platform's cockpit/persona path |
| Admissions | Auto-Admissions | `xadmissions` | none observed | No `--agent-stdio` marker observed | Early worker; no cockpit pin observed |

## Recommended next steps, in order

1. **Switch the gateway onto a real model.** The highest-leverage single action — it turns the
   dev-quality classifiers and a mute persona into something worth using. See checklist §A; the
   full recipe is in xbook's `docs/model-gateway.md`.
2. **Talk to Milo locally.** With a real model and `ANTHROPIC_API_KEY` set, `python milo_demo.py`
   gives a genuine multi-turn bookkeeping conversation (dry-run, no writes). This is the most
   mature part of the persona work — use it to decide whether a live colleague is worth wiring.
3. **Keep using the cockpit + digest.** They're already the real product; nothing here changes
   them.
4. **Roll out current cockpit pins deliberately.** The platform slices in this repo reach workers
   only when their pinned rev moves.
5. **Try the persona group chat locally** (`examples/fleet_chat_demo.py`), then decide if the
   live Chat surface is worth the one paused build (checklist §D).

## Pre-launch checklist

### A. Repo-local platform status
- [x] **Model gateway** — provider-agnostic port, LiteLLM adapter, tool-use turn, multimodal /
      caching passthrough, content-free telemetry, and fleet fan-in path are built here.
- [x] **Shared company memory** — read/recall plus governed owner-only write are built here.
- [x] **Persona spine** — identity, soul/constitution, group space, receptionist, and colleague
      gateway wire are built here.
- [ ] **Session memory** — per-space/per-thread durable memory: framework wiring in review (#79,
      `chat_memory.py` / [`thread-memory.md`](thread-memory.md)); watched-working awaits the live transport + a worker pin bump.
- [ ] **Live Chat transport** — the Workspace add-on surface is still a future slice.

### B. Model/operator config
- [ ] **Pick a real model and get its API key** (e.g. Anthropic Haiku → `ANTHROPIC_API_KEY`).
- [ ] **Make the DPA call.** Hosting model calls sends care-home PII (email bodies, invoice text)
      to a third party — a data processor under GDPR Art. 28. Only once a DPA is in place, set
      `XBOOK_ALLOW_HOSTED_PII=1` (the gateway **fails closed** without it — that's by design).
- [ ] **Install the adapter + point the roles at the model:** `uv add 'clonway-cockpit[litellm]'`,
      then edit xbook's `config/models.yaml` (set `chat_intent` / `inbox_classify` /
      `ledger_period` to `provider: litellm`, `model: anthropic/claude-haiku-4-5`,
      `api_key_env: ANTHROPIC_API_KEY`) and uncomment the `pricing:` block so spend is recorded.
- [ ] **Verify** with one live call (proves the key + flag + model all work), from the
      Auto-Bookkeeper repo root — it prints the model's reply:
      `XBOOK_ALLOW_HOSTED_PII=1 uv run python -c "from dotenv import load_dotenv; load_dotenv('.env'); from xbook.ai import get_gateway; print(get_gateway().complete([{'role':'user','content':'say OK'}], role='chat_intent'))"`

### C. Consumer adoption / pin work
- [ ] **Bump xbook's cockpit pin** from `a75f7a0...` to a current rev when you want the
      receptionist, souls, colleague wire, and governed-write platform slices in the bookkeeper.
- [ ] **Decide whether xletter and xquill should become cockpit-drivable workers.** Their current
      `origin/main` checkouts pin cockpit for shared platform pieces but do not expose
      `--agent-stdio`.
- [ ] **Decide whether xadmissions should adopt cockpit at all.** No cockpit pin was observed on
      `origin/main`.
- [ ] **xops cost consumer (#171 area)** — so the model spend the gateway now records shows up on
      the xops cost page alongside infra spend (the xbook producer side is already wired).

### D. Live-surface work
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
