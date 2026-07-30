# Stable public cockpit worker seams — implementation plan

> **Execution rule:** implement Tasks 1–7 in order with RED/GREEN/REFACTOR commits. Do not change
> shell/walk/telemetry behavior to make a public test convenient. Auto-Bookkeeper changes belong to
> downstream #1046, not this branch.

## Task 0 — Live release inventory

- [x] Rebase current `origin/main`; record exact base and zero-behind state.
- [x] Confirm #114/#115 remain orthogonal docs-only plans; list any newly merged public API.
- [x] Re-run the work-order private-consumer inventory against framework template and xbook #1046.
- [x] Run focused baseline from design §11 and record count/time.
- [x] If any public symbol now exists or private behavior changed, stop for root SOL amendment.
- [x] Record exact downstream #1046 branch/head; no xbook edit or dependency pin in Task 0.

## Task 1 — RED: pin the public API and compatibility behavior

**Modify:**

- `tests/test_shell.py`
- `tests/test_walk.py`
- `tests/test_obs.py`
- `tests/test_obs_package.py`
- `tests/test_render_facade.py`

**Create:**

- `tests/test_public_worker_api.py`

### Shell RED

- [x] Import exact shell names from design §4; expected RED is ImportError/AttributeError only.
- [x] `CallbackScreen` forwards two distinguishable renderables once/in order and propagates a
  callback exception.
- [x] `ShellSession` methods use the exact active Host/screen/key objects. Populate sentinel
  observer/authorization/audit/agent-input fields and prove none is replaced or dropped.
- [x] Host with session-aware pill/extra-key callbacks invokes them once with one active session and
  never invokes legacy callbacks; Host without them invokes the legacy callbacks exactly as today.
- [x] In `agent_mode=True`, a pulse pill invokes neither callback and emits the existing one
  `Sync skipped` model; mutation moving the session callback before refusal is RED.
- [x] Drive `open_capability` for reference card, normal walk/focus, agent observer, gated context,
  crashing walk and `ShellOut`; assert current usage/audit/human/model/failure semantics.
- [x] `emit_model` suppresses observer error and emits exactly once when healthy.
- [x] `show_and_wait` updates once then reads exactly one key; key-reader errors propagate.
- [x] Drive public Home/activate/need/Doctor wrappers through existing fixtures and assert current
  state, focus, selection and fix confirmation.
- [x] Mutation proof monkeypatches the private owner to a sentinel for every wrapper and proves the
  public function resolves it at call time rather than holding a stale alias.

### Walk/render RED

- [x] Public `present` picks `ctx.present` then console fallback; `emit` is best-effort;
  `await_key` reads zero/one; `first_blocked_remedy` keeps current order; constants equal.
- [x] `DEFAULT_HELP_LINES` is a tuple equal/identical to the current private compatibility value.
- [x] Gate/animation tests remain unchanged; public names add no second path.

### Obs RED

- [x] Pin exact `EventBufferScope`, `event_buffer`, `isolated_event_buffers` imports and package
  `__all__`; `_RUN_BUFFERS` remains absent.
- [x] Expected RED: names absent. Commit `test: pin public worker integration seams`.

## Task 2 — GREEN: expose shell and callback-screen seams

**Modify:**

- `src/clonway_cockpit/shell.py`
- `tests/test_shell.py`
- `tests/test_public_worker_api.py`

### Implementation

- [x] Add public constant/class/functions exactly as design §4 with typed explicit signatures.
- [x] Add the two default-`None` Host session callbacks and construct the session only at existing
  pill/extra-key dispatch points; no global active-host state or signature introspection.
- [x] Every function calls the existing private owner at runtime; do not copy a function body.
- [x] `open_capability` never accepts/exposes `_nav`; private shell calls remain unchanged.
- [x] Keep private names and current internal call graph for pinned-worker compatibility.
- [x] Update module docstring to name the public worker entry/nested seams.

### Verify

- [x] Run shell/public tests and the agent/gate/audit suites.
- [x] Mutation rows fail if focus/observer/agent authorization/audit/usage/ShellOut is lost.
- [x] Run legacy Host fixture matrix to prove callbacks/frames/keys unchanged when session hooks are
  absent; run session-aware nested-open rows to prove one observer-visible child frame.
- [x] Commit `cockpit: expose stable shell worker seams`.

## Task 3 — GREEN: expose walk and help-line seams

**Modify:**

