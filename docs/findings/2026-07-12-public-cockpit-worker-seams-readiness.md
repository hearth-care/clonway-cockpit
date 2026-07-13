# Public cockpit worker seams — Foundry readiness

## Why a shared framework plan is required

Auto-Bookkeeper #1046 was generated as a dependency-free local cleanup. Current code disproves that
routing: xbook consumes private shell, walk, render and obs internals, the framework worker template
still generates `_home` and a legacy Home hook whose guidance recommends rebuilding `_host()`, and
xbook duplicates callback-backed Screen adapters because the framework does not expose one. Its
walk-to-walk routes now forward the observer, but Home statutory/deferred hooks still rebuild Host
and lose live stdio session fields. Fixing only xbook would preserve and regenerate the upgrade and
session-continuity hazards for every other worker.

This dependency-free companion is the sole public-API owner. #1046 becomes its exact-SHA xbook
consumer. Framework #114/#115 remain orthogonal Doctor/menu plans.

## Evidence inspected

- framework `origin/main@8694e302`, the current xbook pin;
- `shell.py`, `walk.py`, render help lines, obs ContextVar and package exports;
- worker-template cockpit entrypoint and tests;
- xbook app/walk/state/obs shims, two copied adapters and nested-call sites;
- current #1046/#1041/#1042 relationship comments;
- open framework #114/#115 scope/files;
- sibling worker private-use scan; and
- focused framework baseline: 172 passed in 0.36 seconds.

No provider, config, credentials, operator state, browser, network or durable effect ran.

## Decisions bound

- Public shell API: constant, callback Screen, model emit, blocking show, Home/activate/need/open/
  Doctor entry functions.
- Additive `ShellSession` plus opt-in pill/extra-key Host callbacks carry the exact active observer,
  authorization, audit and prompt context into nested Home routes; legacy callbacks remain default.
- Agent pulse pills still refuse before either callback and emit the existing `Sync skipped` model;
  this PR does not make sync agent-drivable.
- Public walk API: progress constant plus present/emit/await/remedy helpers.
- Public immutable default help tuple.
- Public scoped telemetry buffer carrying only events/owner, with supported test isolation and no
  raw ContextVar/token.
- Private implementations remain the one owner and old symbols remain during pinned-worker
  migration.
- Generated worker production source cannot consume the named framework-private seams.
- Generated workers expose and wire only a `ShellSession`-aware Home key hook; their docs direct
  nested work through public session helpers and forbid Host reconstruction.
- Behavior tests pin focus, observer, gate, audit, usage, crash, ShellOut, navigation and telemetry
  reset—not just import availability.
- Auto-Bookkeeper #1046 pins the merge SHA and owns real nested/reconcile/admissions acceptance.

## Package

- Work order: `docs/superpowers/work-orders/2026-07-12-public-cockpit-worker-seams.md`
- Design: `docs/superpowers/specs/2026-07-12-public-cockpit-worker-seams-design.md`
- Plan: `docs/superpowers/plans/2026-07-12-public-cockpit-worker-seams.md`
- Readiness: this file

## Acceptance that proves platform value

1. each public function drives the existing private owner and named failure semantics;
2. human/model/gate/audit/usage/focus output is unchanged, and session-aware nested opens retain the
   exact active Host rather than rebuilding it;
3. callback Screen forwards once and never becomes an agent observer;
4. telemetry scope handles owner/nested/cross-worker/all-BaseException/reset truth;
5. obs exports no ContextVar/private buffer;
6. generated workers use public Home entry plus the session-aware hook, retain the exact active
   Host for nested work, and guard against private-name/Host-rebuild relapse;
7. private aliases remain for old pins;
8. #114/#115 ownership stays separate; and
9. #1046 pins the merged SHA and passes real consumer acceptance before value is claimed.

## Verification state

- isolated worktree from `origin/main@8694e302`;
- focused baseline 172 passed in 0.36 seconds;
- source/template/downstream/parallel-PR inventory complete;
- exact APIs, TDD tasks, mutation rows, effects, compatibility and QA rejection gates bound;
- 856 artifact lines with 82 explicit implementation/acceptance gates;
- 1,122 current tests, all-file pre-commit and diff checks pass; and
- two independent read-only plan reviewers approved the final package after the generated Home
  hook/session-continuity and agent-pill boundaries were corrected.

## Value state

Blueprint only. After Foundry implementation, independent framework QA and merge, #1046 must pin
the merge SHA and re-drive its real human/agent nested journeys. An API existing on this branch is
not user value by itself.
