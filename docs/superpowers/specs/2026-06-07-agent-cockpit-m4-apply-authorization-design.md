# Agent-navigable cockpit — M4 (framework): apply-authorization handshake

**Date:** 2026-06-07 · **Repo:** `clonway-cockpit` · **Status:** approved (autonomous) → plan/build
**Predecessor:** M2 (#30) made agent mode a blanket dry-run (`confirm_apply` always declines, emits `walk.gate{declined,dry_run}`). M4 turns that into a reviewable, token-gated approval — so a *human-authorized* real post is possible in agent mode without writes ever being autonomous-by-accident.

## Problem
M2 guarantees an agent driving over stdio never posts. The north-star JTBD #2 ("guarded autonomous operation") needs the agent to be *able* to post — but only behind an explicit, per-gate, human-sign-off-able handshake. The framework must provide the **mechanism** (token handshake + observable audit) while keeping the **safe default** (no posts) and leaving the **policy** (route to a human) to the agent.

## Design (conservative, default-safe, opt-in)

- **Default unchanged.** With no opt-in, agent mode stays pure M2 dry-run: `confirm_apply` declines and emits `walk.gate{status:declined,reason:dry_run}`. Shipping M4 changes nothing for any current caller.
- **Opt-in guarded apply.** `serve_stdio(host, *, allow_apply=False)`. When `allow_apply=True`, serve_stdio installs an `authorize_apply` callback on the host; otherwise it's `None` (dry-run).
- **The handshake** (inside `walk.confirm_apply`, only when `ctx.dry_run` and `ctx.authorize_apply is not None`):
  1. mint a per-gate token (a monotonic nonce — unique per gate, so a stale/duplicated apply can't fire);
  2. emit `walk.gate{gate:"awaiting_apply", token, equivalent_cli}` (the proposal the agent routes up for sign-off);
  3. call `ctx.authorize_apply({token, equivalent_cli})` — the stdio pump reads the next message and returns True **iff** it is exactly `{"apply":true,"token":<token>}`;
  4. if authorized → emit `walk.gate{status:"applied",token}` and **return True** (the walk posts); else → emit `walk.gate{status:"declined",reason:"not_authorized"}` and return False.
- **Audit trail = the emitted frames.** The `awaiting_apply` / `applied` / `declined` `walk.gate` frames (carrying the token) are the on-the-wire record an operator/agent logs. The framework has no ambient `obs`; worker-side `obs.event` logging of applied gates is a follow-on when xbook adopts guarded apply.

## New surface
- `WizardContext.authorize_apply: Callable[[dict], bool] | None = None` (defaulted → backward-compatible).
- `Host.authorize_apply: Callable[[dict], bool] | None = None` (defaulted), threaded into the walk ctx in `shell._open_capability` alongside `dry_run`.
- `serve_stdio(..., allow_apply: bool = False)` — builds the token-checking `authorize_apply` from stdin when enabled.
- `walk._next_gate_token()` — monotonic nonce.

## Safety properties (tested)
1. **Default never posts** — even if the agent sends `{"apply":true,...}`, with `allow_apply=False` there is no `authorize_apply`, so the dry-run branch declines.
2. **Correct token posts** — `allow_apply=True` + `{"apply":true,"token":<emitted token>}` → the walk's post fires exactly once; an `applied` frame is emitted.
3. **Wrong / missing / stale token declines** — any non-matching apply (wrong token, a previous gate's token, `apply` not true, a different message, EOF) → no post, `declined` frame.
4. **Human cockpit + in-process driver unchanged** — defaults off; `confirm_apply` with `dry_run=False` still posts on the apply key.

## Non-goals
Worker `obs` logging of applied gates (follow-on); cryptographically-unguessable tokens (the monotonic nonce defeats stale/replay; the human-sign-off policy is the agent's, which the framework can't enforce); the xbook/xops wiring of `allow_apply` (consumer phase).
