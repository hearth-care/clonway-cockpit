# Menu input parity — Fleet Foundry readiness

**Verdict:** SOL-authored, dependency-free shared foundation; dispatchable after publication.

## Why a shared PR is required

Auto-Bookkeeper #1014's generic draft points at `clonway_cockpit/shell.py` and rendering, while
#1015 needs a worker Home-action seam the current framework does not expose. Builders working only
on either xbook branch cannot correctly change the pinned dependency. A local override would fork
the fleet contract. This companion is the single shared owner; #1014/#1015 coordinate one pin plus
their real-consumer acceptance slices.

## Generic-plan gaps corrected

The original work order said Backspace should be a no-op and two-digit items should be enterable,
but did not explain why root returns end the process, notice the false-positive test, choose between
digit buffering and single-key tokens, reserve q, handle overflow, preserve stable row identity,
retain old agent inputs, or bind Rich/model/dispatch to one source.

The replacement:

- fixes only the empty root-stack branch and preserves real back-pop/q/Esc behavior;
- introduces an additive normalized menu item separating ordinal identity from shortcut;
- retains 1–9, then uses deterministic letters excluding q;
- advertises only one-key human/agent actions while accepting legacy multi-digit agent aliases;
- keeps overflow arrow/Enter-accessible without fake tokens or crashes;
- preserves capability order, open usage/audit and nested effect gates; and
- adds backward-compatible worker-declared global/per-Needs Home action facts; and
- requires Auto-Bookkeeper's real 16-item/root/`z` pin/stdio acceptance before value is claimed.

## Evidence inspected

- current framework `run_cockpit`, `_home`, `_NavStack`, `_shelf`, `_open_capability`;
- raw `keys.read_key` one-token behavior;
- Rich `render_menu`, `model_menu`, row IDs/actions and agent stdio frame-per-key pump;
- framework navigation/menu/model/contract tests, including the Backspace test whose script omits
  Backspace;
- current framework main/pinned SHA and all open framework PRs (#114 only, orthogonal);
- Auto-Bookkeeper pinned dependency, 16-item shelf-G catalog and real stdio probes; and
- xbook `z` handler/help/deferred model plus the missing global/active-Needs action facts; and
- focused framework baseline: **204 passed in 0.47 seconds**.

Live-shaped xbook proof: shelf G advertised actions `10`–`16`; `g`,`1`,`0` opened item 1; semantic
root `backspace` ended after one Home frame. No provider/config/accounting write ran.

## Acceptance and value gate

Independent QA must prove root/nested Backspace, q/Esc, sizes 1/2/9/10/16/capacity/overflow, every
token route, stable row identity, Rich/model parity, legacy `"10"`, unknown/reserved inputs,
usage/audit counts, worker Home action defaults/normalization, real xbook active/deferred `z`, stdio
liveness and Auto-Bookkeeper real-shape behavior. No live provider/accounting effect is authorised;
the hermetic reversible park store is the only consumer write in the `z` acceptance.

Blueprint only. Value arrives after framework implementation/QA/merge, #1014 pin/acceptance/merge,
deployment and one natural operator session where root Backspace stays open and item 10+ opens from
its displayed single-key action.

## Authoring verification

- base pinned to `origin/main@8694e302`;
- architecture/journey/compatibility inventory: complete;
- focused framework baseline: 204 passed in 0.47 seconds;
- real xbook stdio/catalog probes: complete;
- four-artifact pre-commit/diff check: pending;
- remote PR/head/checks: pending publication.
