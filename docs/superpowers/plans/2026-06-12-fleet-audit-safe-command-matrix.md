# Plan — Fleet safe-command matrix standard

> Source: 2026-06-12 fleet audit (operator-held) · Wave 0 · docs-only planning artifact.
> Implementation lands on this same branch per the fleet dispatch protocol.

## Context

The audit's cross-fleet P0: **dry-run/safe semantics are inconsistent across workers.**
Concretely observed: some workers' dry-runs still write local state; some report-style
commands default to write rather than read; some help paths hydrate secrets just to print
usage. An agent (or operator) cannot currently know, before invoking any given worker
command, whether it is safe — each worker has its own implicit notion of "safe", and none
publishes a machine-checkable classification. The framework's write gate
(`confirm_apply`, dry-run by default in agent mode) governs cockpit walks, but plain CLI
subcommands sit outside it, and that is where the inconsistencies live.

## Goal

A single cross-repo standard — owned by this framework repo — that defines the
safe-command matrix every worker must publish: fixed columns, fixed safety-class
vocabulary, and falsifiable rules for what each class permits, so "is this command safe
to run?" has one fleet-wide answer format.

## Non-goals

- No per-worker matrices in this repo — each worker publishes its own matrix in its own
  repo against this standard; this plan ships the standard plus one worked example for
  the template scaffold's commands.
- No code enforcement here (a contract-style checker that diffs a worker's CLI surface
  against its matrix is a natural follow-up, out of scope).
- No fixing of the observed violations (each is a worker-repo PR citing this standard).

## Deliverables

- [x] Phase 1 — `docs/safe-command-matrix.md` defining the column contract; one row per
  CLI subcommand/flag combination a worker exposes:
  - Command (exact invocation shape)
  - Help-only (prints usage and exits — MUST NOT touch network, credentials, or disk
    beyond reading config)
  - Read-only external (reads external systems; no mutation anywhere)
  - Local write (writes worker-local state/cache only; named paths)
  - External draft (creates a draft/pending artifact in an external system, not visible
    as a completed action)
  - External post/apply (mutates an external system; MUST sit behind the gate or an
    explicit flag)
  - Credentials required (which credential, or "none"; help-only rows MUST be "none")
  - Expected first output (what a caller sees first — frame kind, header line, or
    prompt — so a hang or a surprise write is detectable immediately)
- [x] Phase 2 — the classification rules, each falsifiable:
  - Every command has exactly one safety class (the highest-impact behaviour it can
    reach in its default invocation).
  - Default invocation is never riskier than its name implies: anything named
    report/list/show/status MUST classify read-only or stricter.
  - A dry-run mode MUST NOT mutate external systems and MUST name any local state it
    writes; "dry-run" with unlisted local writes is a violation.
  - `--help` and bare invocations MUST be help-only: no credential hydration, no
    network.
  - Matrix freshness: adding or changing a subcommand without updating the matrix fails
    the worker's own review checklist.
- [x] Phase 3 — a worked example: the matrix for the template scaffold's command surface
  (`<worker>` bare, `--agent-stdio`, `--allow-apply`, `signals scan`), demonstrating
  every column.
- [x] Phase 4 — adoption pointers: one line in `docs/onboarding-a-worker.md` and one in
  `worker-template/README.md.jinja` requiring each worker to publish
  `docs/safe-command-matrix.md` in its own repo against this standard.

## Acceptance criteria

- [x] `docs/safe-command-matrix.md` exists with all eight columns defined and the
  safety-class vocabulary closed (a command cannot be given a class not in the doc).
- [x] Each Phase 2 rule is stated so a reviewer can fail a specific row against it —
  including the three audit-observed violation patterns by name: dry-runs that write
  local state, report commands that default to write, help paths that hydrate secrets.
- [x] The worked example covers the template's commands with no empty cells.
- [x] Both adoption pointers are present; no worker-specific claims are made in this
  repo beyond the template example.
- [x] The standard explains its relationship to the cockpit write gate: the gate covers
  walks; the matrix covers the whole CLI surface; the two must agree where they overlap
  (an external post/apply row must reference its gate or flag).

## Verification

```sh
ls docs/safe-command-matrix.md
grep -n 'Help-only\|Read-only external\|Local write\|External draft\|External post\|Credentials required\|Expected first output' docs/safe-command-matrix.md
grep -n 'safe-command-matrix' docs/onboarding-a-worker.md worker-template/README.md.jinja
make template-smoke        # template README change still renders
uv run pytest -q           # framework suite unchanged
```

Expected: the standard exists with the full column contract and closed vocabulary, both
adoption pointers resolve, and the template smoke plus framework suite stay green.
