# Agent parity — worker-modelled extra regions + unhandled-key frame re-emit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task (Claude: superpowers:subagent-driven-development or superpowers:executing-plans; Codex: follow the same phase/TDD/verification discipline). Steps use checkbox (`- [ ]`) syntax for tracking. Tick checkboxes as work lands and commit this plan with the code.

**Goal:** Two agent-parity gaps closed in the framework, additively. (a) A worker's `Host.extra_regions` home panels are today invisible to agent drivers — `model_cockpit_screen` records only their COUNT in `meta.extra_regions` (`render_models.py:114`). Add an optional `Host.extra_model_regions` hook whose returned model `Region`s are appended to the home `ScreenModel` after `toolkit`. (b) Over `agent.serve_stdio`, a keypress a screen's key loop ignores produces no redraw and therefore NO frame — the driver blocks until timeout (observed as a long driver hang on a worker screen whose loop ignored `enter`). Fix at the pump so every worker inherits it: after a `{"key":…}` dispatch that wrote no frame, re-emit the current screen's model. The reply to any key message is then always ≥1 frame.

**Architecture:** All framework-side, three seams. (1) `render_models.model_cockpit_screen` (pure model builder, `src/clonway_cockpit/render_models.py:53`) gains a keyword-only `extra_model_regions: list[MRegion] | None = None` and appends them after the `toolkit` region. (2) `shell.Host` (frozen dataclass, `src/clonway_cockpit/shell.py:108`) gains the optional hook field next to `extra_regions` (`shell.py:187`); the home loop's single draw site (`shell.py:424-437`) threads it into the model call. (3) `agent.serve_stdio` (`src/clonway_cockpit/agent.py:71`) already tracks `last: list[ScreenModel | None]` (`agent.py:106` — updated by the `on_screen` closure at `agent.py:115-117`, read by the `{"cmd":"snapshot"}` branch at `agent.py:146-148`); add a frames-written counter in `on_screen` and a dispatch mark in `read_key`, and re-emit `last[0]` at the top of `read_key` when the previous key dispatch advanced nothing. No worker code changes here — worker repos consume via a rev bump in a separate dependent plan PR.

**Tech Stack:** Python 3.12, `uv`, `rich` (existing). **No new dependencies.**

## Global Constraints

- **Additive protocol change only — NO `schema_version` bump.** Rationale (per `docs/agent-screen-model.md` "Protocol versioning", lines 187-195): the version bumps ONLY on a breaking wire change (removed/renamed key, changed type); additive keys do not bump it. Both deliverables are additive — appended regions in an existing `regions` list, and extra frames on the stream (the doc already says "treat app→agent as a stream"). `SCHEMA_VERSION` stays `"1.0"`; `tests/test_model.py::test_to_dict_carries_schema_version` (the shape pin, `tests/test_model.py:34`) must pass unmodified. Task 3 adds the "appending a region is additive" sentence to the doc.
- **Safety/behaviour invariants (HR3)** — each cell bound to a named test:

| # | State / path | Required behaviour | Proof test |
|---|---|---|---|
| I1 | Neither hook set (every existing worker) | home render byte-identical; home model dict-identical | existing `tests/test_shell.py::test_default_host_extras_are_noops` (unmodified) + new `test_home_model_without_extra_model_regions_is_unchanged` |
| I2 | `extra_model_regions` set | model regions are exactly `["pulse","needs","toolkit", <worker regions in order>]` | `test_home_model_appends_worker_model_regions_after_toolkit` |
| I3 | `extra_regions` set, `extra_model_regions` unset | `meta.extra_regions` == renderable count (unchanged); model still has exactly 3 regions; NOT a contract failure | `test_home_model_counts_renderables_not_model_regions` |
| I4 | inert key over `serve_stdio` | reply is exactly one re-emitted frame, byte-identical to the last draw | `test_inert_key_still_replies_with_a_frame` |
| I5 | handled key that redraws | exactly the drawn frame — no double emit | `test_handled_key_emits_one_frame_not_two` |
| I6 | `{"cmd":"quit"}` or `{"key":"q"}` | no re-emit; the session unwinds (EOF is the reply) | `test_quit_messages_emit_no_extra_frame` |
| I7 | `{"cmd":"snapshot"}` | behaviour unchanged | existing `tests/test_serve_stdio.py::test_snapshot_re_emits_current_screen_without_advancing` (unmodified) |
| I8 | wire shape | `schema_version` stays `"1.0"` | existing `tests/test_model.py::test_to_dict_carries_schema_version` (unmodified) |

