# Agent-navigable cockpit — workstream context & handoff

_Written 2026-06-06 at the end of the session that produced PR #28 (M1). Read this first if you're picking up this workstream. It's the "why" and the map; the spec and plan are the "what" and "how"._

---

## North star (what we're ultimately trying to do)

Let an **agent run the bookkeeping by driving the cockpit itself** — launch the TUI, navigate it, perform the work, and *verify it worked* — instead of a human being the only thing that can operate or qualify it. The motivating phrasing from the product owner:

> "I'd like to transform the TUI in Auto-Bookkeeper (and Auto-Orchestrator) to be agentic-friendly. Right now whenever we develop a 'shelf' or a 'walk', agents can't qualify it works because it's a visual thing for a human to render on a terminal screen. I want to re-architect the tool so agents can parse and navigate the TUI, so I can let 'Ryan' (an agent) do the bookkeeping by launching the TUI and making sure of the functionality."

"Ryan" is an agent in the operator's multi-agent harness. The target capability: **Ryan launches the cockpit, drives a walk end-to-end, and confirms it behaved — autonomously.**

## The problem (why this work exists)

The cockpit is a **Rich-based** terminal UI (the shared `clonway-cockpit` framework). Rich is a *rendering* library: it turns data into styled ANSI for a human screen. That's great for humans and useless for agents:

