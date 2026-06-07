# Agent-navigable cockpit — M2 (framework): `serve_stdio` design

**Date:** 2026-06-07
**Repo:** `clonway-cockpit` (framework). Consumers `xbook`/`xops` are OUT of scope this phase.
**Status:** Approved design → implementation planning
**Predecessors:** M1 (#28) + M1-rest (#29) — the `ScreenModel` layer + `on_screen` seam + in-process `CockpitDriver`. This phase is the subprocess transport on top of that core.

## Problem

M1/M1-rest gave every framework screen a semantic `ScreenModel`, emitted through `Host.on_screen`, recordable in-process by `CockpitDriver` (scripted keys → recorded stream). But the north-star job is for an **agent ("Ryan") to launch and drive the real cockpit binary** — a separate process — not just call the framework in-process. The missing piece is a **stdio transport**: a way for an external process to send keys and read `ScreenModel` snapshots over stdin/stdout, plus a **safety guarantee** that an agent driving a real walk cannot post to Xero.

## Goals / non-goals

**Goals**
1. `agent.serve_stdio(host)` — drive the real cockpit over line-delimited JSON on stdin/stdout, built as a thin pump over the existing `shell.run_cockpit` core (no new loop).
2. The wire protocol from the M1 design doc §5: keys + `snapshot`/`quit` commands in; `ScreenModel.to_dict()` (or `{"error":…}`) out.
3. Framework-enforced **dry-run** in agent mode: `walk.confirm_apply` always declines, so an agent can drive any walk end-to-end and see the review/blast-radius but **never posts**.
4. In-process protocol tests (pipe stdin/stdout) including a **gate-safety** test proving zero writes through the gate without authorization.

**Non-goals (this phase)**
- No `xbook`/`xops` `--agent` flags and **no pinned-rev bumps** in consumers — separate per-repo follow-ups.
- No `CockpitDriver.send()` interactive stepping — `serve_stdio` *is* the interactive path.
- No one-shot `--agent-script file.jsonl` mode — the in-process pipe test covers CI.
- No M4 apply-authorization handshake — the gate is hard dry-run in Phase 1.
- The worker-built walk **review screen** stays `unstructured` to the agent until M3 (it is not a framework primitive).

## Architecture

One new public function in `src/clonway_cockpit/agent.py`, beside `CockpitDriver`:

```python
def serve_stdio(host: shell.Host, *, stdin=sys.stdin, stdout=sys.stdout) -> None: ...
```

It binds three things to the existing `shell.run_cockpit(host, *, read_key, screen)` core — it does **not** reimplement any loop:

1. **out — `on_screen` observer.** Writes `json.dumps(model.to_dict()) + "\n"` to `stdout` and flushes; remembers the last model so `snapshot` can re-emit it.
2. **in — `read_key`.** Blocks reading `stdin` lines, parses one JSON message, and returns the key string the loop expects. Commands (`snapshot`/`quit`) and protocol errors are handled inside this function (re-reading until it has a real key to return).
3. **screen — `_NullScreen`** (already in `agent.py`): the agent reads models, not pixels.

Binding: `host_agent = replace(host, on_screen=on_screen, agent_mode=True)`, then `run_cockpit(host_agent, read_key=read_key, screen=_NullScreen())`.

Because `run_cockpit`'s screens emit via `on_screen` **before** they call `read_key` (the M1 ordering), the transport is naturally request/response: draw → emit JSON → block for the agent's next message.

## Wire protocol (line-delimited JSON, UTF-8, one object per line)

| Direction | Message | Effect |
|---|---|---|
| agent → app | `{"key": "down"}` (any key string the loop honours: `up`/`down`/`left`/`right`/`enter`/`esc`/`backspace`/`/`/`?`/letters/digits) | returned to the loop as the next keypress |
| agent → app | `{"cmd": "snapshot"}` | re-emit the current `ScreenModel` (does not advance) |
| agent → app | `{"cmd": "quit"}` | returns `"q"` to the loop → unwinds one level / quits at home |
| app → agent | `{ "kind": …, "regions": …, … }` (`ScreenModel.to_dict()`) | emitted at every draw |
| app → agent | `{"error": "<reason>"}` | malformed JSON, non-object, or unknown message; the current screen is held and `read_key` keeps reading |

**EOF on stdin** → `read_key` returns `"q"` (treated like `quit`), so a closed pipe unwinds the cockpit cleanly rather than hanging.

**Cadence caveats (documented, not bugs):**
- A draw emits exactly one frame. **Inert keys** (keys the current screen ignores) do not redraw, so they produce no frame — the agent should use `{"cmd":"snapshot"}` to re-poll if unsure.
- **Animated progress** screens push frames from a worker thread on a timer (deduped on semantic change, per M1-rest), so the agent may receive several unsolicited `walk.progress` frames between its key and the next interactive prompt. The agent treats app→agent as a stream.
- `"q"` unwinds **one level** (the screen-local quit semantics). A full teardown from deep in a flow is the agent sending `quit`/closing stdin until `serve_stdio` returns.

## Safety — framework-enforced dry-run

The single write gate is `walk.confirm_apply` (the only place a walk posts to Xero). In agent mode it must never post, regardless of what key the agent sends.

- Add `WizardContext.dry_run: bool = False` and `Host.agent_mode: bool = False` — both defaulted, so every existing construction (the live human cockpit, in-process `CockpitDriver`, all tests) is byte-identical.
- The shell already threads the observer into the walk context at the open-capability chokepoint:
  `ctx = replace(ctx, on_screen=host.on_screen)` → extend to
  `ctx = replace(ctx, on_screen=host.on_screen, dry_run=host.agent_mode)`.
- `walk.confirm_apply` still **reads the gate key** (preserving the one-message-per-interactive-screen cadence) but then, **if `ctx.dry_run`, returns `False`** unconditionally:

  ```python
  if ctx.read_key is not None:
      k = ctx.read_key()
      if ctx.dry_run:
          return False  # agent mode: never post, whatever the key
      return k in (keys.ENTER, "a", "A")
  return ctx.confirm_fn(prompt)
  ```

- `serve_stdio` sets `agent_mode=True`, so any walk driven over stdio is dry-run by construction. `CockpitDriver` leaves `agent_mode=False` (its existing scripted tests are unaffected); a test that wants dry-run opts in.

This is the design's Phase-1 posture. M4 later replaces the blanket decline with the explicit `{"apply":true,"token":…}` authorization handshake.

## Error handling

- **Malformed JSON / non-object / object with neither `key` nor a known `cmd`** → emit `{"error":"<reason>"}`, do not advance, keep reading. The cockpit never sees a bogus key.
- **A walk crash** is already isolated by the M1 shell guard (`_open_capability`) → the agent gets a clean `walk.result` with `ok=False`; no traceback crosses the boundary.
- **A raising `on_screen`** cannot happen here (the writer is ours), but the M1-rest `_safe_emit`/`_emit` guards still apply to every emit site.
- **Broken pipe / EOF** → unwind via `"q"`; `serve_stdio` returns normally.

## Components / boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `agent.serve_stdio` | stdio JSON pump: wire `read_key`/`on_screen`/`_NullScreen` to `run_cockpit`; parse/format the protocol | `shell.run_cockpit`, `model`, stdlib `json`/`sys` |
| `WizardContext.dry_run` (new field) | carry the agent dry-run flag into `confirm_apply` | — |
| `Host.agent_mode` (new field) | signal the shell to thread `dry_run` into walk contexts | — |
| `shell._open_capability` (1-line change) | thread `dry_run=host.agent_mode` into the walk ctx | `walk` |
| `walk.confirm_apply` (guard) | honour `ctx.dry_run` → decline | `keys` |

## Testing

All in-process (no real OS subprocess needed — `serve_stdio` takes a Python `host`; CI spawn of a real binary is a consumer/M2-worker concern):

1. **Round-trip:** preload an `io` stdin with JSON lines (`{"key":"c"}`, `{"key":"q"}`, …), capture stdout, parse the emitted JSON lines, assert the screen-kind stream (e.g. `home → shelf_menu/preflight → walk.result`).
2. **`snapshot`:** after a draw, `{"cmd":"snapshot"}` re-emits an identical current model without advancing.
3. **Protocol errors:** a non-JSON line and an unknown `{"cmd":"frob"}` each yield `{"error":…}` and the next real key still works (screen held).
4. **EOF/quit:** closing stdin (or `{"cmd":"quit"}` at home) makes `serve_stdio` return.
5. **Gate-safety (the safety test):** a registered walk whose handler would post via a **mock client**; drive it over stdio through the gate with `{"key":"a"}`; assert the mock's post was **never called** and the walk reports not-applied. Also assert `CockpitDriver` (agent_mode=False) is unchanged.

## Open questions

None blocking. Deferred by scope: the per-worker `--agent` invocation surface and rev bumps (consumer phase), the one-shot scripted mode (add only if a real CI need appears), and the M4 authorization handshake.