- **HR4 N/A** — no money or durable-state writes anywhere in this plan; it touches framework rendering/model building and the stdio pump only. The write gate (`walk.confirm_apply`, the guarded-apply handshake in `agent.py:154-191`) is untouched; its tests (`tests/test_apply_authorization.py`, `tests/test_agent_dry_run.py`) must stay green unmodified.
- **Parity-guard decision (binding):** a worker that sets `extra_regions` without `extra_model_regions` is NOT a contract failure — workers adopt incrementally. `contract.assert_render_model_parity` is unaffected by construction (it is an AST check over `render_*`/`model_*` function names, `contract.py:70-94`; Host hooks are not render functions). `assert_drives_clean` cannot see the gap either (an unmodelled extra panel emits no `unstructured` frame — the home model simply omits it). A future drives-clean-style helper MAY warn on `extra_regions`-without-`extra_model_regions`; building that helper is explicitly OUT OF SCOPE here. Task 3 states all of this in the protocol doc.
- **Raising-hook posture:** `extra_model_regions` is called at the same point and with the same (lack of) guarding as the existing `extra_regions` (`shell.py:426`) — a raising worker hook fails the draw exactly as `extra_regions` does today. No new speculative guard (repo code style).
- No operator-facing step changes — **no RUNBOOK DELTA**. This repo has no operator runbook beyond `docs/agent-screen-model.md`, which is the protocol doc AND the repo's runbook analogue; the REQUIRED Task 3 update to it discharges HR1. The human TUI is byte-identical throughout (I1).
- **Depends on: no unmerged dependencies.** No wave tag. (A worker repo consumes this via a rev bump in a separate, dependent plan PR — do not build any worker code here.)
- CI note for the builder: this repo's CI runs on PR events only when the PR carries the `run-ci` label (`.github/workflows/ci.yml:19-24`).
- Gates (HR2 — the exact canonical commands QA re-runs; paste real output tails): `make lint` (= `uv run ruff check .`), `make format` (= `uv run ruff format --check .`), `make typecheck` (= `uv run mypy src`), `make test` (= `uv run pytest -q`). `make check` runs all four; CI (`.github/workflows/reusable-ci.yml`) runs the identical raw commands.

---

### Task 1: `Host.extra_model_regions` hook + `model_cockpit_screen` merge

**Files:** Modify `src/clonway_cockpit/shell.py`, `src/clonway_cockpit/render_models.py`; test `tests/test_screen_models.py`, `tests/test_shell.py`. (`render.py:68` already re-exports `model_cockpit_screen`; a keyword-only addition needs no facade change.)

**Production call site (HR9):** the home loop's draw block, `shell.py:424-437` — the only production caller of `model_cockpit_screen` (`_safe_emit(host, r.model_cockpit_screen(...))` at `shell.py:435-437`). The hook is wired there in this task, not left as a dead parameter.

**Interfaces produced/changed:** `Host.extra_model_regions: Callable[[CockpitState], list[Region]] | None = None` (new optional field; `Region` is `clonway_cockpit.model.Region`); `model_cockpit_screen(..., extra_model_regions: list[MRegion] | None = None)`.

