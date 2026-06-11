# Onboarding a worker to the Fleet Signal layer

**The payoff:** wire your worker into ~30 lines and a flag flip, and its
forward-looking alerts — "Insurance renews in 9 days", "Pay run due to post
Friday", "DBS expiring" — show up as a pill in the Fleet Cockpit and the morning
briefing, ranked and deduped alongside every other worker's. The operator sees
one cross-fleet "what needs me, by when" list instead of opening five tools. You
write a pure `build_*_signals()` against your real domain state; the shared
helper handles the GCS flush, the wire format, the run-id, and the
never-crash-a-run degrade.

Four workers already did this — **xbook**, **xhr**, **xletter**, **xquill**.
This guide is the distilled recipe; cite those four as worked examples. Future
workers (xadmit, xcqc) follow it verbatim.

---

## 1. Depend on clonway-cockpit

Add the git dependency to your `pyproject.toml` (pin a `rev`, like the others):

```toml
dependencies = [
    # ...
    "clonway-cockpit",
]

[tool.uv.sources]
clonway-cockpit = { git = "https://github.com/hearth-care/clonway-cockpit.git", rev = "<sha>" }
```

### The Dockerfile git-fix (slim images only)

If your worker builds a **slim** Docker image (`python:3.12-slim`, the Cloud Run
pattern), the builder stage needs `git` on PATH — `uv sync` clones the
`git+https` dependency and the slim base ships without git, so the install fails
with *"Git executable not found"*. Add this to the **builder stage** (xletter's
Dockerfile is the canonical example):

```dockerfile
FROM python:3.12-slim AS builder

# git is required to resolve the clonway-cockpit git+https dependency during
# `uv sync` — the slim base ships without it. Builder-stage only; the runtime
# image copies the already-built venv and never shells out to git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
```

**Not needed** for a worker with no slim-Docker build — **xquill** runs as a
local launchd daemon against the repo's own `.venv`, so its `uv sync` runs on a
machine that already has git. Skip the apt line there.

---

## 2. `signals/build.py` — the pure signal builder

Write `build_<worker>_signals(*, today, now) -> tuple[Signal, ...]` returning
[`Signal`](../src/clonway_cockpit/signals/model.py)s grounded in **real domain
state** — read your live integration (Xero, Sheets, Gmail, your DB), don't
fabricate. It must be **pure**: no I/O writes, no GCS, no flag check (the helper
owns those). Keep it 1:1 with what the operator should actually be nudged about
— the anti-fatigue discipline is inherited free.

Each Signal carries:

| Field | What | Notes |
|---|---|---|
| `kind` | one of the closed set | `deadline.approaching`, `action.required`, `anomaly.detected`, `approval.pending`, `credential.expiring` |
| `title` | short, stable | drives the dedup key — keep it constant as a signal escalates |
| `detail` | human one-liner | may change without re-raising (excluded from dedup) |
| `due_at` | real deadline `date` or `None` | sharpens urgency (overdue/due/soon/info) when known; `None` for action-now items |
| `dedup_key` | stable across cycles | use `build_signals()` from the model — it folds `worker|title|capability_key|focus|source_id` |
| `source_id` | per-instance business id | distinguishes two concurrent same-title instances (e.g. two pay cycles → `cycle:2026-06-04`); folded into `dedup_key` |

