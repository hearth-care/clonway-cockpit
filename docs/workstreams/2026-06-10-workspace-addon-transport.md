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

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
