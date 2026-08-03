# Menu input parity — framework design

**Status:** binding SOL design for the shared cockpit framework

**Base:** `origin/main@8694e30233bcfe24f45d1a3103b95dcd252054f2`

**First consumers:** Auto-Bookkeeper #1014 and #1015

**Compatibility:** additive internal menu model; stable existing row identity and accepted inputs

## 1. Product decision

The cockpit promises one interaction model projected to human Rich and agent JSON. A displayed
shortcut is therefore a protocol fact: it must be enterable as one semantic input on both channels
and route to the same capability. Root Backspace is navigation, never an implicit quit.

```text
 capabilities in canonical order
              |
       normalize menu items
       /        |          \
 Rich token  model action  dispatch map
       \        |          /
           exact capability
                 |
        existing open/audit/gate path
```

Do not solve multi-digit shortcuts with an input timeout. `1` must remain immediate; timing-based
ambiguity would make the cockpit slower, flaky over stdio and inconsistent under key repeat.

## 2. Root Backspace state machine

Current `run_cockpit()` enters `_home()` once. The root branch currently:

1. calls `nav.pop_back()`;
2. receives `None` for an empty stack; and
3. returns from `_home()`, ending the cockpit.

Replace it with an explicit split:

```python
if key == keys.BACKSPACE:
    frame = nav.pop_back()
    if frame is None:
        continue
    _home(host, screen, read_key, _nav=nav, _restore_sel=frame.restore_state.get("sel"))
    return
```

At root, do not recapture or force a human repaint: nothing changed. The agent stdio pump's existing
frame-per-key detector will re-emit the current model when it asks for the next input, preserving
request/reply liveness. With a real frame, preserve current recursive restore/return behavior and
pop exactly once.

`q` and Esc remain root quit. Backspace inside shelf/filter retains current return semantics. Tests
must distinguish all four cases; do not infer root behavior from nested navigation.

## 3. Normalized menu item

The current `(key, title, summary)` tuple conflates ordinal row identity, rendered shortcut and
dispatch input. Introduce an immutable internal/public-compatible shape:

```python
@dataclass(frozen=True, slots=True)
class MenuItem:
    ordinal: int
    title: str
    summary: str
    shortcut: str | None
```

Validation:

- ordinal is positive and unique within one menu;
- shortcut is either `None` or one ASCII lowercase/digit character;
- `q` and control/semantic key names are forbidden shortcuts;
- shortcuts are unique case-insensitively; and
- title/summary behavior stays current.

`render_menu()` and `model_menu()` are public framework helpers used by tests/workers. Accept both
legacy tuples and `MenuItem`; normalize once at their boundary. A legacy tuple `("1", ...)` keeps
today's ordinal/shortcut behavior. Every other legacy tuple preserves its exact key as row identity;
positive ASCII-decimal keys also supply the internal ordinal, while nonnumeric/empty keys receive
the lowest free positive ordinal excluding all numeric/direct claims in that menu. Duplicate exact
identities fail loudly. The shared ordinal parser returns no ordinal for leading-zero, Unicode-like,
mixed or conversion-limit-exceeding strings; these keep exact identity with a free fallback rather
than crashing. A legacy key becomes a shortcut only when it passes the ASCII one-character
validator. `_shelf()` constructs `MenuItem` directly.

Keep fresh row IDs stable as `option:<ordinal>` and legacy tuple row IDs stable as their historical
`option:<key>`; selected IDs follow the same identity. Expose `shortcut` as a row field when needed;
do not replace stable identity with the new token. Model `actions` advertises only non-None current
shortcuts plus `up`, `down`, `enter`, `q`.

## 4. Deterministic direct-action tokens

Use a module-level immutable alphabet:

```text
1 2 3 4 5 6 7 8 9 a b c d e f g h i j k l m n o p r s t u v w x y z
```

`q` is deliberately absent because it is Back. The first nine options remain byte-compatible.
Option 10 is `a`, 11 is `b`, and Auto-Bookkeeper's current option 16 is `g`. The mapping is stable
by canonical capability order; reordering capabilities already changes menu ordinal and remains the
worker catalog owner's decision.

For shelves beyond the alphabet, remaining items have `shortcut=None`. Render an empty/dim shortcut
cell, never a fake multi-character action. They remain reachable through arrows and Enter. Add a
structural current-fleet acceptance that no worker shelf exceeds capacity; overflow handling is a
fail-safe, not the intended fleet UX.

## 5. One dispatch map and compatibility aliases

Build the current shortcut map from the normalized items used for render/model:

```python
by_shortcut = {item.shortcut: index for index, item in enumerate(items) if item.shortcut}
```

Normalize a one-character input to lowercase and dispatch only if present. Do not use
`key.isdigit()` as the primary shelf rule.

For compatibility with existing agents which may have cached/used advertised `"10"`–`"n"`, accept
a multi-character all-digit input as a legacy ordinal alias when it is in range. Do not add aliases
to `ScreenModel.actions` or Rich labels. Human raw input can never emit the alias as one key, so this
preserves old agent callers without continuing the false human contract.

Unknown one/multi-character inputs are inert. A one-character `"1"` always routes option 1; the
following `"0"` is a separate input and must never retroactively change that decision.

## 6. Human and agent parity

### Human

`keys.read_key()` already emits one semantic token or literal character. No changes are required.
The shelf menu displays the exact one-character shortcut. Arrows and Enter remain universal.

### Agent

`serve_stdio` already passes the `{"key": ...}` string through. Model actions contain the exact
same single-character shortcuts. The agent may press them or use arrows/Enter. The legacy ordinal
alias remains accepted but undiscoverable.