The easiest path (xbook's) is to build your `NeedsItem`s and call
`clonway_cockpit.signals.model.build_signals(needs, now=now, worker="<worker>")`
— it maps each NeedsItem to a Signal 1:1 with the right kind/urgency/dedup_key.
A worker without a cockpit needs-list (xhr/xletter/xquill) constructs `Signal`s
directly.

### `scan_horizon()` is mandatory — proactive by construction

A worker MUST declare its **forward-looking** alerts, not just its right-now
ones. This is the difference between a reactive log and a fleet that warns you
*before* the deadline. A horizon scan is just the `(*, today, now) ->
Sequence[Signal]` shape `emit_signals(build=...)` already consumes — the
framework names it `ScanHorizon` in `clonway_cockpit.signals.horizon`. This is
the one place your worker says "here's what's coming" — give every horizon item
a real `due_at` so urgency can sharpen as the date approaches without re-raising
the signal.

The shared abstraction (additive — your existing `build_<worker>_signals` keeps
working as-is):

```python
from clonway_cockpit.signals.horizon import compose_horizon, scan_horizon

@scan_horizon                                     # marks this as a horizon scan
def scan_insurance(*, today, now): ...            # -> Sequence[Signal], real due_at

@scan_horizon
def scan_compliance(*, today, now): ...

# compose_horizon stitches one-or-more scanners into the single build= callable
# emit_signals expects (concatenated in declaration order; ranking happens later).
build_<worker>_signals = compose_horizon(scan_insurance, scan_compliance)
```

`compose_horizon()` with no scanners returns an always-empty `build`; with one
it's a passthrough. The `@scan_horizon` marker is discoverable via
`is_scan_horizon(fn)` so the C6 worker template (and a future lint/test) can
assert a worker actually ships a horizon — today that's a guide rule, not yet
code-enforced.

Examples from the fleet:

- **xbook** — insurance renewal due, compliance filing due, pay run due to post,
  HMRC/pension payment coming up, cash getting tight.
- **xhr** — DBS expiring, right-to-work recheck due, probation review due.
- **xletter** — campaign send window, content review due.
- **xquill** — promise/commitment deadlines surfaced from chat digests.

---

## 3. `signals/emit.py` — a thin wrapper

Don't reimplement the GCS flush. Delegate to the shared helper:

```python
# src/<worker>/signals/emit.py
from __future__ import annotations

from datetime import datetime
from datetime import date as Date

from clonway_cockpit.signals.emit import emit_signals, flag_enabled
from clonway_cockpit.signals.model import Signal

from <worker>.signals.build import build_<worker>_signals

_FLAG = "<WORKER>_EMIT_SIGNALS"


def _enabled() -> bool:
    return flag_enabled(_FLAG)


def scan_and_emit(
    *,
    today: Date | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> tuple[Signal, ...]:
    return emit_signals(
        worker_id="<worker>",
        flag_env=_FLAG,
        build=build_<worker>_signals,
        now=now,
        today=today,
        run_id=run_id,
    )
```

The helper does the flag check (returns `()` when off — zero work, no build
call), resolves `now`/`today`/`run_id` (`CLOUD_RUN_EXECUTION` env → uuid
fallback), writes `signals/<worker>/latest.jsonl` every run (incl. empty, so a
now-quiet worker clears its old set) plus a dated archive
`signals/<worker>/<YYYY-MM-DD>/<run_id>.jsonl` only when non-empty, and degrades
silently on any GCS/build failure (never crashes a run).

**xquill's deviation — a project-pinned client.** xquill runs as a launchd
daemon whose env is HOME-only, so a bare `storage.Client()` can't resolve a GCP
project. Pass `project="clonway-care-bookkeeper"`:

```python
    return emit_signals(
        worker_id="xquill",
        flag_env="XQUILL_EMIT_SIGNALS",
        build=build_xquill_signals,
        project="clonway-care-bookkeeper",  # launchd env can't resolve a project
    )
```

Cloud Run workers (xbook/xhr/xletter) omit `project` — the runtime resolves it.
Tests inject a fake GCS client via `storage_client_factory=...` so no network is
hit and `google-cloud-storage` isn't needed in clonway-cockpit's own test env.

---

## 4. The CLI command — `<worker> signals scan`

Register a `signals` Typer sub-app with a `scan` command (xhr's
`src/xhr/cli/signals.py` is the template). It prints `disabled` when the flag is
off and `emitted N` when on:

```python
@signals_app.command("scan")
def cmd_scan() -> None:
    if not _enabled():
        typer.echo("signals: disabled (set <WORKER>_EMIT_SIGNALS=1 to enable)")
        return
    signals = scan_and_emit()
    typer.echo(f"signals: emitted {len(signals)}")
```

Verify locally before scheduling: `uv run <worker> signals scan` (off →
`disabled`) and `<WORKER>_EMIT_SIGNALS=1 uv run <worker> signals scan` (on →
`emitted N`, GCS flush skipped silently if you have no creds).

---

## 5. The flag (default OFF) + go-live

`<WORKER>_EMIT_SIGNALS` defaults OFF — the command and any scheduled call are a
no-op until an operator flips it. Going live is a flag flip + a scheduler entry.
Three deployment shapes, by worker pattern:

### Cloud Run **job** (args-override scheduler) — xbook / xletter

Set the env var on the job, then add a daily Cloud Scheduler entry that invokes
the job's existing args-override entry point with `["signals", "scan"]`:

```bash
gcloud scheduler jobs create http <worker>-signals-scan \
  --schedule="0 7 * * *" --time-zone="Europe/London" \
  --uri="https://<worker>-<hash>.run.app/jobs/<worker>:run" \
  --message-body='{"args":["signals","scan"]}'
```

(Pattern mirrors xbook's existing `xbook-calendar-scan` scheduler entry; see
`Auto-Bookkeeper/docs/ops/`.)

### Cloud Run **service** (HTTP route + OIDC scheduler) — xhr

A long-running service exposes `POST /jobs/signals-scan` (xhr shipped this in PR
#199, alongside its other `/jobs/<name>` crons in `src/xhr/webhook/app.py`). The
scheduler hits it with an OIDC token:

```bash
gcloud scheduler jobs create http xhr-signals-scan \
  --schedule="0 7 * * *" --time-zone="Europe/London" \
  --uri="https://<service>-<hash>.run.app/jobs/signals-scan" \
  --oidc-service-account-email=<scheduler-sa>@<project>.iam.gserviceaccount.com
```

### Local **launchd** — xquill

No Cloud Run; a launchd plist runs the command on a schedule with the flag set
(mirror `Auto-Secretary/deployment/com.ollie.xquill*.plist`):

```xml
<key>ProgramArguments</key>
<array>
  <string>/Users/olliepage/Developer/Auto-Secretary/.venv/bin/xquill</string>
  <string>signals</string>
  <string>scan</string>
</array>
<key>EnvironmentVariables</key>
<dict>
  <key>HOME</key><string>/Users/olliepage</string>
  <key>XQUILL_EMIT_SIGNALS</key><string>1</string>
</dict>
<key>StartCalendarInterval</key>
<dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
```

---

## 6. Register the codename with the bridge

The Fleet Cockpit bridge reads `signals/<worker>/latest.jsonl` **per codename**
from its roster — it doesn't auto-discover arbitrary prefixes. Confirm your
`worker_id` matches an entry in `Auto-Orchestrator/src/xops/bridge/workers.py`:

- `ROSTER` is the canonical set of short codenames (currently `xbook`, `xhr`,
  `xletter`, `xquill`, `xops`). **Add your codename here** so the bridge reads
  your feed and renders a pill.
- `WORKER_ALIASES` maps long service/directory names (e.g. `auto-bookkeeper` →
  `xbook`, `xsecretary` → `xquill`) so one pill represents both spellings. If
  your telemetry path or service name differs from your signal codename, add the
  alias.

Once your codename is in the roster and your scheduled `signals scan` runs with
the flag on, the cockpit shows your signals automatically — ranked, deduped, and
deadline-aware with the rest of the fleet.

---

## Checklist

- [ ] `clonway-cockpit` git dep pinned in `pyproject.toml`
- [ ] Dockerfile git-fix added (slim-Docker builds only — skip for launchd)
- [ ] `signals/build.py` with pure `build_<worker>_signals(today=, now=)` on real state
- [ ] `scan_horizon()`-style forward-looking items, each with a real `due_at`
- [ ] `signals/emit.py` thin wrapper over `emit_signals(...)` (+ `project=` for launchd)
- [ ] `<worker> signals scan` CLI command (`disabled` / `emitted N`)
- [ ] Flag wired (`<WORKER>_EMIT_SIGNALS`, default OFF) + go-live scheduler entry
- [ ] Codename in `xops/bridge/workers.py` ROSTER (+ alias if names differ)
- [ ] Local verify: `<WORKER>_EMIT_SIGNALS=1 uv run <worker> signals scan` → `emitted N`

---

## Agent channel — inherited, not wired by hand

A worker scaffolded from the template (S8/C6) is **born agent-navigable**: it ships
`{{worker}} --agent-stdio` (serves the same cockpit to an agent over line-delimited JSON),
an agent-mode-aware `_host()`, and the enforced gate (`tests/test_cockpit_contract.py` runs
`clonway_cockpit.contract.assert_render_model_parity` + `assert_drives_clean` in CI). You do
not write any of this — it comes from the template.

As the worker grows bespoke screens, the rule is simple and CI-enforced: **every page-framing
`render_*` ships a `model_*` twin, and you drive/verify via `--agent-stdio` /
`CockpitClient` / `CockpitDriver` — never scrape `export_text()`.** Money/write paths go
through the dry-run + guarded-apply gate. Full protocol + the wiring recipe (incl. the ambient
`_AGENT_MODE` variant for a worker that rebuilds its host) live in
[`docs/agent-screen-model.md`](agent-screen-model.md).

## Optional home-screen extension hooks

Generated workers also include `src/<worker>/cli/home_hooks.py`, wired into the
framework `Host` by default. It starts as three no-ops:

- `extra_selectables(state)` for worker-owned rows in the home cursor order.
- `extra_regions(state)` for worker-owned Rich panels between needs-you and toolkit.
- `handle_extra_key(state, selection, key, screen, read_key)` for keys on rows the worker owns.

This is the generic hook path for domain-specific home panels, including statutory heads-up cards.
The shared worker template must stay policy-neutral: new workers inherit the seam, not another
worker's statutory rules. Put CQC/payroll/admissions-specific labels, thresholds, and actions in the
worker repo's `home_hooks.py`, and keep the generated scaffold empty until that worker needs it.

## Becoming a colleague — the persona platform (optional)

Beyond the cockpit + Signal layers, a worker can become a human-named **colleague** the owner
DMs/emails. The framework owns the pieces — a provider-agnostic model gateway, persona identity,
a soul + validated constitution, the group-chat room, the receptionist, and the
`colleague.gateway_responder` wire — so adoption is config + a couple of files, not new
machinery: route the worker's model calls through `clonway_cockpit.gateway.Gateway`
(`role → model` config; default local), and add a `<handle>.toml` identity + `<handle>.md` soul
that `compose_system_prompt` stacks on the shared constitution. Recipe + the "hire the persona,
not the program" model: [`docs/persona-platform-architecture.md`](persona-platform-architecture.md)
and [`docs/personas.md`](personas.md). This layer is **opt-in** — a worker is fully useful with
just the cockpit + Signal layers above.

---

## Shared utilities — runlog, logging setup, bank holidays

Three small utilities that were previously copied per-worker are now centralised
in `clonway_cockpit`. New workers (scaffolded from the template) get them for
free; existing workers can migrate per the recipe below.

### Run log (`clonway_cockpit.obs.runlog`)

JSONL per-run audit trail. The template generates a two-line shim in
`src/<worker>/runlog.py` that binds the worker's id:

```python
from clonway_cockpit.obs.runlog import make_runlog
runlog = make_runlog("xbook")           # runs land in .xbook/runs/
```

API: `runlog.new_run_file(run_id)`, `runlog.append(run_file, **entry)`,
`runlog.hash_request(body)`. Wire format is byte-identical to the pre-extraction
worker copies (compact JSON, auto-`ts`, `sha256:` prefix).

### Logging setup (`clonway_cockpit.obs.logsetup`)

One function configures the root logger for any entrypoint or server. The
template calls it automatically from `main()`:

```python
from clonway_cockpit.obs.logsetup import setup_logging
setup_logging("xbook", runtime_env="XBOOK_RUNTIME", quiet=["httpx"])
```

Idempotent; stdlib-only; level from `<WORKER_ID>_LOG_LEVEL` env-var or arg;
UTC format `%(asctime)s %(levelname)s %(name)s %(message)s`.

### UK bank holidays (`clonway_cockpit.uk_calendar`)

England & Wales bank holidays through 2028, with a CI freshness tripwire (fails
when the table is within 12 months of its horizon):

```python
from clonway_cockpit.uk_calendar import is_business_day, next_business_day, DATA_HORIZON
```

API: `is_bank_holiday(d)`, `is_business_day(d)`, `next_business_day(d)`,
`previous_business_day(d)`, `business_days_between(a, b)`, `horizon_needs_refresh(today)`.
Querying beyond `DATA_HORIZON` raises `BankHolidayHorizonError` — no silent stale data.

### Migration recipe (existing workers)

Each migration is a separate per-worker PR, after the next framework release tag.

| Worker | runlog migration | logsetup migration | bank-holiday migration |
|--------|-----------------|-------------------|----------------------|
| xbook  | delete `src/xbook/runlog.py`; add `src/xbook/runlog.py` shim (2 lines) | swap `logging.basicConfig` in `__main__.py` + `server/__main__.py` for `setup_logging("xbook", runtime_env="XBOOK_RUNTIME")` | swap `xbook/calendar/bank_holidays.py` imports for `clonway_cockpit.uk_calendar`; keep a one-release deprecation shim |
| xhr    | delete `src/xhr/runlog.py`; add shim | swap `logging.basicConfig` in `server/__main__.py` | — |
| xletter | delete `src/xletter/runlog.py`; add shim | swap calls in `watchdog_runner.py`, `cli/entrypoints.py`, `intake/webhook_server.py` | — |
| xhr (HR) | — | — | add `from clonway_cockpit.uk_calendar import ...` to leave/statutory logic |

Each migration PR must: pin the new `clonway-cockpit` rev; run the worker's own
suite; verify `.{worker}/runs/` path is unchanged (the `default_runs_dir` default
preserves the original constant exactly).
