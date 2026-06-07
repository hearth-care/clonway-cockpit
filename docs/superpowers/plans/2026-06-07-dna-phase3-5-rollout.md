# DNA Phases 3–5 — rollout: consumers, orchestrator, convention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Phase 3 repos are independent → good fan-out candidates (one subagent per repo, in worktrees).

**Goal:** Propagate the framework substrate to every existing cockpit consumer, give the orchestrator one uniform way to drive the fleet, and bake the convention into each repo's `CLAUDE.md` so the discipline is both documented and CI-enforced.

**Architecture:** Each consumer retires its hand-copied parity test + bespoke `serve_agent` in favour of the shared `clonway_cockpit.contract` gate + `serve_agent_stdio`, adds a drive-it conformance test, and bumps the pinned framework rev. The orchestrator (Auto-Orchestrator / xops) drives the roster via `CockpitClient`, routing `awaiting_apply` to a human approver. A `drive-cockpit` skill gives sessions/Ryan the same path.

**Tech Stack:** Python 3.12, Typer, pytest per repo; the framework `CockpitClient`/`contract` from Phase 1.

**Depends on:** Phase 1 merged to clonway-cockpit `main` (consumers pin the new rev). Phase 2 is independent of this plan.

**Parent spec:** `docs/superpowers/specs/2026-06-07-agent-navigability-as-platform-dna-design.md`

---

## Phase 3 — consumer retrofit (xbook, xops, xhr)

