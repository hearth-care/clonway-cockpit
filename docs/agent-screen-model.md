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

## Driving over a subprocess: `CockpitClient`

`CockpitDriver` drives an **in-process** host (tests, scripted verification). To drive a
**real worker as a separate process** — the production path the orchestrator and an agent
use — `serve_stdio` (served side) has a peer, `CockpitClient` (driving side):

```python
from clonway_cockpit.agent import CockpitClient

argv = ["uv", "run", "--project", "/…/Auto-Bookkeeper", "xbook", "--agent-stdio"]
with CockpitClient.spawn(argv) as c:
    home = c.read_home()         # first painted frame (dict; carries schema_version)
    frame = c.press("c")         # send {"key":"c"}, return the next frame
    snap = c.snapshot()          # re-request the current screen
    # at an awaiting_apply gate, route the proposal to a human before echoing the token:
    #   c.apply(frame["meta"]["token"], approve=ask_human)  # approve()->bool; never auto-approves
    # c.quit() runs on context exit (escalates terminate->kill so a child is never orphaned)
```

- `spawn(argv)` launches a subprocess; `over_streams(stdin=, stdout=)` wraps any reader/writer
  pair (the in-process test transport, or a custom one).
- A background reader thread pumps the emit-driven frame stream onto a queue; `read_home` /
  `press` / `snapshot` / `apply` / `drain` / `quit` read from it. `drain()` collects the extra
  frames an action emits before the cockpit blocks for input (e.g. `applied` + the home redraw).
- `apply(token, *, approve)` is the **human-sign-off seam**: it sends the apply message ONLY
  if `approve(proposal)` returns True; otherwise it declines. It never auto-approves.
- The orchestrator wraps this in `xops.drive` (resolve a roster codename → argv → drive),
  routing the gate to a real approval queue. The `drive-cockpit` skill is the operational
  recipe for a session/agent.

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
| agent → app | `{"input": "<value>"}` | answer a pending `input_request` (a walk's typed-capture field) |
| agent → app | `{"confirm": true\|false}` | answer a pending `confirm_request` |
| app → agent | `ScreenModel.to_dict()` | emitted at every draw |
| app → agent | `{"error": "<reason>"}` | bad JSON / non-object / unknown / non-string `key`; screen held |
| app → agent | `{"input_request": {"prompt": "<text>", "default": "<text>"}}` | a walk's capture step needs a typed value — answer with `{"input": …}` |
| app → agent | `{"confirm_request": "<prompt>"}` | a walk needs a yes/no — answer with `{"confirm": …}` |
| app → agent | `{"kind":"walk.gate","meta":{"status":"declined","reason":"dry_run"}}` | the write gate was reached and declined (dry-run) — the agent's observable proof the gate held |
| app → agent | `{"kind":"note","meta":{"shellout":true}}` | a capability shelled out; not exec'd in agent mode (session then ends) |

A walk that PROMPTS for typed values (a **capture step**) is drivable end-to-end: it emits
`input_request` / `confirm_request` and blocks for the driver's `input` / `confirm` reply (a
request/response handshake, like the apply gate below). `CockpitClient.answer_input(value)` /
`answer_confirm(bool)` are the driving-side helpers. EOF on a pending input surfaces a clean error
frame; a missing/false confirm is a safe NO. In agent mode the shell swaps the walk's
`input_fn`/`confirm_fn` for these — the live human cockpit keeps the worker's own terminal prompts.

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

## Protocol versioning

Every `ScreenModel.to_dict()` frame carries a top-level `"schema_version"` (currently
`"1.0"`, the `clonway_cockpit.model.SCHEMA_VERSION` constant). A driver / orchestrator
branches on it. The version bumps ONLY on a **breaking** wire change (a removed or renamed
key, or a changed type); additive keys (a new optional `meta` field) do **not** bump it. The
shape-pin test in `tests/test_model.py` (`test_to_dict_carries_schema_version`) fails on an
accidental breaking change to the top-level shape, forcing a deliberate bump + this doc's
update.

## Wiring a worker to the agent channel

A worker exposes the cockpit to an agent with two pieces, both inherited from the framework:

1. **`serve_agent_stdio(host, *, allow_apply=False, stdin, stdout)`** — the one-liner the
   worker's CLI `--agent-stdio` callback calls. It is thin over `serve_stdio`, which forces
   `agent_mode=True` (dry-run) and wires the guarded-apply handshake when `allow_apply`.
2. **An agent-mode-aware host factory.** `serve_stdio` sets `agent_mode=True` on the host it
   threads through `run_cockpit`. A worker whose `_host()` is **re-invoked inside its own
   callbacks** loses that flag on the rebuilt instance — so such a worker reads an ambient
   `_AGENT_MODE` module flag in `_host()` and sets it `True` before serving. A worker that
   never rebuilds its host can pass the host directly and skip the flag.

```python
# the worker's cli/__init__.py callback
if agent_stdio:
    serve_agent(allow_apply=allow_apply)   # → serve_agent_stdio(_host(agent_mode=True), …)
    raise typer.Exit()
```

The discipline is enforced, not optional: `clonway_cockpit.contract.assert_render_model_parity`
(static) + `assert_drives_clean` (dynamic, drives the real loop and asserts no `unstructured`
reaches the agent) run in the worker's CI. Drive and verify via `--agent-stdio` /
`CockpitClient` / `CockpitDriver` — never scrape `export_text()`.

## Coverage: what the gate actually proves

Two checks, and it matters which guarantees what:

- **`assert_render_model_parity` (static) is the EXHAUSTIVE guarantee.** It walks every
  page-framing `render_*` in the namespace and fails if any lacks a `model_*` twin. Nothing
  agent-blind can ship past it.
- **`assert_drives_clean` (dynamic) is COMPLEMENTARY, not exhaustive.** It drives only the
  screens the scripted keys reach, and asserts none of *those* fell through to `unstructured` —
  i.e. it proves the modeled screens it visits actually *emit* on a real path ("advertised but
  not wired" — drive it, don't read it). It does **not** prove every screen emits; widen the
  key script (or inspect `{m.kind for m in stream}`) to widen coverage.

Do not read a green `assert_drives_clean` as "every screen is agent-readable" — parity is what
proves that. The cross-process golden-path test (WS-A) is the end-to-end companion: it proves
the whole loop (spawn → drive → review → gate → decline=0 posts) survives a real process
boundary, which neither static check can.

## Model naming conventions

So an agent author can predict ids without reading every screen:

- **`kind`** follows `<domain>.<screen>` for worker screens — e.g. `report.compliance`,
  `cashflow.affordability`, `loans.list`, `pnl.review_list`, `valuation.overview`,
  `payroll.dashboard`, `occupancy.list`. Framework screens keep their bare kind (`home`,
  `walk.review`, `walk.gate`, `note`, …).
- **`Row.id`** is a stable `<entity>:<key>` — e.g. `bill:<id>`, `loan:<i>`, `dd:<i>`,
  `emp:<ref>`, `resident:<ref>`, `room:<n>`, `month:<YYYY-MM>`, `gap:<i>`. Keep it stable across
  releases; agents key on it.
- **`meta`** carries machine facts: totals/counts, a per-item detail list, and
  `equivalent_cli` on any screen with an apply/run command.