- [x] **Step 1: Write the failing tests.** Append to `tests/test_screen_models.py` (helpers `_PILLS`, `render`, `CockpitState` already imported there):
```python
def test_home_model_appends_worker_model_regions_after_toolkit():
    from clonway_cockpit.model import Field as MField, Region as MRegion, Row as MRow

    state = CockpitState(tenant_name="Example Care", app_label="worker")
    worker_region = MRegion(
        "worker.bills",
        "example bills",
        rows=[
            MRow(
                id="bill:B-1",
                label="Example bill",
                fields=[MField("amount", "100.00", "currency")],
            )
        ],
    )
    m = render.model_cockpit_screen(
        state, [], selection=None, extra_regions=None, extra_model_regions=[worker_region]
    )
    assert [reg.role for reg in m.regions] == ["pulse", "needs", "toolkit", "worker.bills"]
    assert m.regions[3].rows[0].id == "bill:B-1"
    assert m.meta["extra_regions"] == 0  # meta counts RENDERABLES, not model regions


def test_home_model_without_extra_model_regions_is_unchanged():
    state = CockpitState(tenant_name="Example Care", pills=_PILLS)
    base = render.model_cockpit_screen(state, [], selection=None, extra_regions=None)
    off = render.model_cockpit_screen(
        state, [], selection=None, extra_regions=None, extra_model_regions=None
    )
    assert base.to_dict() == off.to_dict()
    assert [reg.role for reg in base.regions] == ["pulse", "needs", "toolkit"]


def test_home_model_counts_renderables_not_model_regions():
    from rich.text import Text

    state = CockpitState(tenant_name="Example Care")
    m = render.model_cockpit_screen(
        state, [], selection=None, extra_regions=[Text("RENDER-ONLY PANEL")], extra_model_regions=None
    )
    assert m.meta["extra_regions"] == 1
    assert [reg.role for reg in m.regions] == ["pulse", "needs", "toolkit"]
```
  Append to `tests/test_shell.py` (helpers `_host_with_extras`, `_keys`, `_Screen`, `usage_to_tmp` already defined there):
