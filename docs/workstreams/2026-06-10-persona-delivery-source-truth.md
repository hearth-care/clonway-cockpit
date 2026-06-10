# Keep persona delivery source of truth current

Generated: 2026-06-10

Source: `/Users/olliepage/Developer/.Codex/state/auto-worker-quarter-review.md`

## Context

The review recommends treating the persona architecture delivery table as the source of truth after each slice.

## Work

- Audit `docs/persona-platform-architecture.md` delivery state against merged PRs.
- Add a lightweight update rule for each persona-platform slice.
- Clarify designed vs coded vs deployed vs watched-working.

## What's Left

- Compare recent PRs #49-#68 to the delivery table.
- Check whether governed write is now merged and update status.
- Add links to the next locked slice.

## References

- Fleet review: clonway-cockpit lowest-hanging fruit
- `docs/persona-platform-architecture.md` Delivery section

## Acceptance Criteria

- The delivery table can be trusted before planning the next slice.
- No surface is described as live until watched working.
- Future worker PRs can link to one canonical platform state.

## Suggested Superpowers Workflow

- Read the repo's `AGENTS.md`/`CLAUDE.md`, this workstream doc, and the linked references before touching code.
- Use `superpowers:using-git-worktrees` before implementation work, then create a fresh implementation branch from `main` rather than committing on this planning branch.
- Use `superpowers:writing-plans` to turn this draft PR into a checked implementation plan under the repo's existing plan location.
- Use `superpowers:test-driven-development` for code changes; if the first task is investigation or a failing behavior, use `superpowers:systematic-debugging` first.
- Use `superpowers:verification-before-completion` before claiming the work is done, and record the actual commands/results in the implementation PR.
- Use `superpowers:requesting-code-review` before merge if the implementation changes behavior, integrations, safety gates, cockpit/agent contracts, or production deployment.

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
