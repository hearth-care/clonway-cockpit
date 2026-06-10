# Resolve statutory-hooks checkout ambiguity

Generated: 2026-06-10

Source: `/Users/olliepage/Developer/.Codex/state/auto-worker-quarter-review.md`

## Context

The review treats `clonway-cockpit-statutory-hooks` as ambiguous because it points to the same remote as `clonway-cockpit`.

## Work

- Compare the statutory-hooks checkout against current `clonway-cockpit/main`.
- Identify useful deltas that should be ported.
- Document whether the separate local checkout should be archived, retired, or kept as a worktree.

## What's Left

- Verify branch/remote identity.
- List files and commits unique to the checkout.
- Create implementation PRs only for deltas that are still relevant.

## References

- Fleet review: clonway-cockpit-statutory-hooks
- Local checkout `/Users/olliepage/Developer/clonway-cockpit-statutory-hooks`

## Acceptance Criteria

- There is one canonical cockpit repo path for future work.
- No statutory hook work is stranded in an ambiguous checkout.
- The decision is documented for future sessions.

## Suggested Superpowers Workflow

- Read the repo's `AGENTS.md`/`CLAUDE.md`, this workstream doc, and the linked references before touching code.
- Use `superpowers:using-git-worktrees` before implementation work, then create a fresh implementation branch from `main` rather than committing on this planning branch.
- Use `superpowers:writing-plans` to turn this draft PR into a checked implementation plan under the repo's existing plan location.
- Use `superpowers:test-driven-development` for code changes; if the first task is investigation or a failing behavior, use `superpowers:systematic-debugging` first.
- Use `superpowers:verification-before-completion` before claiming the work is done, and record the actual commands/results in the implementation PR.
- Use `superpowers:requesting-code-review` before merge if the implementation changes behavior, integrations, safety gates, cockpit/agent contracts, or production deployment.

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
