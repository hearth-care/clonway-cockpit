# Fleet Cockpit Conformance Tracker

> Survey source: `origin/main` of each worker repo, read 2026-06-12.
> For the supported cockpit tag and worker update recipe, see [pin-sync.md](pin-sync.md).

## Rule: a row is not green without a verified commit

Every cell in this tracker that claims a positive (command present, contract test yes, drive path
known) must be backed by the commit SHA and date in "Last verified". A row without both fields is
**unknown**, not green. Before flipping any cell, run the [verification recipe](#verification-recipe)
and refresh "Last verified" with the commit you observed against.

This file is the single source of truth for cockpit adoption status across the fleet. It does not
duplicate pin policy — [pin-sync.md](pin-sync.md) is the authority on the supported tag.

## Conformance matrix

Short SHAs are first 7 chars of the full commit hash. "Observed pin" = the `rev =` value in
`[tool.uv.sources]` in the worker's `pyproject.toml` on the verified commit; see
[pin-sync.md](pin-sync.md) for the supported line.

| Worker | Repo | Cockpit command | Observed cockpit pin | Contract test present | Dynamic drive path | Last verified | Known exceptions |
|---|---|---|---|---|---|---|---|
| xbook | hearth-care/auto-bookkeeper | `uv run xbook --agent-stdio` | `8449c2d` | No | not proven in CI | `bdd519a` · 2026-06-12 | — |
| xhr | hearth-care/auto-hr | `uv run xhr --agent-stdio` | `a75f7a0` | No | not proven in CI | `4d23729` · 2026-06-12 | ~60 s first-frame delay observed on first invocation |
| xletter | hearth-care/auto-marketer | _(no `--agent-stdio`)_ | `4c63daf` | No | n/a | `f789fe7` · 2026-06-12 | Not cockpit-drivable; `--agent-stdio` absent from CLI |
| xquill | hearth-care/auto-secretary | _(no `--agent-stdio`)_ | `4c63daf` | No | n/a | `192f1aa` · 2026-06-12 | Not cockpit-drivable; `--agent-stdio` absent from CLI |
| xadmissions | hearth-care/auto-admissions | `uv run xadmissions --agent-stdio` | `4c63daf` | No | not proven in CI | `33dea4e` · 2026-06-12 | — |
| xcqc | hearth-care/auto-inspector | `uv run xcqc --agent-stdio` | `4c63daf` | Yes | `assert_drives_clean` in `tests/test_cockpit_contract.py` | `11b487c` · 2026-06-12 | — |
| xsource | hearth-care/Auto-Procurer | `uv run xsource --agent-stdio` | `4c63daf` | Yes | `assert_drives_clean` in `tests/test_cockpit_contract.py` | `354fd63` · 2026-06-12 | — |
| xops bridge | hearth-care/auto-orchestrator | `uv run xops bridge --agent-stdio` | `4c63daf` | No | not proven in CI | `746eaaf` · 2026-06-12 | Orchestrator role — drives other workers via `CockpitClient`; also exposes its own `--agent-stdio` for meta-orchestration |

**Contract test present** = the worker's test suite imports `clonway_cockpit.contract` and calls
**both** `assert_render_model_parity` and `assert_drives_clean`. A partial import (one function
only) should be marked Partial, not Yes.

---

## Verification recipe

Run these checks against `origin/main` of the worker repo before editing any cell. Refresh
"Last verified" in the same edit.

### 1. Read the observed pin

```sh
gh api repos/hearth-care/<repo>/contents/pyproject.toml \
  --jq '.content' | base64 -d | grep -A2 'clonway-cockpit'
```

Record the `rev =` value. Compare with the supported line in [pin-sync.md](pin-sync.md).

### 2. Confirm `--agent-stdio` is present

```sh
gh search code --repo hearth-care/<repo> agent_stdio
```

Or with a local checkout:

```sh
grep -r 'agent.stdio\|agent_stdio' src/ --include='*.py' -l
```

If no match, the "Cockpit command" cell should read `_(no --agent-stdio)_`.

### 3. Confirm contract tests

```sh
gh search code --repo hearth-care/<repo> assert_render_model_parity
gh search code --repo hearth-care/<repo> assert_drives_clean
```

Both must return results for the cell to read Yes. One result without the other → Partial.

### 4. Record the commit and refresh this row

```sh
gh api repos/hearth-care/<repo>/commits/main \
  --jq '{sha: .sha[0:7], date: .commit.committer.date[0:10]}'
```

Paste `<sha> · <date>` into "Last verified". Every edit to a data cell in this tracker must
include a refreshed "Last verified" for that row.

---

## Open gaps (2026-06-12)

- **xletter, xquill**: No `--agent-stdio`. Adoption decision deferred; see
  [persona-platform-getting-started.md](persona-platform-getting-started.md) §C.
- **Contract tests missing** for xbook, xhr, xadmissions, xops bridge. xcqc and xsource are
  the reference implementations; add `tests/test_cockpit_contract.py` in each remaining worker
  to complete the fleet.
- **Pins on raw SHA**: All workers except xbook are on `4c63daf` (a raw SHA). Supported line
  is `v0.1.0`; see [pin-sync.md](pin-sync.md) for the update recipe.
- **xbook pin**: On raw SHA `8449c2d`, not on the supported `v0.1.0` tag.
- **xhr first-frame delay**: ~60 s on first invocation. Cause undiagnosed; agent drivers
  should set a timeout ≥ 90 s on the first frame read.
