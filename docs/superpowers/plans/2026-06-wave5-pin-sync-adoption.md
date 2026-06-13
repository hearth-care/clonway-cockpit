# [Plan] Fleet pin-sync + shared-module adoption

**Status:** draft plan — not implemented
**Source:** fleet audit follow-up 2026-06-13, Wave 5 (residual item 2 — "the highest-leverage unlock")

## Why

The framework release story now exists — a `v0.1.0` tag, a changelog, and a release
workflow — but **no worker pins it**. Every worker still pins a raw git rev, and those revs
diverge across the fleet. Per the `docs/pin-sync.md` remote-pin survey (GitHub default-branch
`pyproject.toml`, read 2026-06-11):

| Worker repo | Current default-branch pin | Behind `v0.1.0` (tag-relative) |
|---|---|---|
| Auto-Orchestrator | `4c63daf…` | 9 commits |
| auto-admissions | `4c63daf…` | 9 commits |
| auto-bookkeeper | `4c63daf…` | 9 commits |
| auto-hr | `a75f7a0…` | 70 commits |
| auto-inspector | `4c63daf…` | 9 commits |
| auto-marketer | `4c63daf…` | 9 commits |
| auto-secretary | `4c63daf…` | 9 commits |
| Auto-Procurer | `4c63daf…` | 9 commits |

(Commit distances measured `git rev-list --count <rev>..v0.1.0` in this repo. The follow-up
report cites "up to ~192 commits behind" for the most-behind worker; that figure is the
absolute lag against `main` HEAD at audit time, not the tag-relative number — a builder MUST
re-survey live pins as step 0, see Risks. The *direction* is unambiguous: every worker is
behind, none is on the tag, and one is meaningfully further behind than the rest.)

The consequence is the real prize. The audit's original weakness #5 — **~1,000 lines of
duplication** across the workers (each repo carrying its own runlog, Google-auth lifecycle,
config loader, Sheets client, log setup, UK-calendar helpers, signal emit/subscribe, audit
ledger) — was solved *at the framework*: cockpit extracted all of those into real, tested
modules. But because no worker pins a rev that contains them, **the duplication is removed at
the framework and still present in every worker.** The workers don't yet *have* the shared
modules, the signal factory, the subscription bus, or the audit ledger. They cannot adopt code
they don't depend on.

One pin-bump sweep onto `v0.1.0`, followed by a mechanical per-worker "import the shared
module, delete the local copy" pass, unlocks a large share of the framework's value at once and
finally retires the duplication. This plan is that sweep.

## Scope

**In:**

- Bump every worker's `clonway-cockpit` pin from its current raw SHA to the supported release
  tag (`v0.1.0`), per the mechanical recipe already written in `docs/pin-sync.md`.
- For each worker, **adopt the shared modules and delete the local duplicates** they replace —
  the layer `docs/pin-sync.md` does not cover (it stops at "bump the pin + `uv lock`").
- Surface and resolve any public-API drift exposed by jumping a worker from a stale rev up to
  the tag (renames, package-conversions like `obs` module→package, signature changes).
- One follow-up PR **per worker**, dependency-ordered, each landing green on that worker's own
  CI before the next.

**Out:**

- New framework features, new shared modules, or new signal types. This is adoption of what
  `v0.1.0` already ships — not framework development.
- Branch-protection required-checks (Wave 5 item 1 — separate, do-first plan).
- Wiring the missing xbook `payment.required` AP-intake consumer (Wave 5 item 3 — separate).
- Flipping any integration flag (`*_EMIT_*` / `*_CONSUME_*`) — operator runbook work, out of
  band of a pin bump.
- Re-tagging cockpit or cutting `v0.2.0`. If a worker needs a framework change to adopt cleanly,
  that is a cockpit PR + release first, then this plan resumes against the new supported tag.

## Spec

### The pin target — one tag, fleet-wide

Per `docs/pin-sync.md` and the repo's consumption model (`CLAUDE.md`, README §"Agent-navigable
by construction" (c)): workers pin a **release tag, never a raw SHA and never `main`**. The
single fleet pin target for this sweep is the supported line in `docs/pin-sync.md` — currently:

```toml
# pyproject.toml  [tool.uv.sources]
clonway-cockpit = { git = "https://github.com/hearth-care/clonway-cockpit.git", rev = "v0.1.0" }
```