- When you build a new **shelf** (a top-level cockpit screen/section) or a **walk** (a guided `explain → preconditions → review → apply-gated → summarise` flow), the only way to "qualify it works" was to *look at it*, or to script keystrokes and then `Console(record=True).export_text()` and grep substrings against the rendered ANSI.
- That substring-grep approach is **brittle** (layout-coupled, breaks on cosmetic changes) and gives an agent **no semantic grip** on "what is on this screen" — no notion of regions, rows, the selected item, the available actions, or the structured facts (blast radius, equivalent CLI, the result's ok/links).

The good news discovered during design: the cockpit was **already half-built for this**. `shell.run_cockpit(host, *, read_key, screen)` already injects the keystroke source and a `screen.update(renderable)` sink (tests pass a fake screen + scripted keys), and the *state/logic* is already structured (`CockpitState`, `Step`/`StepResult`, `Precondition`, `Stage`). **Driving was solved; only the output was opaque.** So the whole workstream is: give the cockpit a **semantic output layer**.

## Jobs to be done (in order)

The product owner chose **"both, in that order"**:

1. **Verify-during-development** (the immediate pain): an agent can drive a new shelf/walk and assert it works from a structured snapshot. Read-only; no real writes. *This is the foundation and the safe first win.*
2. **Guarded autonomous operation** (the north star): Ryan operates the cockpit for real — including the write gate that posts to Xero — behind an explicit, reviewable authorization handshake.

## The solution, in one picture

A typed, JSON-serialisable **`ScreenModel`** is the agent-facing description of each screen. It is the contract agents read and assert against.

```
                       build from the SAME inputs
   render_*(state…) ───────────────┬───────────────► model_*(state…)
        │ (untouched, human pixels) │                      │
        ▼                           │                      ▼
   Rich renderable             parity tests           ScreenModel  ──► Host.on_screen / WizardContext.on_screen
        │                  (enforce no-drift)               │              (observer; default no-op)
        ▼                                                    ▼
   screen.update()  ── human terminal              CockpitDriver records the stream  ──► (M2) stdio/JSON ──► Ryan
```

Five layers + a safety gate (full detail in the spec):

1. **`ScreenModel` contract** — `kind`, `title`, ordered `regions` (each with `rows`/`text`), `selection` (the cursored row id), `actions`, `meta`. `Row.id` is a **semi-public contract** agents key on (`pill:<i>`, `need:<i>`, `shelf:<LETTER>`, `option:<key>`, `back`, `change:<i>`, `precond:<i>`).
2. **`model_*` builders** alongside the untouched `render_*`, built from identical inputs.
3. **The seam** — a single `on_screen(model)` observer on `Host`, threaded into walks via `WizardContext.on_screen`. Default no-op → the live cockpit pays nothing and is byte-identical.
4. **`CockpitDriver`** — in-process: feed scripted keys, get the recorded `ScreenModel` stream. The new, non-brittle test harness.
5. **Subprocess `--agent` mode (M2)** — wire `CockpitDriver` to line-delimited JSON over stdio so a separate process (Ryan) launches the real binary and drives it.
6. **🔒 The write gate** — walks post only through `walk.confirm_apply`. In agent mode the default is **dry-run** (the gate declines), so an agent can drive any walk end-to-end and *see* the review/blast-radius but never posts. M4 adds an explicit apply-authorization handshake routed for human sign-off.

## Key decisions & why (the forks taken this session)

| Decision | Choice | Why |
|---|---|---|
| Where it lives | The shared `clonway-cockpit` framework | Both xbook (Auto-Bookkeeper) and xops (Auto-Orchestrator) consume it; fixing it once serves both. |
| Primary goal | Verify-during-dev first, then guarded operation | Safe foundation before letting an agent touch real books. |
| Agent interface | Layered: in-process driver core + (later) subprocess JSON | The in-process driver powers tests/dev now; the subprocess wrapper (M2) is a thin shell over the same core so Ryan can launch the real app. |
| Snapshot source | `ScreenModel`, framework-first | A typed contract done for the framework primitives makes **all walks** agent-verifiable at once; worker shelf-reports migrate incrementally. |
| **Model ↔ render** | **Model builders + parity tests** (NOT rewrite render to derive from the model) | Keeps the mature, golden-tested human cockpit **byte-identical** and is far lower-risk than a byte-identical-or-bust rewrite of the composite home screen + 5 sub-renderers. Parity tests enforce no-drift in practice. |

## What M1 (this PR) delivers

Framework-only, purely additive, behind no-op defaults; human cockpit byte-identical; `make check` green (346 tests, up from 336):

- `src/clonway_cockpit/model.py` — `ScreenModel`/`Field`/`Row`/`Region` + `to_dict()`.
- `Host.on_screen` + `WizardContext.on_screen` seam, threaded into walks at the open-capability chokepoint.
- `model_*` builders + parity tests for the **navigation + walk path**: home, shelf menu, walk preflight, walk result. Emitted from `shell._home`, `shell._shelf`, `walk.preflight`, `walk.run_walk` (ok + error), and the shell's walk-crash chokepoint.
- `src/clonway_cockpit/agent.py` — `CockpitDriver` (scripted keys → recorded `ScreenModel` stream).
- `docs/agent-screen-model.md` — the `Row.id` contract.

## What's deliberately NOT here yet

- **Other framework primitives** (progress, doctor, filter, note, capability card, the two confirm screens, help) — same model+parity pattern, just not on the critical "drive a walk" path. → M1-rest.
- **The subprocess `--agent` protocol** — M2.
- **The walk review/apply screen** — it's built *inside each worker walk*, not a framework primitive, so it's not an M1 framework screen. → M3.
- **xbook shelf-report screens** (`render/_screens.py`, ~5,700 lines) — adopt the model incrementally. → M3.
- **Guarded writes** — the apply-authorization handshake + human sign-off. → M4.
- `CockpitDriver.send()` interactive stepping — arrives with M2's stdio pump.

## Roadmap

- **M1-rest** — model+parity+emit for the remaining framework primitives. Add an "unstructured fallback" `ScreenModel` for any screen not yet migrated, and a contract test that fails if a must-verify screen is still unstructured.
- **M2** — `agent.serve_stdio(host)` + an `--agent` flag in xbook (`xbook cockpit --agent`) and the xops bridge; protocol smoke test; **bump the pinned `clonway-cockpit` git rev** in xbook's and xops's `pyproject.toml` (currently xbook `144a89e`, xops `3408ef1`). Outcome: Ryan can launch + drive the real cockpit in dry-run.
- **M3** — migrate xbook's `_screens.py` shelf reports + the worker-built walk review screen to `ScreenModel`, prioritized by what agents must verify first.
- **M4** — the apply-authorization handshake (`meta.gate="awaiting_apply"`, explicit `{"apply":true,"token":…}`), routed for human sign-off; gate-safety test asserting zero writes without authorization; log applied gates via `obs`.

## Codebase orientation (for the next session)

- **Framework:** `/Users/olliepage/Developer/clonway-cockpit` — `src/clonway_cockpit/`: `shell.py` (the home loop + `Host`), `walk.py` (the walk machine + `confirm_apply` write gate), `render.py` (Rich primitives + now the `model_*` builders), `registry.py` (`CapabilitySpec`/`WizardContext`/`BlastRadius`), `state.py` (`CockpitState`), `keys.py`, `model.py` (new), `agent.py` (new), `obs.py`/`signals/` (operational telemetry to the xops dashboard — not screen semantics).
- **Consumers:** xbook = `/Users/olliepage/Developer/Auto-Bookkeeper` (package `xbook`; the cockpit is its "cockpit" with shelves A–G and walks under `src/xbook/cockpit/`). xops = `/Users/olliepage/Developer/Auto-Orchestrator` (package `xops`; a fleet bridge). Both pin `clonway-cockpit` by git rev.
- **Vocabulary:** *shelf* = top-level cockpit screen/section (A–G; xbook taxonomy in `render.SHELVES`). *walk* = guided flow (`explain → preconditions → review → apply-gated → summarise`). *pulse pills* = sync-status chips. *needs-you* = the actionable alerts list. *Host* = the worker-specific callback bundle the generic shell loop is parameterised on.
- **Gates:** `make check` = `ruff check` + `ruff format --check` + `mypy src` + `pytest -q`. Python ≥3.12.

## Gotchas & lessons (save the next session some pain)

- **The repo has a ruff autofix-on-save hook that STRIPS unused imports.** Add an import only in the same save where something uses it, or it vanishes. In practice: append the using-code first, then add the import; or use function-local imports in tests (as the preflight test does).
- **`mypy src` is enforced and unannotated-defaults are `Any`.** `model_preflight(remedy=None)` is deliberately left *unannotated* to mirror `render_preflight` (annotating it `object | None` makes `remedy.key` a type error). Don't "tidy" that.
- **Don't unpack a heterogeneous `dict` into typed kwargs** (`render_preflight(**pf)`) — mypy rejects it. Call render and model with explicit kwargs (DRY loses to mypy here).
- **The walk *review/apply* screen is worker-built**, not a framework render — it's M3, not M1. Don't look for a `render_review` in the framework.
- **The home screen is a composite** of `render_header/pulse/needs_you/toolkit/_legend` — which is exactly why we chose model+parity over rewriting render to derive from the model.
- **Worktree workflow:** all M1 work is on branch `claude/agent-navigable-cockpit-spec` in worktree `.claude/worktrees/agent-cockpit-spec`. Never commit to `main`. No `Co-Authored-By`/🤖 trailers (repo rule).

## Provenance (the colour: how this got built)

This workstream was scoped and built in a single session driven through a multi-agent harness ("Munder Difflin", an Office-themed local app orchestrating a hive of Claude agents). The orchestrator agent ("Michael") ran the superpowers flow end-to-end: **brainstorming** (the design dialogue + the forks above) → **writing-plans** (the M1 plan) → **subagent-driven execution**. Two notes worth carrying forward:

- **The implementation was done inline by the orchestrator, not by sub-agents**, because spawned implementer agents kept **crashing** mid-task in that environment (resource pressure from many concurrent processes). Inline controller execution with TDD + per-task gates proved reliable. If you re-run in a similar harness, watch for the same instability.
- A **fresh read-only reviewer pass** (APPROVE_WITH_NITS) caught a real gap — the walk-crash chokepoint wasn't emitting a model — which is fixed in this PR (with a regression test). Worth keeping the "emit at *every* draw site" check in mind as you add screens.

## Pointers

- Design spec: `docs/superpowers/specs/2026-06-06-agent-navigable-cockpit-design.md`
- M1 plan: `docs/superpowers/plans/2026-06-06-agent-navigable-cockpit-m1.md`
- `Row.id` contract: `docs/agent-screen-model.md`
- This PR: hearth-care/clonway-cockpit #28
