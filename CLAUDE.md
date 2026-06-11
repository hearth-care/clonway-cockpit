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

## The persona platform — same discipline, the conversational layer

On top of the agent-navigable spine the framework ships a persona platform (model gateway,
persona identity, soul + constitution, group chat, receptionist, the colleague wire). It obeys
the same enforce-don't-trust rules. Architecture: `docs/persona-platform-architecture.md`;
per-module docs: `docs/{model-gateway,personas,group-chat,receptionist}.md`.

- **The model gateway is the single model chokepoint.** Every model call goes through
  `clonway_cockpit.gateway.Gateway` (`complete` / `complete_structured` / `complete_tools`) —
  never a raw provider client. Provider/model is config (`role → model`), so a cost or provider
  switch is an edit, not a code change. Per-call telemetry is **content-free** (counts +
  metadata only); the default config is **local** (no key, no PII off-box). PII-to-hosted is the
  worker's fail-closed gate, not the framework's.
- **Personas compose through the validated constitution.** `compose_system_prompt` is the only
  way to build a persona system prompt; it stacks the swappable soul on the mandatory
  constitution and runs `validate_constitution` (a word-bounded *presence* check, not a semantic
  one). Never bypass it. The fleet's reference responder is
  `clonway_cockpit.colleague.gateway_responder` (persona → soul → gateway) — don't hand-wire a
  second one.
- **The owner-only-command air-gap mirrors the write gate.** In the group room only the owner's
  messages are commands (`is_command`); everything an agent says is data. An agent can never be
  talked into an action by another agent — same confused-deputy guard as the money gate, lifted
  to the message edge. Don't add a path that lets agent chatter trigger a write.

## Consumption model

Workers pin a `clonway-cockpit` git `rev`, and that rev must be a release tag named in
`docs/pin-sync.md`, not a raw SHA or `main`. A framework change propagates on the next tag bump,
so the contract gate + agent channel + protocol upgrades reach every worker that way — that is
how the discipline stays uniform across the fleet rather than drifting per repo.

Releases are changelog-driven: a release PR edits `CHANGELOG.md` and `pyproject.toml` together;
after it lands on `main`, `.github/workflows/release.yml` creates the matching tag and GitHub
Release from the changelog section.

## Tests

Full `pytest` suite runs in CI on every push/PR, not on every commit (keep pre-commit hooks
fast — ruff/format/mypy). Run locally with `uv run pytest -q`.