- `src/clonway_cockpit/walk.py`
- `src/clonway_cockpit/render_panels.py`
- `tests/test_walk.py`
- `tests/test_render_facade.py`
- `tests/test_public_worker_api.py`

### Implementation and verify

- [x] Add public wrappers/constant from design §§5–6; private owners/aliases remain.
- [x] Update docstrings to describe public consumption; no gate/animation/render behavior change.
- [x] Run walk/render/contract/agent tests; compare public/private output/call counts for every row.
- [x] Commit `cockpit: expose stable walk and help seams`.

## Task 4 — GREEN: expose scoped event buffering without the ContextVar

**Modify:**

- `src/clonway_cockpit/obs/_telemetry.py`
- `src/clonway_cockpit/obs/__init__.py`
- `tests/test_obs.py`
- `tests/test_obs_package.py`
- `tests/test_public_worker_api.py`

### Implementation

- [x] Add frozen/slots `EventBufferScope`, validate worker ID, implement owner/nested/cross-worker
  state machine and isolation context exactly as design §7.
- [x] Use `ContextVar.set/reset` only inside these public context managers; never expose mapping or
  token.
- [x] Export exactly the three names and retain all prior `__all__` entries/order policy.
- [x] Do not rewrite `make_obs` to consume the new API in this PR; it remains the reference current
  behavior and shares the same private ContextVar.

### RED/GREEN matrix

- [x] owner fresh list; `make_obs().event` appends exact record;
- [x] nested same worker same object/owner false/no reset;
- [x] nested other worker separate object/both records/no clobber;
- [x] normal/Exception/KeyboardInterrupt/SystemExit reset;
- [x] `asyncio.CancelledError` resets an owner scope; cancellation inside a nested other-worker
  scope restores the exact outer mapping and list identities with no leaked binding;
- [x] nested `isolated_event_buffers` restores exact prior scope;
- [x] blank/non-string worker rejected before binding;
- [x] context copied into a child task/thread does not let reset corrupt the parent mapping.
- [x] Commit `obs: expose scoped worker event buffering`.

## Task 5 — Migrate the generated worker template

**Modify:**

- `worker-template/src/{{ package_name }}/cli/cockpit.py.jinja`
- `worker-template/src/{{ package_name }}/cli/home_hooks.py.jinja`
- `worker-template/README.md.jinja`
- `tests/test_worker_template.py`
- existing worker-template render/smoke tests

**Create:**

- `tests/test_worker_template_public_api.py`

### RED/GREEN

- [x] RED scans generated production Python/Jinja for the exact forbidden framework-private names
  in design §8 and proves the two current `_home` calls fail it.
- [x] RED asserts the current generated legacy `handle_extra_key(screen, read_key)` and `_host()`
  reconstruction guidance violate the active-session contract.
- [x] Replace both `_home` calls with `shell.run_home`; render a worker fixture and run its cockpit
  smoke/import.
- [x] Generate `handle_extra_key_with_session(state, selection, key, session: ShellSession)` and
  wire only `Host.handle_extra_key_with_session`; do not generate/wire the legacy hook.
- [x] Replace ambient `_host()` rebuild advice with public `ShellSession` helper guidance in the
  generated hook, cockpit host docstring and README.
- [x] Render/import a worker and assert the Host owns the exact generated session hook, retains the
  legacy framework default, and passes the exact sentinel active Host/screen/read-key through one
  claimed-key nested-helper test without constructing another Host.
- [x] Guard self-test feeds every forbidden spelling and accepted public equivalents.
- [x] Existing generated output outside the Home entry/hook/wiring/docs migration is byte-identical.
- [x] Commit `template: generate workers on public cockpit APIs`.

## Task 6 — Structural compatibility and independent consumer rehearsal

### Framework guard

- [x] Add a bounded AST/import inventory over `worker-template` and framework docs examples; no
  blanket private-name ban inside framework implementation/tests.
- [x] Assert old private symbols still exist and public wrappers call them; removal is a future
  coordinated major migration.
- [x] Assert legacy Host callbacks still work and the new session callback wins only when explicitly
  configured.
- [x] Assert no new public wrapper contains domain imports, effects or duplicated implementation.

### Downstream rehearsal (read-only to xbook)

- [x] Build/install this exact framework branch into an isolated throwaway environment, import all
  public names from an unmodified xbook checkout and instantiate `CallbackScreen`/`EventBufferScope`.
