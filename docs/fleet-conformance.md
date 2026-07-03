# Fleet Cockpit Conformance Tracker

> Survey source: `origin/main` of each worker repo, read 2026-07-03.
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
| xbook | hearth-care/auto-bookkeeper | `uv run xbook --agent-stdio` | `v0.3.0` | Yes | `assert_drives_clean` in `tests/cockpit/test_agent_contract.py` plus walk coverage in `tests/cockpit/test_agent_walk_coverage.py` | `8155694` · 2026-07-03 | On newer release tag than the supported baseline; accepted by the pin survey |
| xhr | hearth-care/auto-hr | `uv run xhr --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/cockpit/test_agent_contract.py`; opens shelves and walks deep (`["b","q"]`, `["h","x","q"]`, capability-key paths) | `e20f14a` · 2026-07-02 | First-frame SLA is now documented as <=2s warm cache / <=5s cold start; see open gaps |
| xletter | hearth-care/auto-marketer | `uv run xletter --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/test_cockpit_contract.py` | `759054c` · 2026-07-02 | — |
| xquill | hearth-care/auto-secretary | `uv run xquill --agent-stdio` | `v0.1.0` | Yes | `assert_render_model_parity` and `assert_drives_clean` in `tests/test_cockpit_contract.py` | `317a7b4` · 2026-07-02 | — |
| xadmissions | hearth-care/auto-admissions | `uv run xadmissions --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/cockpit/test_agent_contract.py`; drives home, admissions, and guide paths | `f7843b1` · 2026-07-02 | — |
| xcqc | hearth-care/auto-inspector | `uv run xcqc --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/test_cockpit_contract.py` and readiness paths in `tests/test_cockpit_readiness.py` | `b6302ec` · 2026-07-02 | — |
| xsource | hearth-care/Auto-Procurer | `uv run xsource --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/test_cockpit_contract.py` | `24d0ac9` · 2026-07-02 | — |
| xops bridge | hearth-care/auto-orchestrator | `uv run xops bridge --agent-stdio` | `v0.1.0` | Yes | `assert_drives_clean` in `tests/cli/test_bridge_agent_contract.py`; drives `["q"]` and `["d","x","q"]` to `worker_drilldown` | `72d1166` · 2026-07-02 | Orchestrator role — drives other workers via `CockpitClient`; also exposes its own `--agent-stdio` for meta-orchestration |

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

## Open gaps (2026-07-03)

- **xhr first-frame SLA**: the old ~60s first-frame delay has been fixed upstream, and
  auto-hr now documents a <=2s warm-cache / <=5s cold-start SLA in
  `docs/operators/agent-first-frame.md`. Keep this row under observation because drivers should
  still fail fast if the first frame misses that SLA.
