# Menu input parity — Fleet Foundry implementation plan

> **Builder instruction:** execute in order on this PR branch. Each task begins with a load-bearing
> RED and ends with focused GREEN plus a commit. Do not implement an xbook-local shell fork.

**Goal:** root Backspace stays in-session and every advertised shelf action is one human/agent-
equivalent key.

**Binding design:** `docs/superpowers/specs/2026-07-12-menu-input-parity-design.md`

**Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`

## Task 1 — RED/GREEN: make root Backspace a real no-op

**Modify first:** `tests/test_shell.py`, `tests/test_agent_driver.py`.

- [ ] Replace/amend the misleading back-from-walk test so the script actually presses Backspace,
  then a second observable action, then q.
- [ ] RED: empty-stack root Backspace followed by Down/Enter remains in one run; assert frame/capture/
  activation counts and final q exit.
- [ ] RED: two root Backspaces followed by a valid action; neither exits or recaptures.
- [ ] RED: `serve_stdio` receives `backspace`, snapshot and quit; assert a post-Backspace Home frame,
  valid JSON and clean exit rather than early EOF.
- [ ] Preserve non-empty back-pop cursor, nested shelf/filter Backspace and q/Esc quit tests.
- [ ] Record RED: current `_home` returns from the only top-level call.
- [ ] Change only the empty-stack branch to `continue`; keep real-frame recursion/return.
- [ ] Run focused GREEN and commit: `fix(shell): keep root backspace in session`.

## Task 2 — RED/GREEN: normalize stable menu items and tokens

**Modify first:** `tests/test_screen_models.py`, `tests/test_screen_models_rest.py`,
`tests/test_render_primitives.py`, new `tests/test_menu_input_parity.py`.

- [ ] Specify `MenuItem` validation and legacy tuple normalization.
- [ ] Matrix sizes 2/9/10/16/capacity/capacity+1 and assert exact shortcut sequence.
- [ ] Prove ordinal row IDs/selection are unchanged and shortcut is a separate field/fact.
- [ ] Prove Rich and model advertise the same non-None tokens; all are one character, unique and
  exclude q/control/semantic key names.
- [ ] Prove overflow renders no fake token and remains selected/arrow-addressable.
- [ ] Record RED: current option 10 renders/advertises `10`.
- [ ] Implement additive `MenuItem`, normalizer and deterministic alphabet. Keep legacy tuple API.
- [ ] Make render/model consume normalized items once. Do not change wire schema.
- [ ] Run focused GREEN and commit: `feat(menu): assign human-enterable action tokens`.

## Task 3 — RED/GREEN: route current tokens and legacy aliases once

**Modify first:** `tests/test_shell.py`, `tests/test_menu_input_parity.py`.

- [ ] Register 16 unique capabilities and spy on `_open_capability` public effects (usage/audit/run).
- [ ] Press each displayed token; assert exact ordinal capability opens once.
- [ ] Prove `a` opens item 10, `g` opens item 16 and q returns.
- [ ] Prove human-shaped `1`,`0` never combines into item 10.
- [ ] Prove agent-shaped legacy `"10"` opens item 10 for compatibility but is absent from actions.
- [ ] Drive unknown/reserved/uppercase/duplicate/malformed values and overflow Arrow/Enter behavior.
- [ ] Preserve single-spec direct open, Home need digits, shelf letters, back row and effect gates.
- [ ] Replace primary `key.isdigit()` dispatch with one normalized shortcut map plus the narrow
  multi-character ordinal compatibility branch.
- [ ] Run focused GREEN and commit: `fix(menu): share one rendered and dispatched action map`.

## Task 4 — RED/GREEN: let workers declare Home action facts

**Modify first:** `tests/test_model.py`, `tests/test_screen_models.py`, new focused state/model tests.

- [ ] RED legacy constructor matrix plus empty action declarations; preserve every positional field.
- [ ] RED state with `home_actions=("z",)` and Needs `actions=("enter", "z")`; assert global/row
  facts, order, dedupe and selection without changing other fields.
- [ ] Matrix duplicates, whitespace/control/invalid types and collisions with base actions. Invalid
  worker hints cannot crash Home or remove framework actions.
- [ ] Implement additive `NeedsItem.actions` and `CockpitState.home_actions`; normalize only in the
  pure model projection. Do not import worker code or add callbacks/I/O.
- [ ] Assert workers with empty defaults remain model-shape compatible.
- [ ] Use xbook #1015's worktree/candidate pin to drive real active/deferred `z`; assert the
  declaration matches handler behavior and only the reversible local park store changes.
- [ ] Commit: `feat(model): expose worker-declared home actions`.

## Task 5 — contract, agent and real-shape acceptance

- [ ] Drive a 16-item framework host through human-shaped injected keys and `serve_stdio`; compare
  ordered titles, row IDs, shortcuts, actions, selection and exact opened capability.
- [ ] Assert no `unstructured` frames, no frame-per-key timeout and no early process exit.
- [ ] Assert usage/audit open exactly once and any nested write still reaches existing gate/default
  denial; navigation itself creates no completion receipt.
- [ ] Run contract/model shape tests and old-agent legacy alias regression.
- [ ] Create a temporary consumer install/pin or use Auto-Bookkeeper #1014/#1015 worktrees after
  this branch is published; drive the real 16-item shelf, root Backspace and `z` facts without live
  provider/accounting effects.
- [ ] Rebase against #114 if it merged; resolve shell/model overlap semantically and rerun Doctor
  remedy tests. It is not a product dependency.
- [ ] Run independent acceptance, architecture, agent-parity, security and operability QA; fix all
  blockers and rerun.
- [ ] Commit: `test(menu): prove human and agent navigation parity`.

## Task 6 — gates, consumer handoff and release

- [ ] Run at minimum:

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

- [ ] Update framework docs only if the advertised menu action grammar is documented; record the
  exact token alphabet, overflow and legacy agent alias.
- [ ] Update HANDOFF NOTES with RED/GREEN commits, final symbols, compatibility/shape verdict,
  Auto-Bookkeeper real-shape proof, gates and independent QA.
- [ ] Push and verify live head/diff/mergeability/checks; hand to independent Foundry QA.
- [ ] On merge, post exact merge SHA to Auto-Bookkeeper #1014/#1015. The consumers coordinate one
  pin and own deployed xbook observations.

## Stop conditions

Return to SOL authoring if a wire schema bump is required, row identity cannot stay stable, legacy
multi-digit agent inputs cannot be retained, overflow would crash, root no-op cannot satisfy the
existing frame-per-key pump, or the implementation proposes timing/digit buffering or worker-local
code.