- [x] Do not claim xbook acceptance: #1046 must pin the merged SHA and run its real tests.
- [x] Record framework head and downstream rehearsal command/output in `HANDOFF NOTES`.
- [x] Commit `tests: guard public worker API compatibility` if guard changes remain.

## Task 7 — Full gates, docs and QA

- [ ] Run:

```bash
uv run pytest -q
uv run ruff check src tests worker-template
uv run ruff format --check src tests worker-template
uv run mypy
uv run pre-commit run --all-files
git diff --check
```

- [ ] Rebase on current main and rerun focused/full gates; never force-resolve #114/#115 semantics.
- [ ] Update work order/HANDOFF with RED proof, commits, exact counts and final head.
- [ ] Keep draft and hand exact head to independent architecture, acceptance, agent-parity,
  compatibility and telemetry-context QA.
- [ ] QA drives public paths, not merely checks imports; deliberately breaking each wrapper and
  buffer reset must make a named test RED.
- [ ] Link downstream Auto-Bookkeeper #1046; user value remains pending its exact merged-SHA pin.

## Independent QA rejection conditions

Reject if a public function copies logic, exposes `_NavStack`/ContextVar/token, changes
Rich/ScreenModel/gate/navigation/telemetry behavior, catches callback/ShellOut unexpectedly, leaves
the template on private names or the legacy Home hook, retains `_host()` reconstruction guidance,
rebuilds a Host inside a session path, invokes both legacy/session
callbacks, removes a private compatibility symbol, lacks BaseException/cross-
worker buffer proof, uses an editable path as consumer evidence, conflicts with #114/#115 ownership,
or claims product value before #1046 lands.

## HANDOFF NOTES

- Phase: Task 6 compatibility/rehearsal complete; Task 7 full gates/rebase/docs is next.
- Base: `origin/main@8694e302`; branch is zero commits behind. No public symbols from this plan
  exist on main, so no SOL amendment was required.
- Parallel plans: #114 (`1d4e9513`) and #115 (`ccf4a8ef`) remain open code-bearing PRs. Their
  Doctor/menu ownership remains orthogonal; no newly merged public API was found.
- Inventory: the generated cockpit still contains the two planned `shell._home` calls. The
  framework keeps its expected private owners and `_RUN_BUFFERS`; no unplanned template consumer
  was found. The #1046 diff still plans the named private-API and copied-adapter migration.
- Focused baseline: the design §11 command passed, `172 passed in 0.54s`.
- Blueprint QA: two independent read-only reviewers approved the final 856-line/82-gate package.
- Dependency: none. Parallel #114/#115 are orthogonal.
- Downstream: Auto-Bookkeeper #1046 remains draft on
  `claude/plan-preserve-agent-visibility-through-nested-walks@0580b8593`; no edit or pin was made.
- RED proof: `tests/test_public_worker_api.py` and `tests/test_obs_package.py` fail collection on
  absent `EventBufferScope`; isolated import probes also fail on absent shell, walk and help names.
- Task 2 verification: 15 focused public shell tests passed; 117 shell/agent/gate/audit tests
  passed. Legacy and opt-in session callback rows both passed.
- Task 3 verification: 2 focused public walk/help tests and 44
  walk/render/contract/agent tests passed.
- Task 4 verification: 67 public/obs/package tests passed, including BaseException,
  cancellation, nested isolation, cross-worker and copied-context rows.
- Task 5 RED: the generated-production guard reports `shell._home` and ambient agent-mode Host
  reconstruction guidance; its complete forbidden/public-equivalent self-test passes.
- Task 5 GREEN: 28 template structural/render/import/agent/smoke tests passed. Copier renders from
  committed HEAD, so the GREEN run used exact local commit `8c9e952`.
- Task 6 guards: 45 public/structural tests and 4 focused generated-worker AST/session tests
  passed. Public wrappers contain one runtime call to their retained private owner and no imports.
- Downstream rehearsal: built wheel from framework `a2b65271d3bec47547f78a8ba2df7e2238934267`,
  installed it (non-editable) into a fresh venv, and ran from a clean unmodified Auto-Bookkeeper
  checkout at `0580b8593c9529c543293b7a3e613ededd661429`. Importing every bound shell/walk/help/obs
  name and constructing `CallbackScreen`/`EventBufferScope` printed
  `downstream rehearsal: all public imports and constructors passed`. This is compatibility
  rehearsal only; #1046 still owns exact merged-SHA consumer acceptance.
- Known failing tests: none.
- Product value: pending implementation, independent QA, merge and downstream acceptance.
