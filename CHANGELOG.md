# Changelog

All notable changes to clonway-cockpit. Workers pin release tags, not raw SHAs; see
docs/release-policy.md and docs/pin-sync.md.

The format is based on Keep a Changelog 1.1.0, and this project follows the
pre-1.0 rules documented in docs/release-policy.md.

## [Unreleased]

## [0.1.0] - 2026-06-11

Retroactive baseline for the first tagged framework release. This section covers the
extraction history through the release-engineering implementation merge; at plan time,
`origin/main` had reached `8a53e3f`.

### Added

- Cockpit spine: extracted the shared walk machine, guarded `confirm_apply` write gate,
  capability registry, host threading, render primitives, adaptive page width, staged progress
  rendering, raw-mode hardening, live-log panel, navigation stack, and doctor UI affordances.
- Agent channel: added the agent-navigable cockpit contract, `ScreenModel` wire shape,
  headless `CockpitClient`, stdio serving path, template dogfood coverage, and contract checks
  that keep render/model projections in parity.
- Signals and telemetry: added the Signal model, app labels, emit helpers, horizon scanning,
  run telemetry, usage fan-in, and related worker-template signal tests.
- Worker template: added the generated-worker scaffold, local/job deploy shapes, born
  agent-navigable tests, generic home hooks, statutory hook consolidation, template smoke
  coverage, and Auto-Procurer/xsource planning docs.
- Approval and safety: added allowlist policies, autonomous write authorization boundaries,
  apply identity in awaiting-apply frames, approval delivery references, and conversation
  hardening around the money/write gate.
- Persona platform: added the model gateway, LiteLLM adapter, tool-use port, multimodal content
  parts, prompt-caching pass-through, persona identity, soul and constitution composition,
  shared/private/thread memory, group spaces, receptionist, colleague responder, chat transport,
  and public architecture/operator documentation.
- Cross-worker handoffs: added governed write support, negotiation spaces, per-space ledgers,
  plan composition, stall escalation, operator setup guidance, and delivery-truth docs.

### Changed

- Made agent navigability part of the repository contract in CLAUDE.md and README-adjacent docs,
  including the rule that page-framing `render_*` functions need matching `model_*` projections.
- Updated persona-platform docs repeatedly to match delivered behaviour and fleet adoption state.
- Added merge-queue CI triggering in the baseline history before the first release tag.

### Fixed

- Hardened the agent driver around broken pipes, EOF-preserving drains, quit handling, timeouts,
  dry-run authority, and AST-backed page detection.
- Fixed persona, approval, conversation, doctor, walk, render, and getting-started correctness
  gaps found during the pre-release rollout.
