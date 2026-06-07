# CLAUDE.md — clonway-cockpit

The shared interactive-cockpit framework that sits beneath every Clonway autoworker. Workers
depend on this package (pinned by git rev) and supply their own domain capabilities + screens.
The global + Clonway-family CLAUDE.md rules layer on top.

## Agent-navigability is the framework's whole point

This framework exists so every autoworker is **simultaneously a human TUI and an
agent-drivable surface** — same binary, same code path, no second implementation. "One screen
description, two projections": the human Rich render and the agent `ScreenModel` JSON are both
projections of one screen. There is no distinction between a human operating and an agent
operating a cockpit. This is enforced here, not left to discipline:

- **Every page-framing `render_*` ships a `model_*` twin.** The framework's own
  `tests/test_contract.py` dogfoods `clonway_cockpit.contract.assert_render_model_parity`. A
  page-framing screen with no model hands an agent `unstructured` — that fails the build. When
  you add a `render_*` that calls `page(...)`, add its `model_*` in the same change.
- **Models must emit on a real path.** `contract.assert_drives_clean` drives the loop
  headlessly and asserts no screen reaches the agent as `unstructured` — it catches
  "modeled-but-dead" (advertised but not wired), which static review structurally cannot see.
  Drive it, don't read it.
- **The agent channel is framework-owned, not per-worker boilerplate.** `serve_agent_stdio`
  (worker side) + `CockpitClient` (driving side) are the two ends of the protocol; both live
  here so they evolve together. The worker-template generates the worker side; the orchestrator
  uses the driving side.
- **Money/write paths go through the gate.** `confirm_apply` is the single write gate. Agent
  mode is dry-run by default; posting requires the explicit guarded-apply token handshake
  (`serve_stdio(allow_apply=True)` + a matched `{"apply":true,"token":…}`). Never add a second
  post path.
- **The protocol is versioned.** Every `ScreenModel.to_dict()` frame carries `schema_version`;
  a breaking wire change bumps it (the shape-pin test in `tests/test_model.py` forces this).

Full protocol + wiring recipe: `docs/agent-screen-model.md`. The interactive driving recipe
for sessions/agents lives in the `drive-cockpit` skill. New workers inherit all of the above
from `worker-template/` — they are born agent-navigable.

## Consumption model

Workers pin a `clonway-cockpit` git `rev`. A framework change propagates on the next rev bump,
so the contract gate + agent channel + protocol upgrades reach every worker that way — that is
how the discipline stays uniform across the fleet rather than drifting per repo.

## Tests

Full `pytest` suite runs in CI on every push/PR, not on every commit (keep pre-commit hooks
fast — ruff/format/mypy). Run locally with `uv run pytest -q`.
