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
| `walk.review` | per-walk line-item rows (e.g. `window:<date>`/`bill:<id>`/`settle:<i>`) | **`equivalent_cli`** (the apply command — canonical on every review), plus totals/counts + a full per-item detail list in `meta` |
| `unstructured` | (prose region holds the rendered text) | — |

`walk.review` is the **worker-built review screen** an agent reads at the write gate to see
exactly what a posting walk will do before authorizing (M3; xbook's schedule-bills,
payroll-clear, apply-remittance, raise-invoices, bills approve/settle). Row labels are
parity-checked against the human render; richer per-item detail (amounts, dates) rides in
`meta` (amounts are stringified — JSON-safe over stdio). Every `walk.review` exposes the
apply command under `meta["equivalent_cli"]`.

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
- `activate_pill` (pulse sync / bank re-auth) and Doctor `fix.run()` — **now gated**: in
  `agent_mode` the shell skips them and emits a `note{"…skipped…"}` frame instead, so an
  autonomously-driving agent triggers no sync / browser / local side effect. (The live
  human cockpit, `agent_mode=False`, is unchanged.)

For an authoritative audit of applied gates, `serve_stdio(..., on_apply=cb)` invokes `cb`
with the gate proposal the moment an apply is authorized (before the post) — a worker binds
its own `obs.event` there. Best-effort; a logging failure never blocks the post.

## Guarded apply — the M4 authorization handshake (opt-in)

`serve_stdio(host, *, allow_apply=False)`. With `allow_apply=True`, a write gate stops
being a blanket decline and offers a token handshake:

| Step | Frame / message |
|------|-----------------|
| app → agent | `{"kind":"walk.gate","meta":{"gate":"awaiting_apply","token":"<nonce>","equivalent_cli":"…"}}` |
| agent → app | `{"apply":true,"token":"<nonce>"}` — the ONLY input that authorizes |
| app → agent | `{"kind":"walk.gate","meta":{"status":"applied","token":"<nonce>"}}` → the walk posts |
| app → agent | `{"kind":"walk.gate","meta":{"status":"declined",…}}` → anything else (wrong/missing/stale token, `apply` not literally `true`, a plain key, EOF) — no post |

- The `token` is a fresh per-gate monotonic nonce, so a stale/duplicated apply (a previous
  gate's token) can never fire. The agent reads it from the `awaiting_apply` frame and is
  expected to route the proposal up for **human sign-off** before replying — the framework
  enforces the gate-matched handshake; the human policy is the agent's.
- **Default is unchanged dry-run.** With `allow_apply=False` (the default) there is no
  authorizer, so the gate emits `walk.gate{declined,dry_run}` and **never posts**, whatever
  the agent sends. Guarded apply is strictly opt-in.
- The `awaiting_apply` / `applied` / `declined` frames are the on-the-wire audit; an
  authoritative worker-side `obs` log of applied gates is a follow-on.
