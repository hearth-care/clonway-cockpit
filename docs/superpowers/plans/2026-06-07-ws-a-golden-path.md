# WS-A — Golden Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** prove the agent→worker loop end-to-end (cross-process) + formalize the authorization-policy seam. Spec: `docs/superpowers/specs/2026-06-07-ws-a-golden-path-design.md`.

**Two PRs:** (1) clonway-cockpit framework seam + coverage/taxonomy docs; (2) xbook golden-path test + 44-model consistency on the bumped rev.

---

## PR 1 — clonway-cockpit: authorization-policy seam + honesty docs

### Task 1: `clonway_cockpit/approval.py` — the policy contract + reference impls
- [ ] Test `tests/test_approval.py`: `deny_all` → False; `approve_all` → True; `prompt_human` with an injected `input_fn` returning "y"/"n"/"" → True/False/False; `prompt_human` writes the prompt to the injected stream (not stdout).
- [ ] Implement `ApprovalPolicy = Callable[[Mapping[str, object]], bool]`, `deny_all`, `approve_all` (docstring: test/opt-in-only, never a default), `prompt_human(proposal, *, input_fn=input, out=sys.stderr)`.
- [ ] `uv run pytest tests/test_approval.py -q` → PASS.

### Task 2: enrich the proposal handed to a driver-side policy (non-breaking)
- [ ] Test (append `tests/test_cockpit_client.py`): `client.apply(token, approve=spy)` → spy sees `{"token": token}` (back-compat); `client.apply(token, approve=spy, proposal=gate["meta"])` → spy sees the full meta (incl. `equivalent_cli`).
- [ ] In `CockpitClient.apply`, add `proposal: Mapping | None = None`; `prop = proposal if proposal is not None else {"token": token}`; pass `prop` to `approve`. Signature stays back-compatible (xops.drive pinned to the old call keeps working).
- [ ] `uv run pytest tests/test_cockpit_client.py -q` → PASS.

### Task 3: drive-coverage honesty
- [ ] Strengthen `assert_drives_clean` docstring: it checks only the scripted paths; **static parity (`assert_render_model_parity`) is the exhaustive guarantee**; callers can inspect `{m.kind for m in stream}` for coverage.
- [ ] `docs/agent-screen-model.md`: add a "Coverage: what the gate proves" note (parity = exhaustive; drive = illustrative) + a "Model naming conventions" note (`kind` = `<domain>.<screen>`; stable `Row.id` patterns) seeding the xbook taxonomy PR2 fills in.

### Task 4: gate + ship PR1
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q` → green.
- [ ] Commit (focused), push, PR `feat(approval): authorization-policy seam + reference policies (WS-A)`, CI green, merge.

---

## PR 2 — xbook: the golden-path integration test + model consistency

### Task 5: hermetic fixture + cross-process drive
- [ ] Verify (read-only) how xbook reaches a schedule-bills review offline: what local state (`~/.xbook` cache / synced bills) the walk reads. Build a fixture seeding a temp HOME so `xbook --agent-stdio` can plan + present a real `walk.review` with NO live creds. If a full review isn't reachable offline, drive to the furthest structured screen and document it.
- [ ] `tests/integration/test_golden_path.py` (mark `integration`): `CockpitClient.spawn(["uv","run","xbook","--agent-stdio"], env=hermetic)`; assert home `schema_version`; drive toward the schedule-bills review; assert every frame `kind != "unstructured"`; the review carries bills/totals/`equivalent_cli`; gate emits `awaiting_apply`; **decline → `declined`, zero posts**; pure-JSON stdout; clean quit. Bump the clonway pin to PR1's SHA first.

### Task 6: in-process post-count half
- [ ] In the same test file: with the fake-Xero DI seam, drive schedule-bills to `confirm_apply`; `approve_all`+correct token → posts **once**; `deny_all`/wrong token → **zero**. (Reuse existing fake-Xero + apply-authorization patterns.)

### Task 7: 44-model consistency pass
- [ ] Audit the 44 `model_*` `kind`/`Row.id`/`meta` for a coherent `<domain>.<screen>` scheme + stable id patterns; fix outliers; keep parity + the per-screen tests green. Update the xbook side of the taxonomy doc/table.

### Task 8: gate + ship PR2
- [ ] xbook gate (ruff/format/mypy + `tests/cockpit` + `tests/integration/test_golden_path.py`) green; push; PR `test(integration): golden-path agent→worker proof + model consistency (WS-A)`; CI green; merge.

---

## Self-review
- Spec coverage: seam (T1–T2), coverage honesty (T3), golden-path proof (T5–T6), 44-model consistency + taxonomy (T3 framework note + T7 xbook). ✓
- Non-breaking: `apply` proposal param is additive; `deny_all` added not moved; defaults unchanged. ✓
- The one `[ASSUMPTION]` (offline review reachability) is a T5 verification step with a documented fallback. ✓
