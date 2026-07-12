# Work order — Keep navigation input human/agent-equivalent

> **For the Fleet Foundry builder:** implement this work order on this PR branch, task by task.
> Keep `HANDOFF NOTES` current and hand the code-bearing PR to independent QA.

**Job / priority:** shared cockpit navigation foundation; P0 / every worker session

**First consumers:** Auto-Bookkeeper #1014 (root/menu) and #1015 (worker Home actions)

**Depends on:** none

## Outcome contract

**Trigger A:** Backspace is pressed at Home while navigation history is empty.

**Closure A:** Home remains open with the same selection/state; a subsequent key is handled in the
same session. Only `q`/Esc retain root-quit authority.

**Trigger B:** A shelf contains ten or more capabilities.

**Closure B:** Every advertised direct action is one semantic key that both the raw human reader
and agent protocol can send. Rich labels, `ScreenModel.actions`, dispatch and selected row identify
the same capability. Existing multi-character numeric agent inputs remain accepted as compatibility
aliases but are not advertised as human actions.

**Trigger C:** A worker handles an extra Home key (xbook `z` park/wake) outside the framework's
default action vocabulary.

**Closure C:** The worker declares the action as state data; Home global actions and relevant row
fields expose it to the agent from the same snapshot. Workers without declarations remain unchanged.

## Binding package

- design: `docs/superpowers/specs/2026-07-12-menu-input-parity-design.md`
- plan: `docs/superpowers/plans/2026-07-12-menu-input-parity.md`
- readiness: `docs/findings/2026-07-12-menu-input-parity-readiness.md`

## Current-main evidence

- `run_cockpit()` calls `_home()` once. Root Backspace pops an empty stack then returns from `_home`,
  so the whole session exits despite the comment calling it a no-op.
- The existing back-from-walk test says it covers Backspace but its key sequence never presses it.
- `_shelf()` enumerates labels `1`…`n`, dispatches on `key.isdigit()`, and `model_menu()` advertises
  every numeric string.
- `keys.read_key()` reads exactly one semantic key/character. A human typing `1`,`0` activates item
  1 before `0` can form item 10; an agent can send the impossible human action `"10"` in one frame.
- Auto-Bookkeeper's pinned current framework has 16 shelf-G capabilities and advertises `10`–`16`.
  Its real agent subprocess exits after one Home frame on semantic root Backspace, and the human-
  shaped sequence `g`,`1`,`0` opens Config (item 1), not Admitted events (item 10).
- xbook's `z` park/wake handler and human help are live, but `_home_actions()` is framework-only and
  active Needs rows carry no action field. Deferred rows manually hardcode `"enter z"`, proving the
  model has two disconnected action authorities.

## Required states

| State | Required behaviour |
|---|---|
| Root Home + Backspace | inert; same session remains ready for next input |
| Home with a real back frame | pop exactly one frame; restore its cursor; do not duplicate frames/history |
| Root Home + q/Esc | quit exactly as today |
| Shelf with 1 capability | preserve direct-open behavior; no menu |
| Shelf with 2–9 capabilities | preserve `1`–`9` labels/actions |
| Shelf with 10–34 capabilities | use deterministic single-key tokens after `9`, excluding reserved `q` |
| Shelf larger than direct-token capacity | never crash or advertise an unenterable token; all rows remain reachable by arrows/Enter |
| Human key and advertised agent action | open the same exact capability and record one usage/audit launch |
| Legacy agent sends `"10"` | keep compatibility alias if item 10 exists; do not render/advertise `10` |
| Unknown/multi-character non-alias key | inert; no capability opens |
| Back row | arrows/Enter, q, Esc and Backspace remain valid and consistent |
| Worker declares a Home action | append/dedupe it in global actions and relevant row facts |
| Worker declares nothing | byte-compatible Home model and constructors |
| Declared action is malformed/duplicate | normalize safely; never corrupt the frame or shadow base action |

## Invariants

- Fix the shared framework; do not add worker-local shell/menu forks.
- One normalized menu model supplies Rich rendering, ScreenModel rows/actions and dispatch.
- Preserve stable ordinal row identity for existing agents while separating it from visible shortcut.
- Do not buffer digits or add timing heuristics; `1` must stay immediate and deterministic.
- Do not bump the wire schema if legacy numeric aliases remain accepted and row IDs stay stable.
- Do not change Home need-number shortcuts, shelf-letter shortcuts, raw-mode lifecycle, navigation
  performance, capability order, effect policy, write gates or usage/audit behavior.
- Add worker Home action facts through backward-compatible state fields, not worker imports,
  model monkey-patches or hardcoded xbook keys in the framework.
- Navigation is read-only and emits no runtime completion receipt. Handoff evidence is the focused
  framework plus real-worker subprocess acceptance.

## Acceptance gate

- [ ] Record load-bearing RED for root Backspace followed by another action and for a 16-item shelf.
- [ ] Implement root no-op without re-capture and exact one-frame back-pop behavior.
- [ ] Add a backward-compatible normalized menu item with stable ordinal ID and optional shortcut.
- [ ] Drive every current shortcut through Rich, model and both human/agent input forms.
- [ ] Prove item 10+ single-key routes, legacy agent alias, overflow arrows/Enter and reserved keys.
- [ ] Prove optional worker-declared global/row Home actions, legacy constructors and real xbook `z`
  discoverability/drive without adding provider or money effects.
- [ ] Prove Auto-Bookkeeper's 16-item shelf through a pinned-framework candidate and real stdio.
- [ ] Run framework gates, independent acceptance/architecture/security/operability QA and document
  the consumer pin SHA for Auto-Bookkeeper #1014.

## HANDOFF NOTES

- Current phase: SOL design complete; ready for Foundry implementation.
- Base: `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`.
- Baseline: 204 focused framework tests passed in 0.47 seconds.
- Dependencies: none. Auto-Bookkeeper #1014/#1015 must block on this PR and share one pin SHA.
- Next step: execute Task 1 RED before changing `shell.py`.
- Live value: not delivered until this builds/merges and worker pins deploy it.
