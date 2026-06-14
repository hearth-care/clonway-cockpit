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

Last static snapshot: 2026-06-14 (re-run the script for current state).

| Worker repo | Pin as of 2026-06-14 | Status |
|---|---|---|
| Auto-Orchestrator | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |
| auto-admissions | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |
| auto-bookkeeper | `1c868027e31587c33acb5f4d213beeb7650df6f2` | 122 commits ahead (bare SHA → needs tag switch) |
| auto-hr | `a75f7a02e9da214d6eb55cd6b6f444d03251b114` | 70 commits behind `v0.1.0` |
| auto-inspector | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |
| auto-marketer | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |
| auto-secretary | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |
| Auto-Procurer | `4c63daf56500aecbb7e78c19660cbf94bd5c50ee` | 9 commits behind `v0.1.0` |

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
