# clonway-cockpit

The shared **interactive-cockpit framework spine** for the Clonway worker family,
extracted from xbook's cockpit (C1). It carries the framework, not any domain
logic: the walk machine and its single write gate (`confirm_apply`), the
capability registry (`CapabilitySpec` / `WizardContext` / `BlastRadius`), the
render primitives that define the cockpit's locked visual language
(header / pulse / needs-you / toolkit / walk / doctor / usage chrome), the raw
single-keypress reader, local usage telemetry, the shell-out mechanism, the
forward-looking `Signal` model and emitter — **and the agent-navigability layer
that makes every cockpit drivable by an AI agent over the same code path a human
uses.**

On top of that spine the framework also ships the **persona platform** — the layer that
turns a worker into a human-named colleague: a provider-agnostic **model gateway**
(`gateway/` — `complete` / `complete_structured` / `complete_tools` over OpenAI-compatible
or LiteLLM adapters, with content-free per-call telemetry), worker-agnostic **persona
identity** (`persona.py`), a **soul + shared constitution** system-prompt layer
(`persona_soul.py`), a distributed-self-selection **group chat** (`group_chat.py`) and a
**receptionist** front door (`receptionist.py`), the **colleague** wire that binds
persona → soul → gateway so a whole *fleet* can converse (`colleague.py`), and a read-only
shared **company memory** (`shared_memory.py`). See
[docs/persona-platform-architecture.md](docs/persona-platform-architecture.md).

