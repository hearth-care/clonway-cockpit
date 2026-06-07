# WS-A — Golden Path: end-to-end agent-operation proof & seam (design)

**Status:** approved (design), 2026-06-07
**Workstream:** WS-A of the agentic-operating set (see `.claude/state/agentic-operating-workstreams.md`).
**Goal:** convert "agent-navigability proven in pieces" into "demonstrably true as one whole,
guarded in CI," and formalize the authorization-policy seam WS-B (autonomous policy) builds on.

## Why
Today the platform is proven in fragments: static parity, an in-process `CockpitClient` test,
`xops.drive` against a *fake* worker, and two audits that drove a real worker *by hand*. No
durable artifact proves the **whole loop on a real worker subprocess to the money gate**. The
keystone class of bug — green in-process, broken cross-process — is exactly what's unguarded.
WS-A closes that, and lays the seam so WS-B can swap the human approver for an autonomous
policy on a *tested* foundation (relax the control only once the test guarding it exists).

## Decisions (from brainstorming)
- **Hybrid proof.** Cross-process drive proves the wire + structured frames + gate-reached +
  dry-run safety; the "approve → exactly one post" count is asserted **in-process** against the
  existing fake-Xero DI seam. No fake-Xero switch enters production (kept clean ahead of WS-B).
- **Bundled scope.** WS-A = the golden-path proof + the authorization-policy seam +
  drive-coverage honesty + a 44-model consistency pass & taxonomy docs.

## Components

### 1. Authorization-policy seam (framework — clonway-cockpit)
A documented `ApprovalPolicy` contract + reference implementations in one shared place
(`clonway_cockpit/approval.py`):
- `deny_all(proposal) -> False` — the safe default (promoted as the canonical home; `xops.drive`
  already has a copy and keeps working — no forced change there).
- `approve_all(proposal) -> True` — the reference auto-approver the golden-path test uses and
  WS-B's allowlist policy refines. Documented **test/explicit-opt-in only**; never a default.
- `prompt_human(proposal) -> bool` — a reference interactive (terminal y/n) approver, so the
  human path has a concrete impl too.

`ApprovalPolicy = Callable[[Mapping[str, object]], bool]` (type alias).

**Enriched proposal.** The dict handed to the policy must carry enough to *decide*, not just a
token: at minimum `token` + `equivalent_cli` (already available at the gate). Where cleanly
accessible from the walk context, also include the apply identity (capability/walk title,
blast-radius summary). WS-A adds what's readily available; WS-B extends it for the allowlist.
`CockpitClient.apply` is updated to pass the full `awaiting_apply` frame's `meta` as the
proposal to `approve` (so the driver-side policy sees `equivalent_cli`, not just `token`).
Default behaviour is unchanged everywhere: dry-run / deny.

### 2. The golden-path test (centerpiece — xbook `tests/integration/`)
Two complementary halves, with the file documenting what each proves.
- **Cross-process half.** `clonway_cockpit.agent.CockpitClient.spawn(["…","xbook","--agent-stdio"])`
  in a hermetic env (temp HOME, no live creds) seeded with a fixture `.xbook` cache so the
  schedule-bills walk can reach a *real review* offline. Assert: `schema_version` on frames;
  every emitted screen structured (`kind != "unstructured"`); the review emits `walk.review`
  with bills/totals/`equivalent_cli`; the gate emits `walk.gate{awaiting_apply,token}`; on
  decline → `walk.gate{declined}` and **zero posts** (physically guaranteed — no creds);
  stdout a pure-JSON channel throughout; clean quit/EOF.
  - *[ASSUMPTION, verify in plan]:* xbook can plan bills from a seeded local cache without live
    Xero. If a full review isn't reachable offline, the cross-process half drives to the
    furthest reachable structured screen and asserts wire + gate-on-that-screen; the in-process
    half carries the post. The split is documented honestly either way.
- **In-process half.** With the existing fake-Xero DI seam, run schedule-bills to `confirm_apply`
  and assert: `approve_all` + correct token → `run_apply` posts **exactly once** to the fake;
  `deny_all` / wrong token → **zero**. Pins the money math.

### 3. Drive-coverage honesty (framework)
`assert_drives_clean` gains an optional coverage report (the set of `kind`s it actually drove),
and `docs/agent-screen-model.md` states plainly that **static parity is the exhaustive
guarantee** and the drive is illustrative of the scripted paths — so no one over-reads it.

### 4. 44-model consistency + taxonomy docs
Reconcile the `kind` / `Row.id` / `meta` conventions across the six xbook families (confirm a
coherent `<domain>.<screen>` scheme for `kind`, stable `Row.id` patterns; fix outliers), and
extend the `kind` / `Row.id` table + a "naming conventions" note in
`docs/agent-screen-model.md` so an agent author has the map.

## Shape / units
- **PR 1 — clonway-cockpit:** `approval.py` (contract + reference policies) + enriched proposal
  in `CockpitClient.apply` + `assert_drives_clean` coverage + the `agent-screen-model.md`
  taxonomy/coverage notes. Self-contained; no consumer changes.
- **PR 2 — xbook (on the bumped rev):** the golden-path integration test (both halves + the
  fixture) + the 44-model consistency fixes.

## Error handling / safety
- `approve_all` is a foot-gun; documented test/opt-in-only; default stays deny/dry-run.
- The cross-process subprocess runs without creds → cannot post even on a bug; the test never
  satisfies the gate against a real Xero.
- No new production seam (no fake-Xero switch), per the Hybrid decision.

## Testing
The golden-path test is the deliverable's proof. Plus framework unit tests for the reference
policies + the enriched proposal + the coverage report.

## Self-review
- Placeholders: the one `[ASSUMPTION]` (offline review reachability) is flagged for the plan to
  verify, with a documented fallback — not a TODO.
- Consistency: PR1 (framework, no behaviour change to defaults) precedes PR2 (xbook pins it) —
  matches the dependency.
- Scope: focused on the proof + seam + the bundled lightweight polish; nothing unrelated.