```python
def test_home_emits_worker_model_regions(usage_to_tmp):
    from dataclasses import replace

    from clonway_cockpit.model import Region as MRegion, Row as MRow

    captured = []
    state = CockpitState(tenant_name="Example Care")
    host = replace(
        _host_with_extras(state=state),
        extra_model_regions=lambda s: [
            MRegion("worker.example", "example", rows=[MRow(id="example:0", label="Example row")])
        ],
        on_screen=captured.append,
    )
    shell.run_cockpit(host, read_key=_keys(["q"]), screen=_Screen())
    home = captured[0]
    assert home.kind == "home"
    assert [reg.role for reg in home.regions] == ["pulse", "needs", "toolkit", "worker.example"]
```
- [x] **Step 2: Run the focused tests and confirm the expected failures**
Command: `uv run pytest tests/test_screen_models.py -q -k "model_regions or counts_renderables" && uv run pytest tests/test_shell.py::test_home_emits_worker_model_regions -q`
Expected failures: `TypeError: model_cockpit_screen() got an unexpected keyword argument 'extra_model_regions'` (first three); `TypeError: … got an unexpected keyword argument 'extra_model_regions'` from `dataclasses.replace` (fourth — the Host field doesn't exist yet).
- [x] **Step 3: Implement AND wire at the call site.**
  1. `shell.py:35`: extend the import to `from clonway_cockpit.model import Region, ScreenModel`.
  2. `shell.py` after the `extra_regions` field (`shell.py:187`), inside `Host`:
```python
    # Model twin of ``extra_regions``: the worker returns ready-made model Regions
    # (clonway_cockpit.model.Region) for its extra home panels; they are appended to
    # the home ScreenModel's regions after "toolkit". None (the default) keeps the
    # panels render-only — agents see only the ``meta.extra_regions`` count.
    extra_model_regions: Callable[[CockpitState], list[Region]] | None = None
```
  3. `shell.py:424-437` draw block — compute once, thread into the model call only:
```python
            extra = host.extra_regions(state)
            extra_models = (
                host.extra_model_regions(state) if host.extra_model_regions is not None else None
            )
```
  and change the `_safe_emit` call to `r.model_cockpit_screen(state, caps, selection=items[sel], extra_regions=extra, extra_model_regions=extra_models)`. `render_cockpit_screen` is untouched.
  4. `render_models.py:53-64`: add the keyword-only parameter `extra_model_regions: list[MRegion] | None = None`; update the docstring sentence at lines 62-64 (worker renderables are counted in `meta`; `extra_model_regions` is how the worker makes them structured). Replace the inline `regions=[...]` list in the `ScreenModel(...)` construction (`render_models.py:118-125`) with:
```python
    regions = [
        MRegion("pulse", "pulse", rows=pulse_rows),
        MRegion("needs", "needs you", rows=needs_rows),
        MRegion("toolkit", state.toolkit_label, rows=toolkit_rows),
    ]
    regions.extend(extra_model_regions or [])
```
  and pass `regions=regions`. `meta["extra_regions"]` stays `len(extra_regions or [])` (I3). Append-after-toolkit (not the render's between-needs-and-toolkit position) is deliberate: the three framework regions keep stable indices for existing agent scripts; region order in the model is not a position contract — agents key on `role`/`Row.id` (Task 3 documents this).
- [x] **Step 4: Run focused verification**
Command: `uv run pytest tests/test_screen_models.py tests/test_shell.py -q`
Expected pass signal: all passed, zero failures (existing I1 regression `test_default_host_extras_are_noops` included).
- [x] **Step 5: Commit**
Commit message: `shell+render_models: worker-modelled extra home regions (Host.extra_model_regions)`

### Task 2: `serve_stdio` frame-per-key re-emit

**Files:** Modify `src/clonway_cockpit/agent.py`; test `tests/test_serve_stdio.py`.

**Production call site (HR9):** the `read_key` closure inside `serve_stdio` (`agent.py:119-152`) — the loop's only stdin dispatch seam — plus the `on_screen` closure (`agent.py:115-117`). Every nested screen loop (home, shelf menu, walks, doctor) blocks through this one `read_key`, so the fix covers every worker screen with no per-worker code.

**Interfaces produced/changed:** none public — internal pump behaviour. Wire guarantee: any `{"key":…}` message is answered by ≥1 frame.

- [x] **Step 1: Write the failing test + guards.** Append to `tests/test_serve_stdio.py` (helpers `_host`, `_drive` at `tests/test_serve_stdio.py:20-41`). The first test is red-first; the second and third pass on old code and are guards pinning I5/I6 against an over-eager re-emit implementation — state this in the commit.
```python
def test_inert_key_still_replies_with_a_frame():
    # 'z' is not a shelf letter (default SHELVES = A-G) nor any home hotkey, so the
    # home loop ignores it with no redraw (shell.py "else: continue"). The pump must
    # still answer with the current screen — a driver must never block on silence.
    state = CockpitState(tenant_name="Example Care")
    frames = _drive(_host(state), [{"key": "z"}, {"key": "q"}])
    homes = [f for f in frames if f.get("kind") == "home"]
    assert len(homes) == 2, [f.get("kind") for f in frames]
    assert homes[0] == homes[1]  # a re-emit of the SAME model, not a new draw


def test_handled_key_emits_one_frame_not_two():
    # 'down' moves the cursor -> the loop redraws. Exactly ONE new frame (the redraw).
    state = CockpitState(tenant_name="Example Care")
    frames = _drive(_host(state), [{"key": "down"}, {"key": "q"}])
    homes = [f for f in frames if f.get("kind") == "home"]
    assert len(homes) == 2, [f.get("kind") for f in frames]
    assert homes[0]["selection"] == "shelf:A"  # boot cursor: first shelf (no pills/needs)
    assert homes[1]["selection"] == "shelf:B"


def test_quit_messages_emit_no_extra_frame():
    state = CockpitState(tenant_name="Example Care")
    for quit_msg in ({"cmd": "quit"}, {"key": "q"}):
        frames = _drive(_host(state), [quit_msg])
        assert [f.get("kind") for f in frames] == ["home"], frames
```
- [x] **Step 2: Run the focused tests and confirm the expected failure**
Command: `uv run pytest tests/test_serve_stdio.py -q -k "inert_key or one_frame_not_two or no_extra_frame"`
Expected failure: `test_inert_key_still_replies_with_a_frame` fails `assert len(homes) == 2` with `AssertionError: ['home']` (the inert key produced no frame). The two guards pass.
- [x] **Step 3: Implement the minimal pump change.** In `serve_stdio` (`agent.py:106-152`): add two one-cell trackers beside `last`; count draws in `on_screen`; mark key dispatches; re-emit at the top of `read_key`. Exact deltas (builders paste verbatim; surrounding code unchanged):
```python
    last: list[ScreenModel | None] = [None]
    frames_written = [0]  # draws written via on_screen — the no-draw detector
    key_mark = [-1]  # frames_written value when the last {"key":…} was dispatched; -1 = none

    def on_screen(model: ScreenModel) -> None:
        last[0] = model
        frames_written[0] += 1
        _write(model.to_dict())

    def read_key() -> str:
        # Frame-per-key guarantee: if the PREVIOUS dispatched key produced no draw
        # (the screen's key loop ignored it), re-emit the current model so the reply
        # to any {"key":…} is >=1 frame — a driver never blocks on a silent key.
        # A key that drew advances frames_written (no double emit); a key that
        # unwound the loop never re-enters here (EOF is that reply); cmd:"quit"
        # never sets key_mark.
        if key_mark[0] == frames_written[0] and last[0] is not None:
            _write(last[0].to_dict())
        key_mark[0] = -1
        while True:
```
  and in the existing `"key" in msg` branch (`agent.py:139-144`), set the mark just before returning:
```python
                key_mark[0] = frames_written[0]
                return key
```
  The `{"cmd":"quit"}` branch (`agent.py:150-151`) and EOF path (`agent.py:124-125`) return `"q"` WITHOUT setting `key_mark` — that is the no-emit-on-quit guard (I6). The re-emit writes via `_write`, not `on_screen`, so it neither bumps `frames_written` nor rewrites `last` — same frame shape as the `snapshot` branch (`agent.py:146-148`). `authorize_apply` / `agent_input` / `agent_confirm` read stdin directly mid-dispatch; any frames they trigger flow through `on_screen` and advance the counter, which is exactly right.
- [x] **Step 4: Run focused verification**
Command: `uv run pytest tests/test_serve_stdio.py tests/test_agent_hardening.py tests/test_agent_capture_input.py tests/test_apply_authorization.py tests/test_cockpit_client.py -q`
Expected pass signal: all passed, zero failures (the apply-handshake and capture suites prove the mark logic doesn't leak into the gate/capture reads).
- [x] **Step 5: Commit**
Commit message: `agent: serve_stdio re-emits the current frame after a no-draw key dispatch`

### Task 3: protocol doc update (REQUIRED) + parity-guard statement

**Files:** Modify `docs/agent-screen-model.md`; one line in `docs/onboarding-a-worker.md`.

**Production call site (HR9):** n/a — documentation of behaviour shipped in Tasks 1-2; `docs/agent-screen-model.md` is this repo's protocol doc and runbook analogue (HR1 discharged here; no other operator-facing runbook exists).

- [ ] **Step 1-3 (doc-only; no failing test):** make exactly these four edits:
  1. **Cadence paragraph** (the "Cadence:" paragraph in "Subprocess protocol — `agent.serve_stdio` (M2)", `docs/agent-screen-model.md:141-144`): replace the sentence "Inert keys may not redraw (use `snapshot` to re-poll);" with: "Every `{"key":…}` message is answered by ≥1 frame: a handled key emits its redraw; a key the screen's loop ignores re-emits the current screen unchanged, so a driver never blocks on a silent key. A key that unwinds the cockpit (`q`/`esc` at home) ends the session — EOF is that reply;".
  2. **Protocol versioning** section (`docs/agent-screen-model.md:187-195`): append: "Appending a new region to an existing screen's `regions` list (e.g. a worker's `extra_model_regions` on `home`) is likewise additive and does not bump the version."
  3. **New subsection** "Worker home panels: `Host.extra_model_regions`" (after "Wiring a worker to the agent channel") stating: the hook is the model twin of `Host.extra_regions`; returned `Region`s are appended after `toolkit` (region order in the model is not a position contract — the three framework regions keep stable indices; agents key on `role`/`Row.id`; the human render places the panel between needs-you and toolkit); `meta.extra_regions` remains the RENDERABLE count; setting `extra_regions` without `extra_model_regions` leaves that panel agent-invisible and is NOT a contract failure (`assert_render_model_parity` checks `render_*`/`model_*` function twins, not Host hooks; `assert_drives_clean` emits no `unstructured` for it) — workers adopt incrementally, and a future drives-clean-style helper may warn.
  4. `docs/onboarding-a-worker.md:548` (the `extra_regions(state)` bullet): add the sibling bullet "`extra_model_regions(state)` for the model twins of those panels — set both, or the panel is invisible to agent drivers."
- [ ] **Step 4: Verify** the doc-truth suites still pass.
Command: `uv run pytest tests/test_docs_delivery_truth.py tests/test_adoption_playbook_docs.py -q`
Expected pass signal: all passed.
- [ ] **Step 5: Commit**
Commit message: `docs: agent protocol — worker model regions + frame-per-key guarantee`

### Task 4: full gates

**Files:** none new — run the canonical gates and paste output tails into the PR.

- [ ] **Step 1:** `make lint` — expected tail: `All checks passed!`
- [ ] **Step 2:** `make format` — expected tail: `N files already formatted` (no reformat needed).
- [ ] **Step 3:** `make typecheck` — expected tail: `Success: no issues found in N source files`.
- [ ] **Step 4:** `make test` — expected tail: `N passed` with zero failures (full suite; includes the unmodified I1/I7/I8 regressions).
- [ ] **Step 5: Commit** (this plan file with all boxes ticked). Commit message: `plan: tick cockpit agent-parity plan`

---

## Self-Review

- Spec coverage: deliverable (a) → Task 1 (hook + merge + wiring at `shell.py:424-437`); deliverable (b) → Task 2 (pump re-emit); protocol doc + parity-guard statement → Task 3; gates → Task 4.
- Safety invariants: I1-I8 each name their proof test (table above). HR4 N/A — no money/durable-state writes; the write gate is untouched and its suites run unmodified in Task 2 Step 4.
- Tests are load-bearing: `test_inert_key_still_replies_with_a_frame` fails on old code (`['home']`); the Task 1 tests fail with `TypeError` on old signatures; the two Task 2 guards are explicitly declared green-on-old-code pins for I5/I6 (they fail on a double-emit or emit-on-quit implementation).
- Wired end-to-end: `extra_model_regions` is threaded at the home loop's only draw site in the same task that adds it (no dead parameter); the re-emit lives inside the production `read_key` closure every screen loop blocks through.
- Gates: `make lint` / `make format` / `make typecheck` / `make test` (identical to `.github/workflows/reusable-ci.yml`); output tails pasted in Task 4.
- Docs/runbook: no operator-facing step change → no RUNBOOK DELTA; `docs/agent-screen-model.md` (the repo's runbook analogue) update is the REQUIRED Task 3.
- Deferred items: the optional drives-clean-style warning helper for `extra_regions`-without-`extra_model_regions` (stated out of scope); the worker-repo adoption rev bump (separate dependent plan PR).

## HANDOFF NOTES

- Current phase: Task 1 DONE (`74ede0b`) and Task 2 DONE (`e4e4d4a`). Starting Task 3 (doc-only).
- Next concrete step: Task 3 Steps 1-3 (four edits to `docs/agent-screen-model.md` + `docs/onboarding-a-worker.md`).
- Decisions taken (binding, do not relitigate): append model regions AFTER `toolkit`; `meta.extra_regions` stays the renderable count; NO `schema_version` bump (additive); no contract-gate hard failure for render-only extra panels; re-emit implemented at the pump (`read_key` seam), not per-screen.
- Known failing tests: none — full suite green (`uv run pytest -q` → 1121 passed) after Task 1 + Task 2.
- Dependencies/operator TODOs: none — no unmerged dependencies. Remember this repo's CI needs the `run-ci` label on the PR.
