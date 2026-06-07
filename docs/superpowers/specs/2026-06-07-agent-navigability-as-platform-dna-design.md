# Agent-navigability as platform DNA — design

**Status:** approved (architecture), ready for phased implementation
**Date:** 2026-06-07
**Scope:** clonway-cockpit (framework + worker-template) → all `run_cockpit` consumers (xbook, xops, xhr, …) → the orchestrator (Auto-Orchestrator / xops bridge) → fleet `CLAUDE.md` convention.

---

## 1. The goal, restated

Every autoworker we build must be **simultaneously** a human TUI and an agent-drivable
surface — same binary, same code path, no second implementation. An AI agent ("Ryan"),
a human, and the orchestrator all operate the worker through one contract. This must be a
**structural default**, not a per-repo retrofit: a new worker is born agent-navigable, and
the build refuses to go green if a screen stops being agent-navigable.

The operating principle that makes this real:

> **One screen description, two projections.** A cockpit screen is a single model. The
> human pixels (Rich renderables) and the agent JSON (`ScreenModel`) are both projections
> of it. They cannot drift, because the build fails when they do.

Today `render_*` and `model_*` are *parallel* builders kept honest by a parity test that
lives in each repo by hand. This design makes that discipline **inherited, enforced, and
versioned** — and the deepest form (render-derived-from-model, a single source) is named as
the north star without forcing it all at once.

## 2. Why documentation alone can't do this

A convention in `CLAUDE.md` is necessary but **not sufficient**. The only thing that makes a
property *automatic* is a **failing build**. Two hard-won lessons drive the whole design:

1. **Static review structurally cannot catch "advertised but not wired."** (Final Boss
   Audit, 2026-06-06: the architect + design heads both *passed* a screen whose model was
   defined-but-dead; only the acceptance head — which *drove* it — caught it.) → the gate
   must **drive** the cockpit, not just read it.
2. **Copied tests rot independently.** The parity gate today is a hand-copied
   `tests/test_contract.py` per repo. → the gate must be **shipped from the framework** and
   *imported*, so a framework bump propagates the discipline to every consumer at once
   (the pinned-by-git-rev consumption model already gives us this for free).

## 3. The four layers

| Layer | What exists now | What this design adds (the "automatic" mechanism) |
|---|---|---|
| **L1 — The seam** | `serve_stdio`, dry-run gate, guarded-apply, `Host.on_screen`. Each consumer hand-writes ~30 lines of `serve_agent` + a `--agent-stdio` callback; the host-rebuild/ambient-flag wart is per-repo lore. | A framework `serve_agent_stdio(host, …)` one-liner + the canonical agent-mode-aware `_host()` recipe, and a `CockpitClient` (the subprocess **peer** of `serve_stdio`) so the *driving* end is framework-owned too. |
| **L2 — The gate** | `tests/test_contract.py` — parity check, **hard-coded to the framework's own `render` module**, copied per repo. | `clonway_cockpit.contract` — `assert_render_model_parity(render_ns, model_ns)` (static) **and** `assert_drives_clean(host, keys)` (dynamic: drives the real loop, asserts **no `unstructured` frame** + pure-JSON stdout). Each repo's test becomes ~3 lines that parametrize over its *own* render namespace. **This is the load-bearing piece.** |
| **L3 — The scaffold** | `worker-template/` (copier) already generates a working cockpit + signals + CI + the C6 smoke test — but **no agent channel** and **no parity/conformance test bound to the worker's render namespace**. A generated worker is *not* born agent-navigable. | Template generates: the `--agent-stdio`/`--allow-apply` callback, a `serve_agent`, a `model_*` twin for the stub screen, and the L2 gate tests in the generated `tests/`. New workers are born compliant; the generated CI keeps them compliant. |
| **L4 — The orchestrator** | Protocol exists; the *driver* ("Ryan") + human-sign-off routing are operator-harness scope (documented as out-of-scope in the M-series audit). | `CockpitClient` lands in the framework (L1); the orchestrator enumerates the roster and drives each worker through it, routing `awaiting_apply` to an approver. A `drive-cockpit` skill gives sessions/Ryan one uniform path. |

## 4. Component designs

### 4.1 `clonway_cockpit.contract` (new module) — the shippable gate

The current `tests/test_contract.py` logic, promoted into the package so any repo can run it
against its **own** render/model namespaces.

