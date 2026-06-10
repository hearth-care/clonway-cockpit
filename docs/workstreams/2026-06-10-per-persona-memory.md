# Add per-persona multi-turn memory

Generated: 2026-06-10

Source: `/Users/olliepage/Developer/.Codex/state/auto-worker-quarter-review.md`

## Context

The review identifies per-persona multi-turn memory as a remaining persona-platform gap after transport.

## Work

- Design thread/space scoped memory for each persona.
- Keep shared company memory separate from private working memory.
- Preserve owner-only promotion into shared truth.

## What's Left

- Ship and watch the Chat transport first.
- Define retention and storage paths.
- Add tests for quoted content not becoming shared memory.

## References

- Fleet review: clonway-cockpit remaining gaps
- `docs/persona-platform-architecture.md` Two-tier memory
- `src/clonway_cockpit/shared_memory.py`

## Acceptance Criteria

- A persona can remember context within its own thread/space.
- Private memory does not leak across personas.
- Shared memory writes require owner confirmation.

## Suggested Superpowers Workflow

- Read the repo's `AGENTS.md`/`CLAUDE.md`, this workstream doc, and the linked references before touching code.
- Use `superpowers:using-git-worktrees` before implementation work, then create a fresh implementation branch from `main` rather than committing on this planning branch.
- Use `superpowers:writing-plans` to turn this draft PR into a checked implementation plan under the repo's existing plan location.
- Use `superpowers:test-driven-development` for code changes; if the first task is investigation or a failing behavior, use `superpowers:systematic-debugging` first.
- Use `superpowers:verification-before-completion` before claiming the work is done, and record the actual commands/results in the implementation PR.
- Use `superpowers:requesting-code-review` before merge if the implementation changes behavior, integrations, safety gates, cockpit/agent contracts, or production deployment.

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
