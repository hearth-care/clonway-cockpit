# WS-D — Conversational operator PLATFORM (design)

**Status:** approved-to-build (operator: platform-level, keep going), 2026-06-07
**Workstream:** WS-D (see `.claude/state/agentic-operating-workstreams.md`).
**Goal:** one fleet-wide, framework-owned conversational layer — DM a worker (bookkeeper, HR,
secretary, CQC…), it routes the command and drives that worker via the agent channel. The
safety + session model is defined ONCE in clonway-cockpit; every worker inherits it.

## Why platform-level
Highest value (a single pane to operate the whole fleet) AND highest blast radius (an agent
acting on conversational input across many repos). Design the trust + execution model once so
no worker improvises it.

## The trust boundary (the whole point)
A message carries a `source`: **`operator`** (a command from the verified operator) or
**`quoted`** (content forwarded/quoted from someone else — DATA). **Only an operator message is
ever a command; quoted content can never trigger an action.** This is the confused-deputy /
payroll-fraud guard at the conversation boundary (cf. the real "pay Sam into her Barclays
account" chat item — quoted content must never drive a write). Enforced in `Conversation.handle`
before any routing.

## Model-agnostic by construction (injected seams)
The framework provides the session, trust enforcement, execution (drive the worker, route the
write gate to the approver, narrate). It does NOT bake in an LLM, a Chat transport, or the
worker roster. Three injected seams:
- **`Router`** `(Message) -> Plan | None` — interprets a message into a worker + a drive script.
  The LLM lives HERE (operator/orchestrator supplies it). `None` = no actionable command.
- **`Launcher`** `(worker) -> argv | None` — codename → `--agent-stdio` argv (e.g.
  `xops.bridge.launch_argv` + `--agent-stdio`). `None` = not drivable.
- **`ApprovalPolicy`** — the write-gate decision (default `deny_all`); the human-sign-off /
  WS-B autonomous policy plugs in here.

## Components (clonway-cockpit `conversation.py`)
- `Message(text, source)`, constants `OPERATOR` / `QUOTED`.
- `Plan(worker, script, intent)` — a router's decision.
- `Reply(text, acted, frames)`.
- `Conversation(router, launch, approve=deny_all, drive=_drive_argv)`:
  - `handle(message)` → refuse non-operator source; route; resolve argv; drive; narrate.
- `_drive_argv(argv, script, *, approve)` — the default driver over `CockpitClient` (robust:
  guards `read_home`, tokenless gates; routes `awaiting_apply` to `approve`). Mirrors
  `xops.drive.drive_argv` but framework-owned + worker-agnostic.

## Out of scope (operator-deployed edge)
The Google Chat webhook/DM transport, the LLM router implementation, the worker roster wiring.
WS-D ships the platform core (default-off — a library; nothing runs until a transport calls it),
tested; the operator deploys the edge, injecting the three seams.

## Testing
- Trust boundary: a `quoted` message never acts (drive not called); an `operator` message with a
  routing plan acts.
- Routing: `Router→None` and `Launcher→None` both no-op safely.
- Approver threading: the `approve` policy reaches the drive; gate routes to it.
- The default `_drive_argv` drives an in-process worker and routes the write gate to `approve`
  (approve→post / deny→no-post).
