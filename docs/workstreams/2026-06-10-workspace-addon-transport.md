# Ship persona google chat add-on transport

Generated: 2026-06-10

Source: `/Users/olliepage/Developer/.Codex/state/auto-worker-quarter-review.md`

## Context

The review's highest-leverage cockpit feature is production Google Chat add-on transport for per-persona DMs and group-space self-selection.

## Work

- Build the Workspace add-on transport using xhr's working envelope/auth model.
- Support per-persona DM and group-space self-selection.
- Fast-ack when worker driving may exceed Chat's response window.
- Keep central router behavior out of scope.

## What's Left

- Define endpoint envelope normalization.
- Add operator allowlist and IAM/run.invoker docs.
- Watch one persona DM and one group-space selection working.

## References

- Fleet review: clonway-cockpit highest-leverage feature
- `docs/persona-platform-architecture.md` Chat transport section
- Auto-HR Chat add-on implementation

## Acceptance Criteria

- A named persona can receive a real Google Chat DM.
- A group-space message can be handled by distributed self-selection.
- A persona cannot perform cross-domain writes through the transport.

## Suggested Superpowers Workflow

- Read the repo's `AGENTS.md`/`CLAUDE.md`, this workstream doc, and the linked references before touching code.
- Use `superpowers:using-git-worktrees` before implementation work, then create a fresh implementation branch from `main` rather than committing on this planning branch.
- Use `superpowers:writing-plans` to turn this draft PR into a checked implementation plan under the repo's existing plan location.
- Use `superpowers:test-driven-development` for code changes; if the first task is investigation or a failing behavior, use `superpowers:systematic-debugging` first.
- Use `superpowers:verification-before-completion` before claiming the work is done, and record the actual commands/results in the implementation PR.
- Use `superpowers:requesting-code-review` before merge if the implementation changes behavior, integrations, safety gates, cockpit/agent contracts, or production deployment.
- If the work changes cockpit or agent-driving behavior, use the `drive-cockpit` skill and verify structured frames rather than scraping rendered terminal text.

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
