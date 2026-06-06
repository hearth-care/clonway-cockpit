# Agent-navigable cockpit — design

**Date:** 2026-06-06
**Repo:** `clonway-cockpit` (framework), consumed by `xbook` (Auto-Bookkeeper) and `xops` (Auto-Orchestrator)
**Status:** Approved design → implementation planning

## Problem

The cockpit is a Rich-based TUI. Today, a "shelf" (a top-level screen/section) or a
"walk" (a guided `explain → preconditions → review → apply-gated → summarise` flow) can
only be *qualified* by a human looking at the rendered terminal. Automated checks script
keystrokes and then assert substrings against `Console(record=True).export_text()` — brittle,
layout-coupled, and giving an agent no semantic grip on "what is on this screen."

We want agents to **parse, navigate, and verify** the cockpit — and ultimately let an agent
("Ryan") run the bookkeeping by launching the cockpit itself and confirming functionality.

### What already exists (the seams we build on)

- **Driving is already solved.** `shell.run_cockpit(host, *, read_key, screen)` injects the
  keystroke source (`read_key: () -> str`) and a `screen` Protocol whose only method is
  `update(renderable)`. The walk machine (`walk.run_walk`, `walk.preflight`, `walk.confirm_apply`)
  is the same: it presents via `ctx.present` and reads via `ctx.read_key`. Tests already pass a
  frame-recording fake `screen` and a scripted `read_key`.
- **State and logic are already structured.** `CockpitState` (pills / needs / shelves / help),
  `walk.Step`, `walk.StepResult(ok, message, data)`, `walk.Precondition`, `walk.Stage`,
  `registry.CapabilitySpec`, `registry.BlastRadius`.
- **The gap is the output.** Every screen is emitted as an opaque Rich `RenderableType`. The
  structured *inputs* that built it are discarded at the seam. `obs.py` / `signals/` stream
  *operational run* telemetry to the xops dashboard — not screen semantics.

So the missing piece is a **semantic snapshot**: a structured, serializable "what is on this
screen" that an agent reads, navigates by, and asserts against — instead of scraping ANSI.

## Goals / non-goals

**Goals**
1. A typed `ScreenModel` describing each cockpit screen, JSON-serializable.
2. The human render and the agent snapshot derive from the **same** `ScreenModel` (no drift).
3. An in-process driver that scripts keys and records the `ScreenModel` stream — the new,
   non-brittle test harness.
4. A subprocess `--agent` mode (stdio + line-delimited JSON) so a separate agent process can
   launch the real cockpit, read snapshots, and send keys.
5. A safety model for irreversible writes: dry-run by default in agent mode; explicit,
   reviewable authorization for real Xero posts (Phase 2).

**Non-goals**
- No change to the human-facing visuals. The live cockpit stays byte-identical.
- No migration to Textual or any other framework.
- No unrelated refactor of `_screens.py` beyond adding `ScreenModel` emission.

## Architecture

Five layers plus the write gate. New code is additive behind the existing `Host`/`screen`
seam.

### 1. The contract — `ScreenModel`

A new framework module `clonway_cockpit/model.py`. Frozen dataclasses, JSON-serializable via
`.to_dict()`.

```python
@dataclass(frozen=True)
class Field:
    label: str
    value: str
    role: str = "text"          # text | number | currency | status | date | …

@dataclass(frozen=True)
class Row:
    id: str                     # stable, semantic — "shelf:F", "need:2", "fix:sync", "step"
    label: str
    fields: list[Field] = field(default_factory=list)
    selected: bool = False
    enabled: bool = True

@dataclass(frozen=True)
class Region:
    role: str                   # needs | toolkit | preconditions | summary | blast_radius | prose | …
    title: str
    rows: list[Row] = field(default_factory=list)
    text: str | None = None     # for prose regions (explanations, notes)

@dataclass(frozen=True)
class ScreenModel:
    kind: str                   # home | shelf_menu | walk.preflight | walk.review |
                                # walk.result | walk.progress | doctor | filter | note |
                                # card | unstructured
    title: str
    regions: list[Region] = field(default_factory=list)
    selection: str | None = None        # id of the currently-selected Row, if any
    actions: list[str] = field(default_factory=list)   # available keys/verbs
    meta: dict = field(default_factory=dict)            # screen-specific extras
```