then `uv lock` (uv records the resolved commit in `uv.lock`; the human-readable source stays on
the tag). `docs/pin-sync.md` is the source of truth for *which* tag is supported — this plan
does not hardcode a second copy; if the supported line advances before the sweep finishes,
later workers target the newer tag and earlier ones get a trailing catch-up bump.

### The canonical adoption table — local duplicate → cockpit import

For each shared module, the local file a worker currently duplicates and the cockpit import
that replaces it. Exact symbols verified against `src/clonway_cockpit/` at `origin/main`.
(Local filenames are the conventional ones to grep for; a worker may have named its copy
slightly differently — the builder confirms per repo.)

| Concern | Local duplicate (grep target) | Replace with cockpit import | Public surface to use |
|---|---|---|---|
| Per-worker run log (JSONL) | `*/runlog.py`, `*/obs.py` | `from clonway_cockpit.obs import runlog` | `runlog.make_runlog(worker_id)` → `Runlog.new_run_file` / `.append` / `.hash_request`; module fns `default_runs_dir`, `new_run_file`, `append`, `hash_request` |
| Run/stage telemetry emitter | local `obs`/telemetry shim | `from clonway_cockpit.obs import make_obs, flush_buffer, resolve_run_id` | `make_obs`, `flush_buffer`, `resolve_run_id`, `CloudLoggingSink`, `FORCE_FLUSH_ENV` |
| Root-logger setup for entrypoints | `*/logsetup.py`, `*/logging.py` | `from clonway_cockpit.obs.logsetup import setup_logging` | `setup_logging(worker_id, *, level=, runtime_env=, quiet=)` |
| Google credential lifecycle | `*/google_auth.py`, `*/auth.py` | `from clonway_cockpit.google_auth import …` | `resolve_credentials`, `CredentialSpec`, `build_service`, `sa_credentials`, `refresh_if_needed`, `default_store` (+ `FileTokenStore`/`KeyringTokenStore`/`MemoryTokenStore`); errors `GoogleAuthError`, `CredentialsUnavailable`, `ScopeMismatch`, `RefreshLockTimeout` |
| Worker config loader (YAML + env overlay) | `*/config.py` (the loader, not the model) | `from clonway_cockpit.config import load_config, SecretEnvName, ConfigError` | `load_config[ModelT](...)`; annotate secret-name fields with `SecretEnvName`; needs the `clonway-cockpit[config]` extra |
| Google Sheets client | `*/gsheets.py`, `*/sheets.py` | `from clonway_cockpit.gsheets import SheetsClient, extract_sheet_id, a1, col_letter` | `SheetsClient` (injected service — credential resolution stays worker-owned), A1 helpers |
| UK bank-holiday / business-day calendar | `*/uk_calendar.py`, `*/calendar.py`, `*/bank_holidays.py` | `from clonway_cockpit.uk_calendar import …` | `is_bank_holiday`, `is_business_day`, `next_business_day`, `previous_business_day`, `business_days_between`, `horizon_needs_refresh`; error `BankHolidayHorizonError` |
| Signal emit (the forward-looking factory) | local `signal`/emit shim | `from clonway_cockpit.signals.factory import SignalFactory` (+ `from clonway_cockpit.signals.emit import emit_signals, flag_enabled`) | `SignalFactory.make` / `.from_needs` / `.emit`; `emit_signals(...)`, `flag_enabled(env_var)` |
| Signal subscription bus | local poll/cursor code | `from clonway_cockpit.signals.subscribe import poll, Subscription, Delivery` + a cursor store (`FileCursorStore` / `GcsCursorStore`) | `poll(...)`, `Subscription`, `Delivery`, `CursorStore` |
| Fleet audit ledger | `*/audit_log.py`, `*/audit.py` | `from clonway_cockpit.audit_log import make_audit_sink, AuditEvent, read_events` | `make_audit_sink(...)`, `AuditEvent`, `read_events`, plus `AUDIT_SCHEMA`/`EVENTS`/`ACTORS` constants |

Notes that bite during adoption (verified, not speculative):

- **`obs` is now a package, not a module.** `from clonway_cockpit.obs import make_obs` and
  `from clonway_cockpit import obs` both still work (the package re-exports the old surface), but
  `runlog` and `logsetup` are **sub-modules requiring explicit import**
  (`from clonway_cockpit.obs import runlog`). A worker on a pre-package rev that did
  `obs.runlog` via attribute access may need an import line added.
- **Credential resolution stays worker-owned.** `SheetsClient` and the gateway take an
  injected service / resolved credentials; the worker keeps its own fail-closed credential gate
  and only delegates the *mechanism* to `google_auth`. Adoption removes duplicated lifecycle
  code, not the worker's trust boundary.