Workers (xbook, xhr, …) depend on this package and supply their own capabilities,
probes, and domain screens. The only **required** runtime dependency is
[`rich`](https://github.com/Textualize/rich) — the model gateway is stdlib-only (urllib),
and LiteLLM is an optional extra (`clonway-cockpit[litellm]`). The package never imports
any worker — it is the substrate they build on, not the other way round.

## Agent-navigable by construction

Every Clonway worker is **one binary serving two audiences** — a human TUI *and*
an agent-drivable surface — over the **same render loop, same code path, same
write gate**. There is no second implementation and no distinction between a human
operating a worker and an agent operating it. This is a structural property of the
framework, enforced in CI, inherited by every worker — not a per-worker add-on.

**The principle: one screen, two projections.**
A cockpit screen is described once. The human sees Rich renderables (`render_*`);
an agent reads a JSON `ScreenModel` (`model_*`) built from the same inputs. They
cannot drift, because the build fails when they do.

```
            ┌───────────────────────── one screen ─────────────────────────┐
 inputs ──▶ │  render_foo(...) → Rich pixels (human)                        │
            │  model_foo(...)  → ScreenModel.to_dict() → JSON line (agent)  │
            └───────────────────────────────────────────────────────────────┘
                       ▲ parity + drive-clean gate keeps these in lockstep
```

**The pieces (all in this package):**

| Concern | What | Where |
|---|---|---|
| The model | `ScreenModel` / `Region` / `Row` / `Field`, `to_dict()` with `schema_version` | `model.py` |
| The screens | `render_*` (human) + `model_*` (agent) twins | `render.py` |
| The gate | `assert_render_model_parity` (static: every page-framing `render_*` has a `model_*`) + `assert_drives_clean` (dynamic: drive the real loop, no screen reaches the agent as `unstructured`) | `contract.py` |
| The channel — served | `serve_stdio` / `serve_agent_stdio` — pump the cockpit over line-delimited JSON on stdin/stdout (`<worker> --agent-stdio`) | `agent.py` |
| The channel — driven | `CockpitClient` (subprocess peer) + `CockpitDriver` (in-process) — launch and drive a cockpit, read frames | `agent.py` |
| The write gate | `confirm_apply` — agent mode is **dry-run by default**; posting requires the opt-in guarded-apply token handshake | `walk.py` |

**The money gate.** An agent can navigate any flow but **cannot post**. In agent
mode every walk's write gate is dry-run. Posting requires *two* locks: the worker
launched with `--allow-apply`, **and** an explicit `{"apply":true,"token":<per-gate
nonce>}` echoed back at the `awaiting_apply` frame. Anything else declines; the
nonce defeats replay. The orchestrator routes that decision to a human approver
(`approve` callback) and never auto-approves.

**How it's enforced (why it stays true):** the gate (`contract.py`) ships *from*
this framework and is *imported* by each worker's CI (not hand-copied), so a
framework bump propagates the discipline fleet-wide via the pinned-rev model. A
screen with no model fails the build; a model that never emits on a real path fails
`assert_drives_clean`. New workers inherit the whole thing from the template.

**Read next:**
- [docs/agent-screen-model.md](docs/agent-screen-model.md) — the wire protocol, the
  `ScreenModel` contract, the `Row.id` table, the guarded-apply handshake, protocol
  versioning, and how to wire a worker to the agent channel.
- The `drive-cockpit` skill — the operational recipe for a session/agent to launch
  and drive any worker (read frames, route the write gate to a human).
- Auto-Orchestrator `docs/agent-driving.md` — how the orchestrator drives the fleet
  via `CockpitClient` (`xops.drive`).

## Layout

```
src/clonway_cockpit/
  keys.py        prompts.py     registry.py    state.py     shell.py
  doctor.py      render.py      walk.py        usage.py     shellout.py
  model.py       contract.py    agent.py       obs.py        # the agent-navigability layer
  signals/model.py   signals/rank.py   signals/emit.py   signals/horizon.py
  approval.py    conversation.py   shared_memory.py          # write-authz · operator routing · company memory
  persona.py  persona_soul.py  group_chat.py  receptionist.py  colleague.py   # the persona platform
  gateway/gateway.py  gateway/adapters.py  gateway/config.py  gateway/types.py  gateway/telemetry.py
```

- `model.py` — the `ScreenModel` contract + `SCHEMA_VERSION`.
- `contract.py` — the shippable parity + drive-clean gate workers import in CI.
- `agent.py` — `serve_stdio` / `serve_agent_stdio` (served side), `CockpitClient` /
  `CockpitDriver` (driving side).
- `gateway/` — the provider-agnostic model port (`Gateway`, `GatewayConfig`) + the
  OpenAI-compatible / LiteLLM adapters + content-free usage telemetry.
- `persona.py` / `persona_soul.py` — persona identity (`Persona` / `PersonaRegistry`) and
  the soul + validated shared constitution (`compose_system_prompt`).
- `group_chat.py` / `receptionist.py` / `colleague.py` — the group room (distributed
  self-selection), the front-door receptionist, and the `gateway_responder` wire that lets
  a fleet of personas converse persona → soul → gateway.
- `shared_memory.py` — the read-only company handbook (facts with frontmatter, keyword recall).

## Onboarding & scaffolding

- **Add a worker to the Fleet Signal layer:** [docs/onboarding-a-worker.md](docs/onboarding-a-worker.md)
  (includes the inherited agent channel — you wire ~nothing).
- **Scaffold a brand-new worker:** `worker-template/` + `copier.yml` generate a
  worker **born agent-navigable** — a working cockpit, the `--agent-stdio` channel,
  the inherited parity + drive-clean gate, a flag-guarded Signal emit path, a
  mandatory `@scan_horizon` stub, telemetry, CI, a `CLAUDE.md` carrying the
  convention, and the single write-gate safety posture — out of the box (S8/C6).

```sh
copier copy gh:hearth-care/clonway-cockpit ../xadmit   # or a local checkout path
cd ../xadmit && uv sync && uv run pytest -q             # green out of the box
uv run xadmit --agent-stdio                             # drive the SAME cockpit as an agent
```

`make template-smoke` runs a full generate-install-and-test of the template; the
fast, network-free assertions run in CI
([tests/test_worker_template.py](tests/test_worker_template.py)).

## Develop

```sh
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