`meta` is where screen-specific structured facts live, e.g.:
- walk.preflight: `{"blast_radius": "...", "equivalent_cli": "...", "ready": bool, "progress": "step 1 of 4", "remedy": {...}}`
- walk.review: `{"gate": "awaiting_apply"|null, "equivalent_cli": "...", "diff": {...}}`
- walk.result: `{"ok": bool, "message": "...", "links": [...]}`
- walk.progress: `{"label": "...", "stages": [{"key","label","status","detail"}], "elapsed": int}`

`actions` is the set of keys the screen will honour (`["enter","up","down","left","right",
"/","?","q","backspace", …]`), so an agent knows what it can do without guessing.

### 2. Render becomes `ScreenModel → Renderable`

Each framework `render_*` in `render.py` is refactored so a `ScreenModel` is **built first**
(the input of record) and then rendered to Rich. Pattern:

```python
def model_cockpit_screen(state, specs, *, selection, extra_regions) -> ScreenModel: ...
def render_cockpit_screen(state, specs, *, selection, extra_regions) -> RenderableType:
    return _render(model_cockpit_screen(state, specs, selection=selection, extra_regions=extra_regions))
```

Migrate the finite set of **generic primitives** first — they are used by *every* walk and
shelf, so all walks become agent-verifiable at once:

`render_cockpit_screen` (home), `render_menu` (shelf menu), `render_preflight`,
`render_walk_result`, the review/gate screen, `render_sync_progress` / `render_staged_progress`,
`render_doctor`, `render_filter`, `render_note`, `render_capability_card`, `render_help`.

### 3. The seam emits the model

The shell builds the model, renders it to Rich for `screen.update` (the live app — unchanged),
**and** publishes it to an optional observer. Add to `Host` (defaulted to a no-op, so existing
constructions are byte-identical):

```python
on_screen: Callable[[ScreenModel], None] = lambda model: None
```

At each draw site the shell does:

```python
model = model_cockpit_screen(state, specs, selection=items[sel], extra_regions=...)
screen.update(render._render(model))   # live app: unchanged pixels
host.on_screen(model)                  # agent feed: default no-op
```

The walk machine threads the same observer through `WizardContext` (a new optional
`on_screen` field) so walk screens emit too. The live path is byte-identical; agents get the
semantic feed. **One source of truth** — the model that renders is the model that's emitted.

### 4. In-process driver (core + new test harness)

A new module `clonway_cockpit/agent.py`:

```python
class CockpitDriver:
    """Drive the cockpit headlessly: feed keys, record the ScreenModel stream."""
    def __init__(self, host: Host, keys: Iterable[str] | None = None): ...
    def run(self) -> list[ScreenModel]:     # drive run_cockpit with the scripted keys; return the stream
    def send(self, key: str) -> ScreenModel: # interactive: step one key, return the resulting screen
    @property
    def last(self) -> ScreenModel: ...
    @property
    def stream(self) -> list[ScreenModel]: ...
```

It supplies: a fake `screen` (renders to a throwaway buffer or no-ops), a `read_key` that pulls
from the script/queue, and an `on_screen` observer that appends to `stream`. Framework tests
migrate from `export_text() + substring` to structural asserts:

```python
d = CockpitDriver(host, keys=["F", "1", "enter", "enter"])  # open shelf F, first spec, preflight, gate
d.run()
assert d.last.kind == "walk.result" and d.last.meta["ok"]
assert any(r.role == "blast_radius" for s in d.stream for r in s.regions)
```

Keep a handful of golden render-to-text tests so the *human visuals* don't silently regress.

### 5. Subprocess JSON protocol (Ryan launches the real app)

An `--agent` mode wired in each worker's cockpit entry point (`xbook cockpit --agent`,
and the xops bridge). It launches the real cockpit but swaps the interactive tty for a
line-delimited JSON protocol over stdio, internally just `CockpitDriver` bound to stdin/stdout:

- **agent → app** (one JSON object per line): `{"key": "down"}`, `{"key": "enter"}`,
  `{"cmd": "snapshot"}` (re-emit current), `{"cmd": "quit"}`.
- **app → agent** (one JSON object per line): the current `ScreenModel.to_dict()` after each
  key, or `{"error": "..."}` on a bad message (the screen is held).

Ryan's loop: spawn `xbook cockpit --agent`, read a snapshot, decide the next key from the
`regions`/`selection`/`actions`, write it, repeat — literally "launch the TUI itself and verify."

### 🔒 The write gate (safety)

Walks post to Xero only through `walk.confirm_apply` (ENTER / `a` / `A`). For an agent, blindly
confirming an irreversible post is unacceptable.

