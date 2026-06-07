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

## Boundary note (read before M2)

The `ScreenModel` carries whatever the screen carries — it is NOT a sanitised view:

- **`unstructured` holds the screen's raw rendered text.** It is the fallback for a
  not-yet-migrated screen (e.g. a worker's doctor-unconfigured hint), captured verbatim.
  Don't put secrets/credentials in a screen, and treat `unstructured.text` as sensitive.
- **`meta` strings are pass-through** — `equivalent_cli`, doctor `cmd`, `links` urls,
  `detail` are not escaped. They are safe under `json.dumps` (the M2 stdio protocol must
  serialise that way) but unsafe if a consumer raw-prints them to a terminal (a crafted
  url/`detail` could carry control sequences). **M2 invariant: serialise models as JSON
  at the process boundary; never raw-print model text.**

The observer is also best-effort by contract: `Host.on_screen` / `WizardContext.on_screen`
are invoked inside `try/except` (`contextlib.suppress`) at every emit site, so a buggy or
crashing observer (a recorder, the M2 pump) can never take down the human cockpit.

## Subprocess protocol — `agent.serve_stdio` (M2)

`agent.serve_stdio(host, *, stdin, stdout)` drives the real cockpit over line-delimited
JSON, so a separate agent process can launch and drive it. It is a thin pump over the
same `run_cockpit` core the in-process `CockpitDriver` uses.

| Direction | Message | Effect |
|-----------|---------|--------|
| agent → app | `{"key": "<k>"}` | the next keypress (`up`/`down`/`enter`/`esc`/letters/digits/…) |
| agent → app | `{"cmd": "snapshot"}` | re-emit the current `ScreenModel` (does not advance) |
| agent → app | `{"cmd": "quit"}` / stdin EOF | unwind the cockpit |
| app → agent | `ScreenModel.to_dict()` | emitted at every draw |
| app → agent | `{"error": "<reason>"}` | bad JSON / non-object / unknown / non-string `key`; screen held |
| app → agent | `{"kind":"walk.gate","meta":{"status":"declined","reason":"dry_run"}}` | the write gate was reached and declined (dry-run) — the agent's observable proof the gate held |
| app → agent | `{"kind":"note","meta":{"shellout":true}}` | a capability shelled out; not exec'd in agent mode (session then ends) |

Cadence: under piped (non-tty) stdin the loop emits one frame per draw before each
blocking read — request/response. Inert keys may not redraw (use `snapshot` to re-poll);
animated `walk.progress` pushes frames unsolicited, so treat app→agent as a stream.
Malformed input degrades to an `{"error":…}` reply and the screen is held; a single
message is capped (~1 MB) and over-deep/over-long JSON is reported, never crashes.

**Safety — `agent_mode` contract (read before wiring a worker `--agent`):**
`serve_stdio` runs in `Host.agent_mode`, which the shell threads as `dry_run=True` into
every walk's `WizardContext` at the open-capability chokepoint; `walk.confirm_apply` reads
the gate key (keeping cadence) then always declines and emits the `walk.gate` frame above —
an agent drives any walk end-to-end and sees the review/blast-radius but **never posts**.

This guarantee covers the framework's own walk path. It does **not** cover:
- A worker `handle_extra_key` / `activate_pill` that **rebuilds its own `Host`** — a fresh
  `Host()` defaults `agent_mode=False`, dropping dry-run. **A worker adding `--agent` MUST
  preserve `agent_mode` on any host it constructs**, or re-entering `_open_capability`
  through that host can post for real.
- `activate_pill` (pulse sync / bank re-auth) and Doctor `fix.run()` — these still run in
  agent mode (read-only / local by framework contract, not Xero posts). Gating them behind
  `agent_mode` is a future consideration.

The explicit apply-authorization handshake (turning the blanket decline into reviewable,
token-gated approval) is M4.
