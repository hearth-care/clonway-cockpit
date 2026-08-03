# Menu input parity — Fleet Foundry implementation plan

> **Builder instruction:** execute in order on this PR branch. Each task begins with a load-bearing
> RED and ends with focused GREEN plus a commit. Do not implement an xbook-local shell fork.

**Goal:** root Backspace stays in-session and every advertised shelf action is one human/agent-
equivalent key.

**Binding design:** `docs/superpowers/specs/2026-07-12-menu-input-parity-design.md`

**Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`

## Task 1 — RED/GREEN: make root Backspace a real no-op

**Modify first:** `tests/test_shell.py`, `tests/test_agent_driver.py`.

- [x] Replace/amend the misleading back-from-walk test so the script actually presses Backspace,
  then a second observable action, then q.
- [x] RED: empty-stack root Backspace followed by Down/Enter remains in one run; assert frame/capture/
  activation counts and final q exit.
- [x] RED: two root Backspaces followed by a valid action; neither exits or recaptures.
- [x] RED: `serve_stdio` receives `backspace`, snapshot and quit; assert a post-Backspace Home frame,
  valid JSON and clean exit rather than early EOF. (Landed in `tests/test_serve_stdio.py`, not
  `test_agent_driver.py` — that's the file that actually exercises `serve_stdio`; see deviation note
  in HANDOFF NOTES.)
- [x] Preserve non-empty back-pop cursor, nested shelf/filter Backspace and q/Esc quit tests.
- [x] Record RED: current `_home` returns from the only top-level call.
- [x] Change only the empty-stack branch to `continue`; keep real-frame recursion/return.
- [x] Run focused GREEN and commit: `fix(shell): keep root backspace in session`.

## Task 2 — RED/GREEN: normalize stable menu items and tokens

**Modify first:** `tests/test_screen_models.py`, `tests/test_screen_models_rest.py`,
`tests/test_render_primitives.py`, new `tests/test_menu_input_parity.py`.

- [x] Specify `MenuItem` validation and legacy tuple normalization.
- [x] Matrix sizes 2/9/10/16/capacity/capacity+1 and assert exact shortcut sequence.
- [x] Prove ordinal row IDs/selection are unchanged and shortcut is a separate field/fact.
- [x] Prove Rich and model advertise the same non-None tokens; all are one character, unique and
  exclude q/control/semantic key names.
- [x] Prove overflow renders no fake token and remains selected/arrow-addressable.
- [x] Record RED: current option 10 renders/advertises `10`.
- [x] Implement additive `MenuItem`, normalizer and deterministic alphabet. Keep legacy tuple API.
- [x] Make render/model consume normalized items once. Do not change wire schema.
- [x] Run focused GREEN and commit: `feat(menu): assign human-enterable action tokens`.

## Task 3 — RED/GREEN: route current tokens and legacy aliases once

**Modify first:** `tests/test_shell.py`, `tests/test_menu_input_parity.py`.

- [x] Register 16 unique capabilities and spy on `_open_capability` public effects (usage/audit/run).
- [x] Press each displayed token; assert exact ordinal capability opens once.
- [x] Prove `a` opens item 10, `g` opens item 16 and q returns.
- [x] Prove human-shaped `1`,`0` never combines into item 10.
- [x] Prove agent-shaped legacy `"10"` opens item 10 for compatibility but is absent from actions.
- [x] Drive unknown/reserved/uppercase/duplicate/malformed values and overflow Arrow/Enter behavior.
- [x] Preserve single-spec direct open, Home need digits, shelf letters, back row and effect gates.
- [x] Replace primary `key.isdigit()` dispatch with one normalized shortcut map plus the narrow
  multi-character ordinal compatibility branch.
- [x] Run focused GREEN and commit: `fix(menu): share one rendered and dispatched action map`.
  (Landed in the SAME commit as Task 2 — `feat(menu): assign human-enterable action tokens` — since
  `_shelf()` needed the MenuItem/alphabet to be testable end-to-end; see HANDOFF NOTES.)

## Task 4 — RED/GREEN: let workers declare Home action facts

**Modify first:** `tests/test_model.py`, `tests/test_screen_models.py`, new focused state/model tests.

- [x] RED legacy constructor matrix plus empty action declarations; preserve every positional field.
- [x] RED state with `home_actions=("z",)` and Needs `actions=("enter", "z")`; assert global/row
  facts, order, dedupe and selection without changing other fields.
- [x] Matrix duplicates, whitespace/control/invalid types and collisions with base actions. Invalid
  worker hints cannot crash Home or remove framework actions.
- [x] Implement additive `NeedsItem.actions` and `CockpitState.home_actions`; normalize only in the
  pure model projection. Do not import worker code or add callbacks/I/O.
- [x] Assert workers with empty defaults remain model-shape compatible.
- [ ] Use xbook #1015's worktree/candidate pin to drive real active/deferred `z`; assert the
  declaration matches handler behavior and only the reversible local park store changes.
  BLOCKED — the exact candidate framework passes xbook's real reversible park/wake handler/store
  tests (`4 passed, 63 deselected`), but Auto-Bookkeeper #1015 is still an unmerged plan and its
  production state does not populate `home_actions` / per-row `actions`. The declaration-to-handler
  acceptance cannot pass until that consumer implementation exists. See HANDOFF NOTES.
- [x] Commit: `feat(model): expose worker-declared home actions`.

## Task 5 — contract, agent and real-shape acceptance

- [x] Drive a 16-item framework host through human-shaped injected keys and `serve_stdio`; compare
  ordered titles, row IDs, shortcuts, actions, selection and exact opened capability.
- [x] Assert no `unstructured` frames, no frame-per-key timeout and no early process exit.
- [x] Assert usage/audit open exactly once and any nested write still reaches existing gate/default
  denial; navigation itself creates no completion receipt.
- [x] Run contract/model shape tests and old-agent legacy alias regression.
- [x] Create a temporary consumer install/pin or use Auto-Bookkeeper #1014/#1015 worktrees after
  this branch is published; drive the real 16-item shelf, root Backspace and `z` facts without live
  provider/accounting effects.
  PARTIAL — a temporary `PYTHONPATH` candidate load imported this exact branch, loaded
  Auto-Bookkeeper main's real ordered shelf-G catalog, and passed 32/32
  `{human, stdio} × {1..9,a..g}` route cells with inert run-body substitutions plus real stdio
  root-Backspace liveness. No provider/accounting effect ran. The `z` facts half remains blocked
  as described in Task 4 because the consumer declaration implementation does not exist yet.
- [x] Rebase against #114 if it merged; resolve shell/model overlap semantically and rerun Doctor
  remedy tests. It is not a product dependency. (#114 is still open/unmerged at the time of this
  implementation — nothing to rebase against yet. Per the design doc §9 it is explicitly orthogonal
  and neither PR blocks the other; this PR proceeds independently.)
- [ ] Run independent acceptance, architecture, agent-parity, security and operability QA; fix all
  blockers and rerun.
  Independent Foundry QA runs after this PR flips to `agent:needs-qa` — not something the builder
  self-certifies.
- [x] Commit: `test(menu): prove human and agent navigation parity`.

## Task 6 — gates, consumer handoff and release

- [x] Run at minimum:

  ```text
  uv run pytest -q \
    tests/test_shell.py \
    tests/test_menu_input_parity.py \
    tests/test_screen_models.py \
    tests/test_screen_models_rest.py \
    tests/test_render_primitives.py \
    tests/test_model.py \
    tests/test_state.py \
    tests/test_agent_driver.py \
    tests/test_contract.py
  uv run ruff check src tests
  uv run ruff format --check src tests
  uv run mypy
  uv run pytest -q
  uv run pre-commit run --all-files
  git diff --check
  ```

  (`tests/test_state.py` does not exist in this repo — deviation: the worker-declared home-action
  tests landed in the new `tests/test_home_actions.py` instead; `tests/test_serve_stdio.py` was
  added to the focused run since that's the file that actually exercises `serve_stdio`, not
  `test_agent_driver.py`. See HANDOFF NOTES.)
- [x] Update framework docs only if the advertised menu action grammar is documented; record the
  exact token alphabet, overflow and legacy agent alias. (`docs/agent-screen-model.md` — new
  "Shelf menu action tokens" section; `model.py`'s Row.id docstring updated `option:<key>` →
  `option:<ordinal>`.)
- [x] Update HANDOFF NOTES with RED/GREEN commits, final symbols, compatibility/shape verdict,
  Auto-Bookkeeper real-shape proof, gates and independent QA.
- [x] Push and verify live head/diff/mergeability/checks; hand to independent Foundry QA.
- [ ] On merge, post exact merge SHA to Auto-Bookkeeper #1014/#1015. The consumers coordinate one
  pin and own deployed xbook observations. NOT DONE — this PR has not merged yet (builders never
  merge; independent QA + the operator do). Whoever merges this PR should post the merge SHA to
  #1014/#1015 per the design doc, or re-dispatch a follow-up to do so.

## HANDOFF NOTES

- **Status:** QA fixer findings 1–5 addressed; finding 6 is blocked on the missing consumer
  declaration implementation and needs operator resolution of the cross-PR ordering cycle.
- **Commits (RED/GREEN per task), on `Codex/menu-input-parity-plan`:**
  - `fix(shell): keep root backspace in session` — Task 1.
  - `feat(menu): assign human-enterable action tokens` — Tasks 2 **and** 3 combined (see
    deviation below).
  - `feat(model): expose worker-declared home actions` — Task 4.
  - `test(menu): prove human and agent navigation parity` — Task 5.
  - This doc/checkbox/HANDOFF-NOTES update — Task 6.
- **Final symbols:**
  - `clonway_cockpit.render_chrome.MenuItem` (frozen dataclass: `ordinal`, `title`, `summary`,
    `shortcut`), `MENU_SHORTCUT_ALPHABET` (34 slots: `1`-`9` then `a`-`z` excluding `q`),
    `assign_menu_shortcuts(n)`, `normalize_menu_items(options)` — all re-exported via
    `clonway_cockpit.render`.
  - `render_menu`/`model_menu` now take `Sequence[MenuItem | tuple[str,str,str]]` (legacy tuples
    still accepted, normalized once at the boundary).
  - `shell._shelf()` builds `MenuItem`s directly and dispatches through one `by_shortcut` map
    (normalized to lowercase) plus a narrow multi-character-digit legacy ordinal alias branch.
  - `state.NeedsItem.actions: tuple[str, ...] = ()` (appended last, after `source_id`) and
    `state.CockpitState.home_actions: tuple[str, ...] = ()` (appended last, after `breadcrumb`).
  - `render_models._normalize_actions`, `_needs_row_fields` — the normalize/merge helpers behind
    the worker-declared Home action facts.
- **Compatibility/shape verdict:** additive throughout — `SCHEMA_VERSION` unchanged (still
  `"1.0"`), the `test_to_dict_carries_schema_version` shape-pin test untouched and green, every
  existing positional/keyword construction of `NeedsItem`/`CockpitState`/menu tuples still works.
  Row ids stay `option:<ordinal>` (never the shortcut). Legacy multi-character digit aliases
  (e.g. `"10"`) still open the right capability but are never advertised.
- **Auto-Bookkeeper real-shape proof:** a candidate-source load against Auto-Bookkeeper main
  imported this worktree's `clonway_cockpit`, loaded the production ordered shelf-G catalog
  (`config`, `resident-lifecycle`, `connections`, `doctor`, `rooms`, `direct-debits`,
  `prepayments`, `loans`, `onboard-resident`, `admitted-events`, `occupancy-sync`,
  `occupancy-create-contacts`, `reauth`, `connect-lloyds`, `connect-revolut`, `setup`) and passed
  32/32 `{human, stdio} × {1..9,a..g}` exact route cells with inert run-body substitutions. Real
  stdio root Backspace remained live. Separately, the production xbook handler/store tests pass
  against this candidate (`4 passed, 63 deselected`). Consumer metadata still pins pre-PR
  `8694e302`; per design §9, #1014 updates that pin after this framework merges.
- **Gates (this session, on this branch's HEAD):**
  - `uv run pytest -q` (focused list from Task 6, substituting `test_home_actions.py` for the
    non-existent `test_state.py` and adding `test_serve_stdio.py`) → 274 passed.
  - `uv run pytest -q` (full suite) → 1177 passed.
  - `uv run ruff check src tests` → All checks passed.
  - `uv run ruff format --check src tests` → 160 files already formatted.
  - `uv run mypy` → Success: no issues found in 67 source files.
  - `uv run pre-commit run --all-files` → all hooks passed.
  - `git diff --check` → clean (no whitespace errors).
  - Rebase check: `origin/main` (`8694e30`) is an ancestor of this branch's HEAD — no rebase
    needed.
- **Independent QA:** not yet run — this PR flips to `agent:needs-qa` as the next step; the
  auditor's own exact-head gate re-run is the merge-gate receipt per the dispatch instructions.
- **Deviations from the plan (all recorded above in-line too):**
  1. Tasks 2 and 3 landed in ONE commit (`feat(menu): assign human-enterable action tokens`)
     instead of two — `_shelf()`'s dispatch needed the `MenuItem`/alphabet types to be
     meaningfully testable end-to-end, so splitting them into separate RED/GREEN commits would
     have meant an intermediate commit with an unused type. No functional deviation from the
     design.
  2. `tests/test_state.py` doesn't exist in this repo; Task 4's new state/model tests landed in
     the new `tests/test_home_actions.py`.
  3. Task 1's `serve_stdio` RED test landed in `tests/test_serve_stdio.py` (the file that
     actually exercises `serve_stdio`) rather than `tests/test_agent_driver.py` (which drives the
     in-process `CockpitDriver`, not the JSON wire).
  4. Task 4's declaration-to-handler `z` drive is BLOCKED — the real handler/store drive passes,
     but production xbook does not populate the new framework action facts. #1015 owns that
     implementation per design §9 and is still an unmerged plan.
  5. #114 (Doctor remedy actions) is still open/unmerged at the time of this work — nothing to
     rebase against; the design doc (§9) already declares it orthogonal/non-blocking.
- **OPERATOR TODO:** after this PR merges, post the exact merge SHA as a comment on
  Auto-Bookkeeper #1014 and #1015 per the design doc's consumer-handoff step (the consumers
  coordinate one shared pin).

## Stop conditions

Return to SOL authoring if a wire schema bump is required, row identity cannot stay stable, legacy
multi-digit agent inputs cannot be retained, overflow would crash, root no-op cannot satisfy the
existing frame-per-key pump, or the implementation proposes timing/digit buffering or worker-local
code.

## HANDOFF NOTES

- **Current phase:** QA findings 1–5 addressed; blocked on finding 6's absent consumer declaration
  implementation.
- **Decisions:** legacy agent aliases are canonical multi-character ASCII decimal strings with no
  leading zero and an in-range ordinal. All Unicode digit-like, leading-zero, mixed, unknown and
  out-of-range strings are inert. Positive ASCII-decimal legacy tuple keys supply stable ordinal
  row/selection identity; duplicate identities fail validation.
- **Evidence:** compatibility focused RED produced 7 expected failures including the `²²` crash
  and rewritten `option:7`/`option:12` identities; focused GREEN is `16 passed, 34 deselected`.
  Exact route acceptance is now an exhaustive fresh-session matrix:
  `{human, stdio} × {1..9,a..g}` = 32 cells, `32 passed, 7 deselected`. Each cell asserts its
  rendered/model token, exact public effect, exactly one usage/audit launch and zero neighbor opens.
- **Known-failing tests:** none in the completed framework phases. Finding 5's real catalog
  candidate probe is green. Finding 6 cannot be made green because the consumer declaration code
  under test is absent from both current Auto-Bookkeeper production and its open #1015 plan branch.
- **Consumer status:** Auto-Bookkeeper #1014 and #1015 are still open, unmerged plan PRs. No
  consumer implementation has been assumed.
- **Fixer round 2026-08-03, current phase:** QA finding 1 is GREEN; next concrete step is the
  recurring legacy-menu-key grammar matrix for findings 2–4.
- **QA finding 1 decision:** worker action declarations are untrusted at both state fields. Only
  tuple/list containers are accepted; bare strings and non-sequences normalize to empty. Tokens
  are trimmed but must remain printable, whitespace-free and comma-free so every fact is one
  key token and the Needs-row comma-delimited field stays unambiguous.
- **QA finding 1 RED/GREEN:** the real `run_cockpit` matrix
  `{home_actions, NeedsItem.actions} × {None, bare string, integer, valid tuple, empty tuple}`
  failed 6/10 cells before the boundary guard; the focused phase now passes
  `23 passed in 0.10s` via `uv run pytest -q tests/test_home_actions.py`.
- **Known-failing tests:** none in completed phases. Findings 2–4 have not yet been implemented;
  their RED matrix is the next step.
