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
| `shelf_menu` | `option:<identity>`, `back` | `label` |
| `walk.preflight` | `change:<i>`, `precond:<i>` | `ready`, `equivalent_cli`, `remedy` |
| `walk.result` | (prose region, no rows) | `ok`, `message`, `links` |
| `card` | (prose region, no rows) | `equivalent_cli` |
| `note` | (prose region, no rows) | `detail` |
| `help` | `help:<i>` (field `keys`) | — |
| `confirm` | (prose region, no rows) | `confirm_of` (`remedy` \| `doctor_fix`) |
| `doctor` | `probe:<i>`, `fix:<n>` (callback/capability), `fix:display:<i>` | `warnings`, `errors`, `ok`, `focus_requested`, `focus_matched`, `focus_state`, `focus_row` |
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

## Shelf menu action tokens

A `shelf_menu` row's stable identity and its rendered/dispatched direct-action key are two
different facts. Fresh `MenuItem` rows use `option:<ordinal>`. The accepted legacy
`(key, title, summary)` API preserves the exact key as `option:<key>` — including nonnumeric and
empty keys — so existing agent selectors do not move. Duplicate exact identities are rejected
loudly. Internally, nonnumeric legacy rows receive the lowest free positive ordinal, excluding
every numeric/direct ordinal claimed anywhere in the same menu; this prevents mixed-key menus from
manufacturing an ordinal collision. Legacy keys become advertised shortcuts only when they are one
ASCII lowercase letter or digit other than reserved `q`; all other legacy keys remain identities
but are not actions.

For fresh ordinal shelves, the one-character shortcut depends on position:

- ordinals 1–9 get shortcuts `"1"`–`"9"` (byte-compatible with every existing shelf);
- ordinal 10 onward gets deterministic lowercase letters `a, b, c, …` — **excluding `q`**
  (reserved for Back) — so ordinal 10 is `"a"`, ordinal 16 is `"g"`, and so on;
- the alphabet has 34 slots total (`1`-`9` + `a`-`z` minus `q`); a row past capacity
  (ordinal 35+) advertises **no shortcut** (`shortcut: None` — absent from both the row's
  `shortcut` field and `ScreenModel.actions`) and is reachable only by `up`/`down`/`enter`.
  This is a fail-safe for an oversized shelf, not the intended fleet UX — no worker shelf
  should exceed 34 capabilities.
- a row's `shortcut` field (when present) is a `Field(label="shortcut", ...)` alongside
  `summary`, distinct from the stable `id`.

