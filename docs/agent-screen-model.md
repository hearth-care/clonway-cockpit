# The agent screen model

`clonway_cockpit.model.ScreenModel` is the structured, JSON-serialisable description
of a cockpit screen that agents read and assert against (via `Host.on_screen` or
`clonway_cockpit.agent.CockpitDriver`). The human cockpit still renders Rich
renderables; the model is built from the same inputs by the `model_*` functions in
`render.py`, and parity tests keep the two in agreement.

## `Row.id` — a semi-public contract

Agents key on `Row.id`. Treat these as stable; changing one is a breaking change for
any agent script that asserts on it.

| Screen (`ScreenModel.kind`) | Row ids | key `meta` |
|---|---|---|
| `home` | `pill:<i>`, `need:<i>`, `shelf:<LETTER>` | `app_label`, `tenant_name` |
| `shelf_menu` | `option:<key>`, `back` | `label` |
| `walk.preflight` | `change:<i>`, `precond:<i>` | `ready`, `equivalent_cli`, `remedy` |
| `walk.result` | (prose region, no rows) | `ok`, `message`, `links` |
| `card` | (prose region, no rows) | `equivalent_cli` |
| `note` | (prose region, no rows) | `detail` |
| `help` | `help:<i>` (field `keys`) | — |
| `confirm` | (prose region, no rows) | `confirm_of` (`remedy` \| `doctor_fix`) |
| `doctor` | `probe:<i>`, `fix:<n>` (runnable), `fix:display:<i>` | `warnings`, `errors`, `ok` |
| `filter` | `match:<i>` | `term` |
| `walk.progress` | `log:<i>` (sync), `stage:<key>` (staged) | `label`, `elapsed`, `stages` |
| `unstructured` | (prose region holds the rendered text) | — |

`walk.progress` is emitted on **semantic change** (a new log line / a stage status
change), not per animation frame — `elapsed` ticks are not separate emits. The
`unstructured` kind is the fallback for any screen not yet migrated to a `model_*` twin;
the framework contract test (`tests/test_contract.py`) fails the build if a page-framing
framework `render_*` ships without one.

`ScreenModel.selection` is the id of the currently-cursored row (or `null`).
`ScreenModel.actions` is a best-effort list of keys/verbs the screen honours.
`ScreenModel.meta` carries screen-specific facts (e.g. preflight `ready`/`equivalent_cli`,
result `ok`/`links`).

## Driving headlessly

```python
from clonway_cockpit.agent import CockpitDriver

driver = CockpitDriver(host, keys=["c", "n", "q"])  # open shelf C, cancel preflight, quit
stream = driver.run()
assert any(s.kind == "walk.preflight" for s in stream)
```

## Scope

M1 + M1-rest cover every framework primitive: home, shelf menu, walk preflight/result,
capability card, note, help, the two confirm screens, doctor, filter, the three progress
screens, plus the `unstructured` fallback. Worker shelf-report screens and the walk
review/apply screen adopt the model in M3.