```python
# clonway_cockpit/contract.py  (sketch — full code in the Phase-1 plan)

def page_framing_renders(render_ns) -> set[str]:
    """Public render_* in `render_ns` whose source calls page(...) — i.e. frames a
    full screen (vs a sub-component like render_header)."""

def model_twin(render_name: str) -> str:
    """'render_foo' -> 'model_foo'."""

def assert_render_model_parity(render_ns, model_ns=None, *, allow_unmodeled=frozenset()):
    """Every page-framing render_* in `render_ns` has a model_* twin in `model_ns`
    (defaults to render_ns). `allow_unmodeled` is an explicit, reviewed escape hatch
    (a screen deliberately served as `unstructured`) — empty by default."""

def assert_drives_clean(host, keys, *, allow_unstructured=False):
    """DYNAMIC conformance: drive `host` headlessly via CockpitDriver over the scripted
    `keys`, and assert every emitted ScreenModel.kind != 'unstructured' (unless opted out).
    This is what catches 'modeled-but-dead' — the failure static review cannot see."""
```

- **Why both static and dynamic:** static proves *a twin exists*; dynamic proves *the twin
  is actually emitted on a real path* (and that nothing falls through to `unstructured`).
- **Dogfood:** the framework's own `tests/test_contract.py` is rewritten to call these, so
  the helper is exercised by the framework's own CI.
- `assert_drives_clean` reuses the existing `CockpitDriver` — no new harness.

### 4.2 `serve_agent_stdio` + the canonical host recipe (L1 DRY)

Each consumer currently writes its own `serve_agent`. Promote the wrapper:

```python
# clonway_cockpit/agent.py  (addition)
def serve_agent_stdio(host, *, allow_apply=False, stdin=sys.stdin, stdout=sys.stdout):
    """The worker-side one-liner: serve the agent protocol over stdin/stdout.
    Thin over serve_stdio (which already forces agent_mode=True)."""
    serve_stdio(host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)
```

**The host-rebuild wart, documented as the recipe.** `serve_stdio` sets `agent_mode=True`
on the host it threads through `run_cockpit`. A worker whose `_host()` is re-invoked *inside*
its own callbacks (xbook) loses that flag on the rebuilt instance. The canonical fix —
already proven in xbook — is an agent-mode-aware factory:

```python
_AGENT_MODE = False  # module ambient, set True before serving the agent channel
def _host(*, agent_mode: bool = _AGENT_MODE) -> shell.Host:
    return shell.Host(..., agent_mode=agent_mode)
```

The template generates this shape so no future worker rediscovers it. Workers that never
rebuild their host (xhr) can pass the host directly and skip the ambient flag.

### 4.3 Protocol versioning (L1, the orchestrator depends on it)

`ScreenModel.to_dict()` is currently **unversioned** (`asdict(self)`, no version key). The
orchestrator and Ryan need a stable, declared contract version to branch on.

- Add `SCHEMA_VERSION = "1.0"` to `clonway_cockpit.model`.
- `to_dict()` includes `"schema_version": SCHEMA_VERSION` at the top level (additive; agents
  that ignore unknown keys are unaffected).
- A **shape-pin test** records the key set + value types of `to_dict()` per `kind`. An
  accidental breaking change to the model fails this test and forces a deliberate
  `SCHEMA_VERSION` bump + a doc update. (Lighter than a full JSON-Schema dep; sufficient to
  make breakage loud.)
- `docs/agent-screen-model.md` gains a "Protocol versioning" section.

### 4.4 `CockpitClient` (L1/L4) — the framework-owned driving end

The peer of `serve_stdio`: launches `<worker> --agent-stdio` as a subprocess, speaks the
line-delimited JSON protocol, and exposes a clean Python API.

```python
# clonway_cockpit/agent.py  (addition — full code in the Phase-4 plan)
class CockpitClient:
    def __init__(self, argv: list[str], *, allow_apply=False): ...
    def __enter__(self) -> CockpitClient: ...           # spawn + read the home frame
    def press(self, key: str) -> dict: ...              # send {"key":…}, return next frame
    def snapshot(self) -> dict: ...                     # {"cmd":"snapshot"}
    def apply(self, token: str, *, approve) -> dict: ...# guarded-apply handshake via `approve`
    def quit(self) -> None: ...
```

- `approve` is a caller-supplied callback `(proposal) -> bool` — the **human-sign-off seam**.
  The orchestrator wires it to a real approval queue; a CLI session wires it to a prompt;
  a test wires it to a fixed answer. The client never auto-approves.
- Living in the framework means **both ends of the protocol evolve together** and every
  consumer + the orchestrator + Ryan share one driver — the strongest "no distinction
  between human and agent" guarantee.

### 4.5 The convention (L1–L4, backed by the gate)

Each fleet repo's `CLAUDE.md` (and the orchestrator's) gains a short, identical block:

> **Agent-navigability is non-negotiable.** Every page-framing `render_*` ships a `model_*`
> twin (enforced by `clonway_cockpit.contract.assert_render_model_parity` in CI). Drive and
> verify the cockpit via `--agent-stdio` / `CockpitClient` / `CockpitDriver` — **never**
> scrape `export_text()`. Money/write paths go through the dry-run + guarded-apply gate.

The words explain *why*; the imported CI gate enforces *that*.

## 5. North star (not in scope now, but every step points at it)

The end state is **render-derived-from-model**: one description per screen, with the Rich
renderable computed *from* the `ScreenModel` so drift is impossible by construction (no
parity test needed because there is one source). We are not refactoring to that now —
parallel builders + an enforced gate is the pragmatic 90% — but no step in this plan moves
away from it, and L2's gate is exactly the safety net that would let a future migration
proceed screen-by-screen.

## 6. Phasing (each phase ships working, tested software)

| Phase | Repo | Deliverable | Plan |
|---|---|---|---|
| **1** | clonway-cockpit | `contract` module (static + dynamic gate), `serve_agent_stdio`, schema versioning, `CockpitClient`. Dogfood the framework's own tests. | `plans/2026-06-07-dna-phase1-framework-contract-and-protocol.md` |
| **2** | clonway-cockpit | Worker-template grows the agent channel + the gate tests + a modeled stub screen. C6 ACs extended. | `plans/2026-06-07-dna-phase2-worker-template.md` |
| **3** | xbook, xops, xhr | Retrofit onto the shared gate + `serve_agent_stdio`; add the drive-it conformance test; bump the pinned rev; add the `CLAUDE.md` block. | `plans/2026-06-07-dna-phase3-5-rollout.md` |
| **4** | Auto-Orchestrator / xops | Orchestrator drives the roster via `CockpitClient`, routing `awaiting_apply` to an approver. `drive-cockpit` skill. | `plans/2026-06-07-dna-phase3-5-rollout.md` |
| **5** | all repos | The `CLAUDE.md` convention block (folded into each repo's Phase-3/4 PR). | `plans/2026-06-07-dna-phase3-5-rollout.md` |

**Ordering constraint:** Phase 1 must merge before 2 (the template generates calls into the
new `contract` module) and before 3/4 (consumers + orchestrator pin the new framework rev).
2 is independent of 3/4 once 1 lands. 3 and 4 are parallel across repos.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Adding `schema_version` to `to_dict()` breaks tests that assert exact dict equality. | Phase-1 plan updates those tests in the same change; the shape-pin test becomes the single place the wire shape is asserted. |
| `assert_drives_clean` needs a representative key script per worker → false confidence if the script is shallow. | The template ships a script that visits every shelf + Doctor; consumers extend it. `log()`/doc the coverage; a shallow script is a reviewable omission, not a silent pass. |
| The host-rebuild/ambient-flag wart can't be fully abstracted (depends on whether a worker rebuilds its host). | Encode the canonical recipe in the template + document it; `serve_agent_stdio` removes the *other* boilerplate. |
| Typer can't cleanly compose a framework-supplied global callback with a consumer's existing one. | Don't try to inject a callback; ship building blocks (`serve_agent_stdio`) the consumer calls from *its* callback. The template generates the callback so new workers pay nothing. |
| `CockpitClient` subprocess management (deadlocks, zombie children) on errors. | Context-manager lifecycle, bounded reads (reuse `_MAX_MSG_BYTES`), EOF→quit, kill-on-exit; covered by Phase-4 tests including a worker that dies mid-session. |

## 8. Testing strategy (per layer)

- **L1 contract module:** unit tests for `page_framing_renders` (finds page-framers, ignores
  sub-components), `assert_render_model_parity` (passes on twinned, fails on an orphan),
  `assert_drives_clean` (passes clean, fails when a path emits `unstructured`). Framework's
  own `test_contract.py` rewritten to dogfood them.
- **L1 schema:** shape-pin test per `kind`; `to_dict()` carries the version.
- **L1 client:** drive a real in-process `serve_stdio` over a pipe pair; assert frames,
  the apply handshake (approve → posts; decline → 0 posts), and clean teardown on peer death.
- **L2/L3 template:** extend `tests/test_worker_template.py` — generated worker serves the
  agent channel (emits a `home` frame), `assert_drives_clean` passes on the generated stub,
  and the generated `tests/` include the gate.
- **L3 consumers / L4 orchestrator:** each repo's existing suite + the new conformance test;
  orchestrator integration test drives a fake worker via `CockpitClient`.

---

**Self-review (per writing skill):** placeholder scan — none (all sketches are cross-linked
to their plan for full code). Internal consistency — phase ordering matches the dependency
constraint in §6; the `contract` API names in §4.1 match the Phase-1 plan. Scope — decomposed
into 4 plan-scoped subsystems, each independently shippable.