- **Phase 1 (default agent mode): dry-run.** In `--agent` mode `confirm_apply` always declines.
  An agent can drive any walk end-to-end and *see* the review screen, blast radius, and
  equivalent-CLI — but never posts. This makes Phase-1 verification safe end-to-end.
- **Phase 2: explicit apply-authorization handshake.** At the gate the app emits
  `kind="walk.review", meta.gate="awaiting_apply"` carrying the blast radius, equivalent-CLI,
  and a proposed diff/summary. The agent must send `{"apply": true, "token": <gate-id>}` to
  proceed; any other input declines. Ryan routes that proposal up to **god → human** for
  sign-off before sending `apply`. The `token` is a per-gate nonce so a stale/duplicated apply
  can't fire. Irreversible writes are never autonomous-by-accident, and every applied gate is
  logged (reuse `obs.event`).

## Error handling

- **Unmigrated screen** → `ScreenModel(kind="unstructured", title=<best guess>,
  regions=[Region(role="prose", title="", text=export_text(renderable))])`. The driver still
  works; the model explicitly flags it isn't semantic yet.
- **A walk crash** already renders a clean `render_walk_result(ok=False)` (the shell's
  `_open_capability` guards every walk). Model it as `kind="walk.result", meta.ok=False`; no
  traceback escapes to the agent.
- **Protocol errors** (bad JSON, unknown key/cmd) → app replies `{"error": "..."}` and holds
  the current screen; never crashes the session.
- **`ShellOut`** (a capability that leaves the alt-screen to run a child command) is control
  flow, not an error — in agent mode it surfaces as a `kind="note"` model describing the
  shell-out rather than actually exec'ing a child (agents don't get an interactive child shell).

## Testing

1. **Driver-based unit tests** in the framework: migrate the `test_shell.py` / `test_walk.py`
   assertions from text-substring to `ScreenModel` structure. Far less brittle.
2. **Golden visual tests**: keep a small set of `export_text()` snapshots so the human-facing
   render can't silently regress while we refactor.
3. **Protocol smoke test**: spawn `xbook cockpit --agent` as a subprocess, drive a known walk in
   dry-run, assert the snapshot stream and that no apply fired.
4. **Contract test** (xbook / xops): every capability/shelf an agent must verify yields a
   non-`unstructured` model. Fails the build if a must-verify screen is still unmigrated.
5. **Gate safety test**: in agent mode, a walk driven through the gate without an explicit
   authorized `{"apply":true,...}` performs **zero** writes (assert via a mocked Xero client).

## Components / boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `model.py` | `ScreenModel` + `Field/Row/Region` + `to_dict` | stdlib only |
| `render.py` | `model_* (build) → _render (to Rich)`; keep `render_*` wrappers | `model`, rich |
| `shell.py` | emit `model` to `host.on_screen` at each draw | `model`, `render` |
| `walk.py` | thread `on_screen` via `WizardContext`; gate honours agent dry-run/auth | `model`, `render` |
| `agent.py` | `CockpitDriver` (in-process) + stdio JSON pump | `shell`, `walk`, `model` |
| worker entry (`xbook`/`xops`) | `--agent` flag → `agent.serve_stdio(host)` | `agent` |

## Phasing / milestones

- **M1 — framework core (clonway-cockpit PR).** `model.py`; refactor the generic primitive
  renders to model-first; `host.on_screen` + walk `WizardContext.on_screen`; `CockpitDriver`;
  migrate framework tests. *Outcome:* walks are agent-verifiable in-process.
- **M2 — subprocess mode.** `agent.serve_stdio`; `--agent` flag in xbook (+ xops bridge);
  protocol smoke test; bump pinned revs in xbook/xops. *Outcome:* Ryan can launch and drive the
  real cockpit in dry-run.
- **M3 — shelf reports.** Add `ScreenModel` emission to xbook `_screens.py` shelf reports,
  prioritized by which shelves agents verify first; add the contract test. *Outcome:* shelves
  become agent-verifiable incrementally.
- **M4 — guarded writes (Phase 2).** Apply-authorization handshake + the Ryan→god→human
  sign-off path + gate safety test + `obs` logging of applied gates. *Outcome:* Ryan can
  operate the books with reviewable, non-accidental writes.

## Open questions (resolve during planning)

- Exact `--agent` invocation surface per worker (new Typer subcommand vs. flag on the existing
  `cockpit` command).
- Whether the stdio protocol should be one-shot scripted (`--agent-script file.jsonl`) in
  addition to interactive — useful for CI.
- `Row.id` naming scheme stability guarantees (agents will assert on these — treat as a
  semi-public contract and document it).
