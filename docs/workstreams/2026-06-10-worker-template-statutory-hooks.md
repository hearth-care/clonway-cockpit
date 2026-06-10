# Fold statutory hooks into worker template if needed

Generated: 2026-06-10

Source: `/Users/olliepage/Developer/.Codex/state/auto-worker-quarter-review.md`

## Context

The review says the leverage in statutory hooks is a single canonical worker template and hook path, not another support repo.

## Work

- Decide which statutory hook primitives belong in the shared worker template.
- Keep worker-specific statutory policy outside the framework.
- Add template smoke tests for any hook that becomes standard.

## What's Left

- Complete statutory-hooks consolidation first.
- Define framework hook contracts versus domain policy examples.
- Update `docs/onboarding-a-worker.md` if the template changes.

## References

- Fleet review: clonway-cockpit-statutory-hooks highest-leverage note
- clonway-cockpit `worker-template/`
- `docs/onboarding-a-worker.md`

## Acceptance Criteria

- New workers inherit only generic hooks that apply fleet-wide.
- Domain statutory rules stay in the worker repos.
- Template CI proves the generated worker still runs.

## Suggested Superpowers Workflow

- Read the repo's `AGENTS.md`/`CLAUDE.md`, this workstream doc, and the linked references before touching code.
- Use `superpowers:using-git-worktrees` before implementation work, then create a fresh implementation branch from `main` rather than committing on this planning branch.
- Use `superpowers:writing-plans` to turn this draft PR into a checked implementation plan under the repo's existing plan location.
- Use `superpowers:test-driven-development` for code changes; if the first task is investigation or a failing behavior, use `superpowers:systematic-debugging` first.
- Use `superpowers:verification-before-completion` before claiming the work is done, and record the actual commands/results in the implementation PR.
- Use `superpowers:requesting-code-review` before merge if the implementation changes behavior, integrations, safety gates, cockpit/agent contracts, or production deployment.

## Notes For Implementers

This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one or more implementation PRs as needed. Preserve the repo's safety invariants and verification gates when turning this workstream into code.
