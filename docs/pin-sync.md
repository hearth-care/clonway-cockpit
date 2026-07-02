# Fleet Pin Sync

Supported: v0.1.0

Workers pin clonway-cockpit release tags, not raw SHAs and not `main`. The supported line above
is the single source an agent or doctor check should read when deciding whether a worker is on the
current framework release.

## Worker Update Recipe

For each worker repo:

1. Edit `[tool.uv.sources]` in `pyproject.toml`.
2. Replace the current `clonway-cockpit` rev with the supported tag:

   ```toml
   clonway-cockpit = { git = "https://github.com/hearth-care/clonway-cockpit.git", rev = "v0.1.0" }
   ```

3. Run `uv lock`.
4. Run that worker's documented local gates.
5. Open a one-line PR with the lockfile update.

`uv` records the resolved commit in `uv.lock`; the human-readable source stays on the release tag.

## Current Remote Pin Survey

Run `python3 scripts/check_fleet_pins.py` for a live survey against the current supported tag.

Last static snapshot: 2026-07-02 (re-run the script for current state).

`v0.2.0` was released on 2026-06-14. The supported baseline remains `v0.1.0`
until the operator moves it; a worker on a newer release tag is conformant under
the survey's newer-tag rule from PR #108.

| Worker repo | Pin as of 2026-07-02 | Status |
|---|---|---|
| auto-orchestrator | `v0.1.0` | OK (on supported baseline) |
| auto-admissions | `v0.1.0` | OK (on supported baseline) |
| auto-bookkeeper | `v0.2.0` | OK (newer release tag than `v0.1.0`) |
| auto-hr | `v0.1.0` | OK (on supported baseline) |
| auto-inspector | `v0.1.0` | OK (on supported baseline) |
| auto-marketer | `v0.1.0` | OK (on supported baseline) |
| auto-secretary | `v0.1.0` | OK (on supported baseline) |
| Auto-Procurer | `v0.1.0` | OK (on supported baseline) |

Update consumers before emitters when a wire shape changes. The orchestrator is the first consumer
because it bridges worker output across the fleet; update it before workers that emit changed
signals, run logs, screen models, or handoff payloads.

## Policy

- Every worker MUST pin a release tag.
- A worker MUST NOT pin `main`.
- A worker MUST NOT stay on a bare SHA after a supported tag exists.
- The maximum supported skew is one minor version between any two workers.
- A fleet-level operator config may record each worker's observed `cockpit_pin` so the
  orchestrator doctor can compare actual pins with the supported line in this file.
