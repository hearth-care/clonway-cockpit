# [Plan] Signal emit factory + dedup-contract hardening

**Status:** draft plan — not implemented
**Source:** fleet audit 2026-06-11, items C12, C6
**Wave:** 1

## Why

The Signal layer is the fleet's only cross-worker contract in daily production use (every worker emits; the orchestrator's briefing and Fleet Cockpit consume). The emit *transport* was already extracted (`src/clonway_cockpit/signals/emit.py` — flag-gated, best-effort GCS flush; workers keep ~10-line wrappers). What was **not** hardened is signal *construction*, and the audit found two concrete failure modes, both verified in code at `dcda649`:

1. **Worker identity is not sealed (C12).**
   - `signals/model.py:171` — `build_signals(needs, *, now, worker: str = "xbook", ...)`: the worker id **defaults to `"xbook"`**. Any caller that forgets `worker=` silently emits another worker's identity into shared state.
   - `emit.py` takes `worker_id=` separately from the `Signal.worker` field baked in by `build(...)`: nothing stops the rows inside `signals/<worker_id>/latest.jsonl` claiming a different `worker` than the path they were written to — consumers keying on either would disagree.
   - Workers that build Signals directly (not via `build_signals`) import **private helpers** to do it: `Auto-HR/src/xhr/signals/build.py` does `from clonway_cockpit.signals.model import Signal, _dedup_key, _urgency_from_due_at` (verified at that repo's `origin/main`). Underscore-name imports across a pinned-rev dependency boundary mean any internal refactor here breaks a live prod worker with no deprecation path — and each worker re-derives the dedup recipe by hand.

2. **Title→kind drift degrades silently (C6).**
   - `model.py:35-62` — `_TITLE_KIND` is a hardcoded, exact-match, xbook-centric table ("Re-authenticate Xero", "Bills overdue", …). `model.py:67-68` — `_kind_for` falls back to `"action.required"` for *any* unknown title, by design, **with no warning, no counter, no strict mode**.
   - Consequences compound: `kind` misclassification skews the briefing's ranking; and because `title` is folded into `dedup_key` (`model.py:97-103` — `uuid5(worker|title|capability_key|focus|source_id)`), a renamed title mints a **new** dedup key, so the orchestrator's lifecycle layer (acks keyed by `dedup_key`) treats an already-acknowledged item as brand new — the audit's "daily duplicate signals" mode. Today the rename is discoverable only by an operator noticing the duplicate.

Both fixes belong here, not in workers: the contract lives in this repo, and eight wrappers cannot individually guarantee fleet-wide invariants.

## Scope

**In:**
- A sealed per-worker signal factory (construction + emission as one bound object).
- Public, supported equivalents of the private helpers workers currently import.
- Unknown-title observability: warn-once logging, an emit-time counter, an opt-in strict mode for worker CI.
- Per-worker title→kind extension (workers register their own titles instead of inheriting an xbook table).
- Removal of the `worker="xbook"` default (deprecation-staged).

**Out:**
- Wire-shape changes to `Signal.to_wire()` (consumers in prod; the wire is frozen here).
- Subscriptions / push delivery (companion plan `2026-06-fleet-audit-signal-bus.md`).
- The orchestrator's consumer-side lifecycle logic (its repo).
- Migrating the eight worker wrappers (per-repo follow-ups after a release tag).

## Spec

### 1. `SignalFactory` (C12) — `src/clonway_cockpit/signals/factory.py`

```python
@dataclass(frozen=True)
class SignalFactory:
    worker_id: str
    flag_env: str
    title_kinds: Mapping[str, str] = field(default_factory=dict)  # worker's titles
    strict_kinds: bool = False        # also via env CLONWAY_SIGNALS_STRICT_KINDS

    def make(self, *, title: str, detail: str, level: str,
             capability_key: str | None = None, focus: str | None = None,
             source_id: str | None = None, due_at: Date | None = None,
             now: datetime, kind: str | None = None,
             source_ref: str | None = None) -> Signal:
        """Seals worker (= self.worker_id, not a parameter), emitted_at (= now),
        urgency (from due_at/level via the public helper), dedup_key (computed
        internally — callers cannot pass one), and kind (explicit arg wins; else
        title lookup per §3; explicit kind must be in SIGNAL_KINDS)."""

    def from_needs(self, needs: tuple[NeedsItem, ...], *, now: datetime,
                   source_ref: str | None = None) -> tuple[Signal, ...]:
        """build_signals, with worker sealed."""

    def emit(self, *, build: Callable[..., Sequence[Signal]],
             now: datetime | None = None, **kw) -> tuple[Signal, ...]:
        """Delegates to signals.emit.emit_signals(worker_id=self.worker_id,
        flag_env=self.flag_env, ...) AND verifies every built Signal has
        .worker == self.worker_id — a mismatch raises SignalIdentityError
        from the build step (caught by emit_signals' existing never-crash
        guard in scheduled runs, but loud in tests and logs)."""
```

- A worker's whole `signals/emit.py` wrapper collapses to `FACTORY = SignalFactory("xhr", "XHR_EMIT_SIGNALS", title_kinds=...)` plus thin re-exports.
- **Public helpers** (same module or `model.py`): `dedup_key(worker, title, capability_key, focus, source_id)` and `urgency_from_due_at(due_at, level, now)` — exact current semantics (`_SIGNAL_NS` uuid5 recipe unchanged: existing dedup keys must not change values), with the underscore originals kept as deprecated aliases for one release.
- **`build_signals` default removal:** `worker: str = "xbook"` → required keyword. Staged: this release warns (`DeprecationWarning` when the default is used), next release removes. Changelog-flagged.

### 2. Identity sealing rules

- `make()` has no `worker`, `emitted_at`, or `dedup_key` parameters — sealed fields are not overridable (the point of the factory).
- `emit()`'s identity check covers the directly-built path too (workers building `Signal(...)` raw and handing tuples to emit get the same guarantee).
- Wire output of a factory-built Signal is byte-identical to today's path for the same inputs (golden test).

### 3. Title→kind: per-worker registration + fallback observability (C6)

Resolution order in `make()` / `from_needs()`:

1. explicit `kind=` argument (validated against `SIGNAL_KINDS`),
2. the factory's `title_kinds` mapping (worker-owned titles),
3. the framework `_TITLE_KIND` table (legacy/xbook + the generic forward titles),
4. fallback `"action.required"` — **now observable**:
   - `logging.getLogger(f"{worker_id}.signals").warning("unknown signal title %r → action.required", title)` — once per title per process (module-level seen-set; matches the warn-once idiom).
   - The emit log line gains a count: `unknown_title_kinds=N` (flows into worker logs that `obs` already ships).
   - **Strict mode** (`strict_kinds=True` or env `CLONWAY_SIGNALS_STRICT_KINDS` truthy): raise `UnknownSignalTitle` instead. Intended for worker *test suites and CI*, never prod (prod must keep the never-crash posture documented in `emit.py`).
- Dedup-vs-rename note (docs, same module docstring): a title rename is a **contract change** — the dedup key changes by design; the registration table plus strict CI makes the rename visible at PR time in the worker repo, which is the actual fix for the silent-duplicate mode. Consumers needing rename-survivable identity should set `source_id` (already folded into the key).

### 4. Worker-template

The template's generated `signals/emit.py` + `signals/build.py` switch to `SignalFactory` (template currently mirrors the manual wrapper) — new workers are born sealed.

## Implementation plan

### Phase 1 — public helpers + deprecation shims
- [x] Promote `_dedup_key` / `_urgency_from_due_at` to public names; keep underscore aliases emitting `DeprecationWarning`; pin test: public `dedup_key(...)` returns byte-identical values to current `_dedup_key` for a fixture matrix (the uuid5 recipe is frozen).
- [x] `build_signals` worker-default deprecation warning + test.
- Files: `src/clonway_cockpit/signals/model.py`, `tests/test_signal_model.py` (extended existing file; plan's plural filename did not exist).

### Phase 2 — `SignalFactory`
- [ ] `signals/factory.py` per Spec §1–2; golden wire test (factory vs current path, same inputs → identical `to_wire()` dicts); identity-mismatch test (`emit` with a foreign-worker Signal → `SignalIdentityError` surfaced via the build-failure path: emit returns `()`, exception logged); sealing tests (no override possible — API-shape asserted).
- Files: `src/clonway_cockpit/signals/factory.py`, `tests/test_signal_factory.py`.

### Phase 3 — title→kind observability
- [ ] Resolution order per Spec §3; warn-once test (two unknown emits, one log record); strict-mode raise test; emit-log counter test; `SIGNAL_KINDS` validation of explicit kinds.
- Files: `factory.py`, `model.py` (fallback hook), tests.

### Phase 4 — template + docs + changelog
- [ ] Worker-template `signals/*.jinja` → factory; `make template-smoke` green; template tests assert the generated build module imports no underscore names.
- [ ] Docs: `docs/onboarding-a-worker.md` signal section rewritten around the factory; migration recipe table (worker · wrapper file · title table to register · CI strict-mode line).
- [ ] Changelog `[Unreleased]`: new factory (additive), deprecations (warn), future default removal (notice).

## Acceptance criteria

- Golden tests prove: dedup-key values and `to_wire()` bytes are unchanged for all existing input shapes (zero consumer impact at pin-bump time).
- A factory caller cannot set `worker`, `emitted_at`, or `dedup_key` (TypeError on attempt — asserted).
- `emit()` of a Signal whose `.worker` mismatches the factory logs an exception and flushes nothing (and raises under pytest via strict assertion of the log).
- An unknown title produces exactly one warning per process per title, an `unknown_title_kinds` counter on the emit log line, and a raise under strict mode.
- Calling `build_signals` without `worker=` emits a `DeprecationWarning` (and the changelog states the removal release).
- Generated template worker uses the factory with zero underscore imports; `make check` + `make template-smoke` green.

## Risks & dependencies

- **Frozen wire/dedup invariants are the whole game:** any accidental change to the uuid5 namespace, the join string `f"{worker}|{title}|{capability_key}|{focus}|{source_id}"`, or `to_wire()` ordering breaks live consumer state (orchestrator acks). The golden fixture matrix must be written *first*, from current behaviour, before any refactor commit.
- **The HR worker's private imports** (`_dedup_key`, `_urgency_from_due_at`) mean this repo cannot delete those names until that worker (and any other — survey all eight at build time: `grep -rn "signals.model import" ../*/src ../*/xquill`) has migrated; deprecation aliases stay until the pin-sync advisory confirms.
- **Strict mode in prod by accident:** the env var read must be inside the factory (not module import time) and documented as CI-only; emit's never-crash posture is the prod guarantee either way.
- Cross-repo: eight wrapper migrations + per-worker title tables are follow-up PRs (after a release tag — depends on the release-engineering plan). The orchestrator may *additionally* want a consumer-side unknown-kind tolerance check — its repo, out of scope.
- Companion-plan coupling: the signal-bus plan (C15) consumes the same model; land this first (it freezes the construction contract subscriptions will rely on).

## Next-agent pickup

- Branch: `claude/signal-hardening` off `origin/main` of `hearth-care/clonway-cockpit`, fresh worktree.
- First commit: the golden fixture matrix capturing **current** dedup-key values and wire bytes (run against unmodified `model.py`). Everything else builds on that safety net.
- Then Phases 1→4 in order, TDD throughout; one PR, phase-per-commit.
- Run the eight-repo private-import survey before touching any underscore name; paste results in the PR description.
- Do NOT: change `Signal.to_wire()` or the dedup recipe in any way; remove `_TITLE_KIND` (it remains layer 3 of resolution); make strict mode the default anywhere; migrate worker wrappers from this branch; add identifiers to docs (public repo — note the shared bucket name already in source is referenced via `emit._BUCKET`, never re-stated in new docs).
- Done = acceptance criteria demonstrated, `make check` + `make template-smoke` green, changelog updated.

## HANDOFF NOTES

- Agent: builder-codex-20260612T022623Z.
- Current phase: Phase 2 — `SignalFactory`.
- Completed: rebuilt worktree from `origin/claude/plan-signal-hardening`; baseline `uv run pytest -q` passed (`758 passed in 15.10s`); baseline `pre-commit run --all-files` failed because `.pre-commit-config.yaml` is absent; Phase 1 tests were written red first, then public `dedup_key` / `urgency_from_due_at`, deprecated underscore shims, and the staged `build_signals()` default-worker warning were implemented.
- Verification: `uv run pytest tests/test_signal_model.py -q` -> `47 passed in 0.03s`.
- Decisions/deviations: used existing `tests/test_signal_model.py`; `tests/test_signals_model.py` named in the plan does not exist. `.claude/` was already ignored. No wire shape or dedup recipe changes were made.
- Next concrete step: write Phase 2 failing tests in `tests/test_signal_factory.py` for golden wire parity, sealed fields/API shape, and `emit()` identity mismatch.
- Known-failing tests: none after the Phase 1 focused run.
