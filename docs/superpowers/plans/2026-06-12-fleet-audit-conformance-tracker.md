# Plan — Fleet cockpit conformance tracker

> Source: 2026-06-12 fleet audit (operator-held) · Wave 0 · docs-only planning artifact.
> Implementation lands on this same branch per the fleet dispatch protocol.

## Context

The framework promises agent navigability fleet-wide, but adoption truth lives nowhere
versioned and current. The audit found:

- `README.md` ("Agent-navigable by construction") says the discipline is "enforced in CI,
  inherited by every worker", while actual adoption is uneven: **xbook, xadmissions, xcqc,
  xsource and the xops bridge emit structured frames; xletter and xquill expose no
  `--agent-stdio`; xhr's `--agent-stdio` can block ~60s before a first frame.**
- The only in-repo adoption matrix is in `docs/persona-platform-getting-started.md`
  ("Fleet adoption matrix", verified 2026-06-09) and is already stale — it lists
  xadmissions with no `--agent-stdio` marker, and has no rows for xcqc or xsource.
- `docs/pin-sync.md` tracks pins (supported line `v0.1.0`, per-worker pin survey of
  2026-06-11) but says nothing about agent-channel or contract-test conformance.

There is no single place an agent or operator can read "which workers are actually
cockpit-conformant, proven when, against what commit".

## Goal

A docs-owned, dated conformance matrix — one row per fleet worker — that is the single
source of truth for cockpit adoption, with a verification recipe that forbids marking a
row green without fresh source evidence.

## Non-goals

- No code, CI jobs, or automation in this phase (a doctor/CI check that diffs reality
  against the tracker is a natural follow-up, out of scope here).
- Not a pin policy — `docs/pin-sync.md` stays the authority on supported tags; the
  tracker consumes it, never duplicates it.
- Not a CI-workflow adoption board — that is `docs/ci-adoption.md` (a useful format
  precedent for this doc).
- No fixing of non-conformant workers (that is the adoption playbook plan, on its own
  branch).

## Deliverables

- [x] Phase 1 — `docs/fleet-conformance.md` skeleton with the column contract:
  - Worker (codename + repo)
  - Cockpit command (exact invocation, e.g. `uv run xbook --agent-stdio`; the xops
    bridge form `xops bridge --agent-stdio` is a valid variant)
  - Pinned cockpit rev (as read from the worker's `pyproject.toml`; link
    `docs/pin-sync.md` for the supported line)
  - Contract test present (worker CI imports `clonway_cockpit.contract` —
    `assert_render_model_parity` and `assert_drives_clean`)
  - Dynamic drive path (the key script(s) actually driven, beyond home `["q"]`)
  - Last verified commit + date (mandatory; a row without both is "unknown", not green)
  - Known exceptions (named `allow_unstructured` paths and latency caveats, e.g. xhr's
    ~60s first-frame delay)
- [x] Phase 2 — seed the rows from the 2026-06-12 audit truth above, marking anything
  not re-checked against each worker repo's current default branch as "unverified".
  **Deviation**: all 8 rows were re-checked fresh against each worker's `origin/main` on
  2026-06-12, so all carry verified commits rather than "unverified". Fresh check also
  found xadmissions has gained `--agent-stdio` (contradicts the 2026-06-09 getting-started
  doc which showed "No `--agent-stdio` marker observed" for it).
- [x] Phase 3 — verification recipe written into the doc with exact `gh api` / `gh search`
  commands for pin, --agent-stdio, contract tests, and commit refresh.
- [x] Phase 4 — cross-links added: README "Read next" section and
  `docs/persona-platform-getting-started.md` "Fleet adoption matrix" both point at
  `docs/fleet-conformance.md`; getting-started matrix marked superseded for adoption status.

## Acceptance criteria

- [x] `docs/fleet-conformance.md` exists and contains exactly one row per fleet worker
  (xbook, xhr, xletter, xquill, xadmissions, xcqc, xsource, xops bridge), each with all
  seven columns populated or explicitly "unknown".
- [x] No row is green without a "last verified" commit SHA and date; the doc states
  this rule in its preamble.
- [x] xletter and xquill rows show no `--agent-stdio` (confirmed by fresh check);
  the xhr row records the ~60s first-frame caveat.
- [x] Pins are cited as "observed pin" with a link to `docs/pin-sync.md`; the tracker
  contains no second pin-policy statement.
- [x] Both cross-links of Phase 4 are present and resolve.

## Verification

```sh
ls docs/fleet-conformance.md
grep -c '^|' docs/fleet-conformance.md        # >= 10 (header + separator + 8 worker rows)
grep -n 'last verified' docs/fleet-conformance.md
grep -n 'fleet-conformance' README.md docs/persona-platform-getting-started.md
uv run pytest -q                              # unchanged; docs-only change stays green
```

Expected: the conformance file exists with a complete matrix, both cross-links resolve,
and the test suite is untouched by a docs-only change.

## HANDOFF NOTES

**Current phase**: COMPLETE — all four phases implemented in one commit.

**What was done**:
- `docs/fleet-conformance.md` created with all 8 worker rows verified fresh from `origin/main`
  on 2026-06-12 via `gh api` and `gh search code`.
- All rows carry verified commit SHAs; none are "unverified".
- README.md "Read next" section extended with fleet-conformance link.
- `docs/persona-platform-getting-started.md` "Fleet adoption matrix" marked superseded.
- Plan doc checkboxes ticked.

**Key deviation from plan**: Phase 2 said to mark rows as "unverified" if not re-checked.
Fresh checks were run against all 8 workers; all rows are fully verified. Also found that
xadmissions now has `--agent-stdio` (the 2026-06-09 getting-started doc showed it absent —
it was evidently added between 2026-06-09 and 2026-06-12).

**Next concrete step**: None — ready for QA and merge.