> Repos live outside this checkout (`~/Developer/Auto-Bookkeeper`, `~/Developer/Auto-Orchestrator`, `~/Developer/Auto-HR`). Work each in its own worktree/branch. **Verify against `origin/main`, not a stale local checkout** (hard-won: a stale xhr checkout once led to a wrong claim — xhr's interactive cockpit lives on `claude/new-joiner-kickoff`, not `main`). The three repos are independent → run them as parallel subagents.

### Task 3A: xbook (Auto-Bookkeeper)

**Files (verify exact paths against the repo):**
- Modify: `src/xbook/cockpit/app.py` (replace bespoke `serve_agent` with `serve_agent_stdio`; keep the `_AGENT_MODE` ambient flag — xbook *does* rebuild its host)
- Modify: `src/xbook/cli/__init__.py` (callback already has `--agent-stdio`; route through the framework wrapper)
- Replace: xbook's hand-copied parity test (the per-repo `test_contract`-equivalent) with a call to `contract.assert_render_model_parity(xbook.cockpit.render, ...)`
- Create: `tests/cockpit/test_agent_conformance.py` — `contract.assert_drives_clean(host, <script visiting each review screen>)`
- Modify: `pyproject.toml` — bump `clonway-cockpit` rev to the Phase-1 merge SHA
- Modify: `CLAUDE.md` — add the convention block (see Phase 5)

- [ ] **Step 1:** In a worktree off `origin/main`, bump the pinned rev; `uv sync`.
- [ ] **Step 2:** Replace the bespoke parity test. xbook puts `model_*` across `render/_screens.py` + `render/bills.py`; point `assert_render_model_parity` at the render package (pass the render namespace; if models live beside renders, the default `model_ns=render_ns` works). Run it; fix any orphan it surfaces (a real bug if found).
- [ ] **Step 3:** Replace the bespoke `serve_agent` body with `serve_agent_stdio(_host(agent_mode=_AGENT_MODE_OR_TRUE), …)`. Keep the ambient `_AGENT_MODE` set-before-serve (xbook rebuilds its host inside callbacks — the documented exception). Run xbook's existing agent tests.
- [ ] **Step 4:** Add the drive-it conformance test: build the agent-mode host, drive a script that reaches each `walk.review` screen (schedule/payroll/remittance/AR/bills), assert no `unstructured`. This is the per-repo positive proof that every modeled screen emits on a real path.
- [ ] **Step 5:** Add the `CLAUDE.md` block. Full gate: `ruff/format/mypy/pytest`. PR `feat(cockpit): adopt the shared agent-navigability gate (DNA Phase 3)`.

### Task 3B: xops bridge (Auto-Orchestrator)

**Files (verify):**
- Modify: `src/xops/cli/bridge.py` (`serve_bridge_agent` → `serve_agent_stdio`)
- Replace/add: the bridge's parity test → shared `assert_render_model_parity`; add `assert_drives_clean` for the fleet-cockpit home + a shelf drill
- Modify: `pyproject.toml` rev bump; `CLAUDE.md` block

- [ ] Same shape as 3A. The bridge's screens are largely framework screens (roster home, menus) → parity is mostly inherited; the conformance test proves the fleet home + a worker-shelf drill drive clean.

### Task 3C: xhr (Auto-HR)

**Files (verify — on `claude/new-joiner-kickoff`, NOT `main`):**
- Modify: `src/xhr/cockpit/app.py` (`serve_agent` → `serve_agent_stdio(_host(), …)`; xhr does not rebuild its host, so no ambient flag)
- Modify: `src/xhr/cli/__init__.py` (callback already has the flags)
- Replace/add: parity test → shared gate; add `assert_drives_clean`
- Modify: `pyproject.toml` rev bump; `CLAUDE.md` block

- [ ] Same shape. Confirm the big framework rev jump is still clean (xhr's suite). Note in the PR that this lands on the WIP cockpit branch (xhr has no cockpit on `main` yet) — the eventual `main` merge is the operator's call.

**Phase 3 exit criteria:** all three repos green in CI with (a) the shared parity gate, (b) a drive-it conformance test proving no `unstructured` on a real path, (c) the framework rev bumped, (d) the `CLAUDE.md` block. No repo keeps a hand-copied parity test.

---

## Phase 4 — orchestrator drives the roster + the `drive-cockpit` skill

### Task 4A: Orchestrator uses `CockpitClient` to drive workers

**Files (Auto-Orchestrator / xops — verify):**
- Create: `src/xops/drive/` — a thin orchestration layer over `clonway_cockpit.agent.CockpitClient`
- Test: `tests/drive/test_drive_worker.py` — drive a fake `--agent-stdio` worker (or a real one in CI) via `CockpitClient.spawn`, assert home frame, a snapshot, and the apply handshake routing

- [ ] **Step 1:** A `WorkerHandle` that resolves a roster codename → its `--agent-stdio` argv (reuse `xops/bridge/workers.py` ROSTER/aliases for discovery). `enumerate()` lists drivable workers.
- [ ] **Step 2:** A `drive(codename, script, *, approve)` that opens `CockpitClient.spawn([...])`, plays the script, and on a `walk.gate{awaiting_apply}` frame calls `apply(token, approve=approve)`. `approve` is the orchestrator's **human-sign-off queue** — never auto-approve.
- [ ] **Step 3:** Integration test: a tiny fake worker script that emits an `awaiting_apply` frame; assert `approve=True` → applied, `approve=False` → declined (0 posts). Reuse the in-process pattern from Phase-1 `test_cockpit_client.py` for speed; add one real-subprocess test against an installed worker if a worker is available in CI.
- [ ] **Step 4:** `CLAUDE.md` block. PR.

### Task 4B: `drive-cockpit` skill — one path for sessions + Ryan

**Files:**
- Create: `~/.claude/skills/drive-cockpit/SKILL.md` (or the repo's skills dir)

- [ ] A skill that documents the uniform recipe: launch `<worker> --agent-stdio` via `CockpitClient.spawn`, read frames, assert on `Row.id`/`kind`/`meta`, route `awaiting_apply` to the operator, **never** scrape `export_text()`. Includes the protocol (one JSON object per line), the `schema_version` check, the guarded-apply handshake, and the dry-run default. This is what makes "no distinction between human and agent" operational: any session drives every worker the same way.

---

## Phase 5 — the convention block (folded into each repo's PR)

Add this identical block to each fleet repo's `CLAUDE.md` (clonway-cockpit, Auto-Bookkeeper,
Auto-Orchestrator, Auto-HR, and any new worker via the template's generated `CLAUDE.md` —
add a generated `CLAUDE.md.jinja` to the template carrying it, as a Phase-2 follow-up):

```markdown
## Agent-navigability is non-negotiable

Every autoworker is simultaneously a human TUI and an agent-drivable surface — same binary,
same code path. This is enforced, not aspirational:

- **Every page-framing `render_*` ships a `model_*` twin.** CI runs
  `clonway_cockpit.contract.assert_render_model_parity(<your render ns>)`. A screen with no
  model hands an agent `unstructured` — that fails the build.
- **Drive, don't scrape.** Verify the cockpit via `--agent-stdio` /
  `clonway_cockpit.agent.CockpitClient` / `CockpitDriver`. Never assert on `export_text()`.
  A drive-it conformance test (`assert_drives_clean`) proves every modeled screen emits on a
  real path.
- **Money/write paths go through the gate.** Agent mode is dry-run by default; posting
  requires the explicit guarded-apply token handshake (`--allow-apply`). Never add a second
  post path.
- **The protocol is versioned.** Frames carry `schema_version`; a breaking change bumps it.
```

**Phase 5 exit criteria:** every fleet repo's `CLAUDE.md` carries the block; the worker
template generates it for new workers.

---

## Self-review

- **Spec coverage:** L3 consumers (Phase 3), L4 orchestrator + skill (Phase 4), convention (Phase 5). ✓
- **Cross-repo honesty:** every repo task says "verify exact paths against the repo" + "off `origin/main`" + the xhr-WIP-branch caveat — no assumed state. ✓
- **Fan-out:** Phase 3's three repos flagged as independent parallel subagent candidates; Phase 4 depends on Phase 1's `CockpitClient` only. ✓
- **No silent caps:** each phase has explicit exit criteria; the `approve` seam is called out as "never auto-approve" everywhere it appears. ✓