- **`config` and the gateway are optional extras.** `clonway-cockpit[config]` is required for
  `load_config`; the model gateway (`clonway_cockpit.gateway.Gateway`) is a separate concern —
  in scope to adopt only where a worker already hand-rolls model calls, otherwise leave for a
  dedicated gateway-migration plan.

### What "deleted the local copy" means

A module is adopted when (a) every worker import of the local file is repointed at the cockpit
symbol, (b) the local file is deleted (not left as a re-export shim — shims perpetuate the
duplication the audit flagged), and (c) the worker's own tests that exercised the local copy
either move to exercise the cockpit behaviour through the worker, or are deleted if they were
change-detectors restating the now-shared implementation. Per global test discipline: a test
that breaks during this refactor *without catching a real bug* is confessing it's a
change-detector — prune it then, with the evidence in hand.

### Relationship to existing docs (build on, don't duplicate)

- **`docs/pin-sync.md`** owns the mechanical pin bump (edit `[tool.uv.sources]` → `uv lock` →
  one-line PR) and the supported-tag line. This plan **cites** it for the bump and adds the
  adoption layer on top. Do not re-document the bump recipe here.
- **`docs/superpowers/plans/2026-06-12-fleet-audit-adoption-playbook.md`** (PR #100) is the
  **agent-channel** retrofit recipe — pinning is step 1 there, but its subject is wiring
  `--agent-stdio` + the contract asserts, not shared-module dedup. This plan is the sibling
  that covers the *module* adoption the agent-channel playbook deliberately scopes out. A worker
  that is doing both at once (e.g. xletter/xquill, which the playbook flags as lacking the agent
  channel) should land the pin bump once and reference both docs.

## Implementation plan

**One worker per follow-up PR**, each green on that worker's CI before the next starts. Per
worker, the task sequence is identical:

- [ ] **Bump the pin.** Edit `[tool.uv.sources]` → `rev = "<supported tag>"`; `uv lock`.
- [ ] **Run full gates immediately, before touching imports.** This isolates pure pin-bump
  breakage (API drift) from adoption breakage. Surface every failure the rev jump exposes —
  renames, the `obs` module→package change, signature changes — and fix imports/usages to the
  `v0.1.0` public surface. A worker on a further-behind rev (auto-hr) will surface more drift;
  budget for it.
- [ ] **Adopt shared modules** per the table above, one concern at a time, repointing each
  local import at the cockpit symbol.
- [ ] **Delete the local duplicates** (no re-export shims).
- [ ] **Gates green:** full `pytest` + `pre-commit run --all-files` for that worker.
- [ ] **Duplication grep clean** for that worker (see Acceptance).

### Ordering — consumers before emitters

`docs/pin-sync.md` states the rule: *update consumers before emitters when a wire shape
changes; the orchestrator is the first consumer because it bridges worker output across the
fleet.* Applying that here:

- [ ] **Phase A — Auto-Orchestrator (xops) first.** It consumes worker output (run logs, screen
  models, signals, handoff payloads) across the fleet, so it must understand the `v0.1.0`
  shapes before emitters start producing them. It is also the heaviest user of the signal
  bus/audit ledger, so it exercises the most shared surface — failures here are the cheapest to
  catch first.
- [ ] **Phase B — emitter / leaf workers**, in ascending order of drift so the simplest land
  first and de-risk the recipe: the `4c63daf` cohort (auto-admissions, auto-bookkeeper,
  auto-inspector, auto-marketer, auto-secretary, Auto-Procurer) before **auto-hr** (furthest
  behind, most drift). **xbook (auto-bookkeeper) is the money repo** — land it inside Phase B
  but give it the most scrutiny (full suite + safety AST invariants must stay green; per the
  audit its `enforce_admins` is also a separate governance gap — not this plan's job, but do not
  merge a red money-repo gate).

Reasoning on "first or last" for the cockpit-consumers: xops goes **first** (it must read the
new shapes before anyone emits them — the canonical consumers-before-emitters rule). xbook is an
*emitter* of `payment.required` and a consumer of nothing new in this sweep, so it sits in the
emitter phase, not first — but with money-repo scrutiny. There is no worker that should go
*last* for consumer reasons; "last" is simply "highest drift" (auto-hr).

## Acceptance criteria

- [ ] **All 8 workers pin the same supported release tag** (`v0.1.0`), each verifiable in its
  `[tool.uv.sources]`, with `uv.lock` resolved to the tag's commit. None on a bare SHA, none on
  `main`. (`docs/pin-sync.md`'s "max one minor version skew" holds trivially at zero skew.)
- [ ] **Local duplicates deleted** in every worker: no worker-local `runlog` / `google_auth` /
  config-loader / `gsheets` / `logsetup` / `uk_calendar` / signal emit+subscribe / `audit_log`
  copy remains; all such usages import from `clonway_cockpit.*`.
- [ ] **Full test suites green** on every worker's CI (`pytest` + `pre-commit run
  --all-files`), with safety/never-send/never-submit/never-order AST invariants intact where the
  worker has them.
- [ ] **Duplication grep is clean fleet-wide.** A grep for the extracted implementations'
  signatures across the worker repos returns only the cockpit dependency, not re-implementations
  (e.g. no second `def is_bank_holiday`, no second `class SheetsClient`, no local
  `make_runlog`). Record the grep used in each PR so the acceptance is reproducible.
- [ ] **The audit's weakness-#5 duplication is retired** — the ~1,000 lines exist once, in
  cockpit, depended-on by the fleet.

## Risks & dependencies

- **API drift across the rev gap is the headline risk.** Jumping from a stale SHA to the tag can
  cross renames and the `obs` module→package conversion; auto-hr (furthest behind) carries the
  most. Mitigation: the "run gates before touching imports" step isolates drift from adoption so
  the two failure modes don't tangle. **Re-survey live pins as step 0** — the survey table is
  dated 2026-06-11 and the follow-up notes auto-bookkeeper may already be on `main` HEAD; do not
  trust this doc's distances without re-running `git rev-list --count` against each worker's
  actual pin.
- **Staggered adoption is deliberate, not a smell.** One worker per PR means the fleet runs
  mixed pins mid-sweep. `docs/pin-sync.md` permits up to one minor version of skew; since every
  bump targets the same `v0.1.0`, transient skew is "tag vs old-SHA", which is within policy.
  Land xops (the consumer) first so it never reads a shape it doesn't understand.
- **Rollback is per-worker and cheap.** Each worker's bump+adoption is one PR on its own branch;
  reverting that PR restores the prior pin and the (git-history-preserved) local copies. No
  cross-worker coordination is needed to roll one back — another reason for one-worker-per-PR
  over a fleet-wide mega-PR.
- **A worker may need a framework change to adopt cleanly.** If adoption surfaces a genuine gap
  in the `v0.1.0` public surface (a missing parameter, an awkward seam), that is a **cockpit PR
  + new release tag first** (changelog-driven, per `CLAUDE.md`), then this plan resumes against
  the new supported line — do not work around it with a worker-local shim, which would re-create
  the duplication.
- **Depends on `v0.1.0` being intact and the release workflow having produced the tag** (it
  has — `git tag` shows `v0.1.0`). Independent of Wave 5 items 1/3/4; can proceed in parallel.

## Next-agent pickup

- **Claim one worker, open one branch.** Branch name: `claude/wave5-pin-adopt-<worker>` (e.g.
  `claude/wave5-pin-adopt-auto-hr`). Work in a git worktree, never the worker's main checkout.
- **Order:** take Auto-Orchestrator (xops) first if unclaimed; otherwise take the
  lowest-drift unclaimed `4c63daf`-cohort worker; leave **auto-hr last** (most drift) and give
  **auto-bookkeeper** money-repo scrutiny. Check the supported tag in `docs/pin-sync.md` at
  pickup time — target whatever line is current, not a baked-in `v0.1.0`.
- **Recipe per worker:** (1) re-survey the live pin; (2) bump per `docs/pin-sync.md` + `uv
  lock`; (3) run full gates *before* import changes and fix all API drift to the `v0.1.0`
  surface; (4) adopt modules per the Spec table, one concern at a time; (5) delete local copies
  (no shims); (6) gates green + duplication grep clean; (7) record the grep in the PR body.
- **PR:** open against the **worker's** repo (not cockpit), title `Wave 5 — adopt cockpit
  <tag> + delete local duplicates (<worker>)`, body listing the modules adopted, the files
  deleted, the API-drift fixes made, and the duplication grep used. One worker = one branch =
  one PR. This plan doc stays in cockpit as the shared contract all those PRs cite.
- **Do not** bundle the branch-protection work (Wave 5 item 1) or the xbook AP consumer (item 3)
  into a pin-adoption PR — they are separate plans.