Both channels normalize a one-character input to lowercase before dispatch (an uppercase
send routes the same as lowercase). **Legacy compatibility alias:** a canonical multi-character
ASCII decimal message with no leading zero and an in-range positive ordinal (e.g.
`{"key": "10"}`) still opens that capability — this
is a no-human-equivalent input a raw keypress can never produce in one token, kept ONLY so
an agent that cached an older framework's advertised `"10"`-style value still works. It is
never rendered, never appears in `ScreenModel.actions`, and two separate single-character
presses (`"1"` then `"0"`) can never combine into it — each key dispatches (or doesn't)
immediately. Leading-zero, Unicode digit-like, mixed, unknown and out-of-range strings are inert.
An oversized ASCII decimal that Python cannot safely convert is also inert; it cannot crash the
session.

## Doctor remedy actions

Doctor probe and remedy rows carry stable worker-supplied identity in additive fields. A probe row
includes `probe_id`, `evidence_revision`, `level`, and its `fix_id` cross-reference. A remedy row
includes `remedy_id`, `probe_id`, `action_kind`, `capability_key`, `focus`, `confirm`, and `cmd`.
The row's `cmd` is display/reference copy only; the framework never executes it.

Workers should use stable, namespaced IDs (for example `source.feed.health` and
`source.feed.review`) and change `evidence_revision` whenever the evidence represented by a probe
changes. Legacy empty IDs remain accepted, but a remedy receipt cannot correlate them and reports
closure as `unknown`.

The probe's `fix_id` names the row rendering that probe's own `Fix`, and it comes from the **same
pairing decision** the shell dispatches and receipts from — so what an agent reads as "this probe
owns that remedy" is exactly what ⏎ will act on. Object identity may help the shared pairing choose
a candidate, but the model publishes a link only when that final pairing attributes the remedy row
to the probe. This keeps links aligned for workers whose `doctor_fixes_for` normalizes fixes while
preserving stable IDs, repeated legacy fix instances, and fixes whose explicit owner differs from
the probe carrying the direct object. A remedy whose owner is missing or ambiguous carries **no**
`fix_id` rather than a guessed one — the same fail-closed rule dispatch and receipts use.

The three action kinds are:

- `display_only`: shown but not selectable; the operator uses the equivalent CLI or documentation;
- `callback`: invokes the worker callback for a human, preserving its optional confirmation, but is
  skipped in agent mode because the callback is opaque to capability effect policy; and
- `open_capability`: routes through the existing registered-capability chokepoint with optional
  `focus`. It is available to humans and agents. Nested writes still reach the capability's normal
  `walk.gate`; agent mode remains dry-run/default-declined.

A Home need may target `capability_key="doctor"` with a probe or remedy ID as `focus`. Doctor
resolves the identity against everything it renders — the full probe snapshot and the full fix
list, including display-only fixes — matching a probe first, then a remedy. The Rich `focus` line
and the model meta are two projections of one decision, published as three facts that can never
contradict each other:

- **`focus_state`** — the four-valued **resolution** verdict. It answers "did the identity
  resolve, and is it actionable?" and is *independent of where the cursor is*.
- **`focus_row`** — the row id the focus resolved to, or `null`. Non-null exactly when
  `focus_state` is `matched`, so a driver whose cursor has moved knows where to move back to.
- **`focus_matched`** — strictly "the **selected** row IS the one you asked for": the requested
  ID when `focus_state` is `matched` *and* `selection == focus_row`, otherwise `null`.

| `focus_state` | Meaning | `focus_row` | `selection` on entry |
|---|---|---|---|
| `matched` | Resolved to exactly one runnable remedy | that remedy's row | that remedy |
| `present` | Resolved to exactly one rendered target that has **no runnable remedy** (a display-only fix, or a probe carrying none) | `null` | `null` — **no row is pre-selected** |
| `ambiguous` | Two or more probes, or two or more remedies, claim the ID | `null` | the visible first row (fail-closed fallback, *not* authorized by the focus) |
| `unknown` | Nothing Doctor renders claims the ID | `null` | the visible first row |

**A driving agent must branch on `focus_state`, not on `focus_matched` alone**: `present` means
"your target is on screen, it just has no remedy to run", which is a different decision from
`unknown`. An identity Doctor is currently rendering is never `unknown` — reporting a visible
probe as "not found" is false in both projections. Conversely, **only `focus_matched` licenses
⏎**: a resolved focus the cursor has navigated away from still reports `focus_state="matched"`,
but ⏎ would run the row under the cursor, not your target. The Rich line says the same thing —
`✓ <id> matched` only while the cursor is on it, otherwise `⚠ <id> matched — cursor on row N`,
where `N` is the current `selection`/`❯` row. The focus target remains available separately as
`focus_row`; the cursor label never substitutes that target row for the operator's actual cursor.

Selection visibility is derived from the current resolution on **every** frame, including after
a remedy rebuilds the report. `present` deliberately pre-selects nothing so ⏎ cannot run an
unrelated state-changing remedy that happens to sit at row 1; the first ↑/↓/⏎ reveals the
fallback cursor without running it, and a numbered key is an explicit choice that still runs
directly. An explicit choice is authoritative only under the snapshot it was made in — a rebuild
is a new snapshot, so a remedy that leaves its own probe present-but-not-actionable re-hides the
cursor rather than silently arming a neighbour. An empty `focus` (`""`) is treated as no focus at
all, not as a focus on the empty ID that legacy probes carry.

`focus_state`/`focus_row` are additive — absent focus reports `null`, and the protocol
`schema_version` is unchanged.

After any selected action, Doctor re-probes the same stable `probe_id` and constructs one
`DoctorRemedyReceipt`. `resolved` means the probe is absent from a successful rebuild;
`still_present` means level and revision are unchanged; `changed` means either differs; and
`unknown` covers legacy identity or an unavailable comparison. Opening a capability is only
`action_result="opened"`—it is never itself proof of resolution. A capability `ShellOut`
intentionally ends the current session, so Doctor cannot re-probe; it delivers exactly one
`action_result="opened"`, `closure="unknown"` receipt before preserving the human shell-out or
agent shell-out-note boundary.

Workers opt into typed report failures with `Host.doctor_classify_report_failure(exception)` and
receive receipts through `Host.doctor_on_receipt(receipt)`. The classifier owns exception typing,
safe wording, and redaction. Receipt delivery is best effort; workers own persistence, timestamps,
and observability. Framework receipts contain bounded framework status rather than raw exception
text. A classifier-produced failure renders as a normal `doctor` model, not `unstructured`;
legacy hosts without the callback retain their existing fallback. The generated-worker scaffold
keeps its classifier example unwired so a report-builder exception still reaches the documented
setup hint; wire the example only after replacing it with the worker's typed/redacted taxonomy.

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
blocking read — request/response. Every `{"key":…}` message is answered by ≥1 frame: a
handled key emits its redraw; a key the screen's loop ignores re-emits the current screen
unchanged, so a driver never blocks on a silent key. A key that unwinds the cockpit
(`q`/`esc` at home) ends the session — EOF is that reply; animated `walk.progress` pushes
frames unsolicited, so treat app→agent as a stream. Malformed input degrades to an
`{"error":…}` reply and the screen is held; a single message is capped (~1 MB) and
over-deep/over-long JSON is reported, never crashes.

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
- `activate_pill` (pulse sync / bank re-auth) and Doctor callback remedies — **now gated**: in
  `agent_mode` the shell skips them and emits a `note{"…skipped…"}` frame instead. Doctor
  capability remedies may navigate because they reuse `_open_capability`; any nested write still
  reaches this same dry-run/guarded-apply gate. (The live human cockpit, `agent_mode=False`, is
  unchanged.)

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
update. Appending a new region to an existing screen's `regions` list (e.g. a worker's
`extra_model_regions` on `home`) is likewise additive and does not bump the version.