Sending root `"backspace"` must produce another valid response/snapshot rather than EOF. The
existing no-draw frame re-emission remains the liveness owner; do not add a second agent-only draw.

## 7. Worker-declared Home action facts

The framework's `_home_actions()` currently knows only its own keys. Worker `handle_extra_key`
extensions can therefore be live for humans but invisible to agents. Do not hardcode worker keys in
the framework and do not ask workers to monkey-patch model output.

Append backward-compatible fields to the shared state shapes:

```python
@dataclass(frozen=True)
class NeedsItem:
    # existing fields unchanged and in the same order
    actions: tuple[str, ...] = ()

@dataclass(frozen=True)
class CockpitState:
    # existing fields unchanged and in the same order
    home_actions: tuple[str, ...] = ()
```

Actions are semantic key tokens such as `enter`, `backspace` or `z`. Normalize by trimming,
rejecting whitespace/control-only values and de-duplicating in first-seen order. Base framework
actions win ordering; worker `home_actions` append only when absent.

`model_cockpit_screen()`:

- merges normalized `state.home_actions` into global `actions`;
- appends an `actions` field to a Needs row only when `NeedsItem.actions` is non-empty; and
- derives both from the exact state snapshot already rendered, with no callback/I/O.

This is additive wire data, not a schema break: legacy constructors default empty and legacy frames
remain unchanged. The framework cannot prove a worker handler implements the declaration, so each
consumer must drive every declared action through its real `handle_extra_key` seam. Invalid action
data must not crash Home or silently remove base actions.

For xbook #1015, active and deferred Needs declare `("enter", "z")`; Home declares `("z",)` only
when at least one parkable/wakeable row exists. The existing deferred extra region stops hardcoding
its own string and reads the item actions. `z` remains a reversible local attention-state operation;
the xbook consumer acceptance must prove it touches only the needs-park store, re-captures to the
opposite projection and performs no provider, accounting or money effect.

## 8. Acceptance matrix

### Root navigation

- empty-stack Backspace followed by Down/Enter/q;
- two repeated root Backspaces followed by a real action;
- non-empty stack Backspace restores exact cursor and pops once;
- nested shelf/filter Backspace;
- q/Esc still quit; and
- capture/on-open/raw-mode call counts unchanged.

The current misleading `test_back_from_walk_result_returns_to_home_with_cursor_preserved` must be
replaced or amended so its key sequence actually contains Backspace and proves a later input ran.

### Menu sizes and tokens

- 0 is unreachable through `_shelf` as today;
- 1 direct-opens with no menu;
- 2, 9, 10, 16, alphabet-capacity and capacity+1 menus;
- exact tokens at 1/9/10/16/capacity;
- q never assigned; all advertised shortcuts length one and unique;
- overflow rows blank-token but arrow/Enter reachable;
- Rich labels, model actions/row fields and dispatch are derived from one normalized tuple; and
- stable row IDs/selection remain `option:<ordinal>` for fresh items and exact `option:<key>` for
  accepted legacy tuples.

### Exact routing and safety

- every direct token opens its exact capability once;
- item 10 opens through `a` for human-shaped and agent drives;
- legacy agent `"10"` opens item 10 once;
- `"1"`,`"0"` cannot open item 10;
- unknown/duplicate/reserved inputs never open;
- usage/audit launch counts remain one;
- single-spec/direct shelf behavior, Home need digits and shelf letters remain unchanged; and
- nested write capabilities still encounter the same effect/approval gate.

### Worker Home actions

- legacy positional `NeedsItem`/`CockpitState` constructors and empty declarations;
- global base+worker de-duplication/order and malformed/control values;
- per-Needs-row action field present only when declared;
- Home model action and row fact agree from one snapshot;
- real xbook active/deferred `z` actions and human help agree;
- agent `z` drive changes only the reversible park projection/store and emits the refreshed Home;
- no `z` when no parkable/wakeable rows exist; and
- workers with no extension remain byte-compatible.

### Real consumer

After framework merge, Auto-Bookkeeper #1014 pins the exact SHA and drives its 16-item shelf G:

- labels/actions are `1`–`9`,`a`–`g`;
- each opens the catalog item at the matching ordinal;
- root Backspace remains in the same real stdio session; and
- human Rich and agent `ScreenModel` preserve title/order/selection/action parity.

No live provider/config/accounting effect is required; use agent dry-run and inert/reference or
stubbed capability opens.

## 9. Ownership and composition

- This shared PR owns generic root Backspace and menu shortcut normalization/dispatch.
- Auto-Bookkeeper #1014 owns the dependency pin, real 16-item catalog acceptance and deployment
  observation. It must not copy framework shell/render code.
- Auto-Bookkeeper #1015 consumes the same pin, declares xbook's `z` action truth and proves the
  park/wake model plus disabled-xadmit copy. It must not add a second framework pin/fork.
- Open clonway-cockpit #114 owns Doctor remedy actions and is orthogonal. Rebase conflicts in
  `shell.py`/models must preserve both contracts; neither PR blocks the other semantically.
- Worker catalog order/titles remain worker-owned. The token derives from order but does not reorder.
- No runtime receipt is created: usage/audit opens already evidence routed capabilities; CI/subprocess
  acceptance evidences navigation correctness.

## 10. Stop conditions

Return to SOL authoring if stable row IDs cannot be preserved, a schema bump becomes necessary,
existing agent multi-digit inputs cannot remain accepted, the normalized model would require worker
imports, root no-op breaks frame-per-key liveness, or a candidate fix relies on digit buffering or
time-dependent input.
