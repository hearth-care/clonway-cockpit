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

        ## Notes For Implementers

        This is intentionally docs-only. Use this branch/PR as the assignment brief, then open one
        or more implementation PRs as needed. Preserve the repo's safety invariants and verification
        gates when turning this workstream into code.