## Wiring a worker to the agent channel

A worker exposes the cockpit to an agent with two pieces, both inherited from the framework:

1. **`serve_agent_stdio(host, *, allow_apply=False, stdin, stdout, on_apply=None, policy=None)`**
   — the one-liner the worker's CLI `--agent-stdio` callback calls. It is thin over `serve_stdio`,
   which forces `agent_mode=True` (dry-run) and wires the guarded-apply handshake when
   `allow_apply`. `on_apply` is an audit callback fired on each apply; `policy` is an optional
   autonomous-authorization predicate (WS-B) consulted before a guarded apply.
2. **Session-aware nested callbacks.** `serve_stdio` sets `agent_mode=True` and installs the
   observer, guarded-apply authorization, audit sink, and agent prompt callbacks on the Host
   it threads through `run_cockpit`. A worker must wire
   `activate_pill_with_session` / `handle_extra_key_with_session` and use the supplied
   `ShellSession` helpers for nested work. Constructing another Host inside a callback drops
   that live state; carrying only an agent-mode flag is insufficient.

```python
# the worker's cli/__init__.py callback
if agent_stdio:
    serve_agent(allow_apply=allow_apply)   # → serve_agent_stdio(_host(agent_mode=True), …)
    raise typer.Exit()
```

```python
def handle_extra_key_with_session(state, selection, key, session: ShellSession) -> bool:
    if key == "p":
        session.open_capability("payroll-status")
        return True
    return False
```

The discipline is enforced, not optional: `clonway_cockpit.contract.assert_render_model_parity`
(static) + `assert_drives_clean` (dynamic, drives the real loop and asserts no `unstructured`
reaches the agent) run in the worker's CI. Drive and verify via `--agent-stdio` /
`CockpitClient` / `CockpitDriver` — never scrape `export_text()`.

## Worker home panels: `Host.extra_model_regions`

`Host.extra_model_regions` is the model twin of `Host.extra_regions`: instead of an
arbitrary Rich renderable, the worker returns ready-made `clonway_cockpit.model.Region`s,
which are appended to the home `ScreenModel`'s `regions` after `toolkit`. Region order in
the model is not a position contract — the three framework regions (`pulse`/`needs`/
`toolkit`) keep stable indices for existing agent scripts, and agents key on `role` /
`Row.id`, not position. The human render is unaffected: `extra_regions` still places the
panel between needs-you and toolkit on screen.

`meta.extra_regions` on the home model remains the RENDERABLE count (from `extra_regions`),
not the count of model regions — the two hooks are independent. Setting `extra_regions`
without also setting `extra_model_regions` leaves that panel agent-invisible; this is **not**
a contract failure. `assert_render_model_parity` checks `render_*`/`model_*` function-name
twins, not `Host` hooks, so it cannot see the gap; `assert_drives_clean` emits no
`unstructured` for an unmodelled extra panel either — the home model simply omits it.
Workers adopt `extra_model_regions` incrementally. A future drives-clean-style helper MAY
warn on `extra_regions`-without-`extra_model_regions`; building that helper is out of scope
here.

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
