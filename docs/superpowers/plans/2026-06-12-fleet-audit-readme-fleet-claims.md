# Plan — README wording: framework guarantees vs fleet adoption

> Source: 2026-06-12 fleet audit (operator-held) · Wave 0 · docs-only planning artifact.
> Implementation lands on this same branch per the fleet dispatch protocol.

## Context

README's "Agent-navigable by construction" section claims a fleet-universal property:
"Every Clonway worker is one binary serving two audiences … This is a structural property
of the framework, enforced in CI, inherited by every worker — not a per-worker add-on."
The audit found that is true of the framework and of template-generated workers, but not
of the fleet: xletter and xquill expose no `--agent-stdio`; xhr's channel can block ~60s
before a first frame; only xbook, xadmissions, xcqc, xsource and the xops bridge emit
structured frames today. The discipline propagates only when a consumer bumps its pin and
runs the conformance gate — the framework cannot enforce it on stale consumers from inside
this repo.

A second wording gap from the same audit: the README advertises the persona platform
broadly, while its true status — tested libraries plus local demos, no live Chat
transport, consumers inherit only after a pin bump — is buried in
`docs/persona-platform-getting-started.md` ("Current status — read this first"). A reader
of README alone over-reads "ships the persona platform" as live surface readiness.

## Goal

README states exactly what the framework and the generator guarantee, what a consumer
must do to earn those guarantees, and where current adoption truth lives — plus a
top-of-README status banner separating built-and-tested from live.

## Non-goals

- No weakening of the real guarantees: parity + drive-clean enforcement for adopted
  consumers and template-generated workers is true and stays stated plainly.
- No new adoption data in README — adoption truth belongs to the conformance tracker
  (planned separately as `docs/fleet-conformance.md`); README only links it.
- No restructuring of README beyond the affected sections; no changes to
  `docs/agent-screen-model.md` or the template.

## Deliverables

- [x] Phase 1 — rewrite the "Agent-navigable by construction" framing: replace
  "enforced in CI, inherited by every worker" with the three-part truth —
  (a) the framework ships the gate (`contract.py`) and the channel (`agent.py`);
  (b) every template-generated worker is born conformant;
  (c) an existing consumer is conformant only after it pins the supported tag
  (`docs/pin-sync.md`), wires `--agent-stdio`, and runs
  `assert_render_model_parity` + `assert_drives_clean` in its CI.
  Link the conformance tracker for who currently meets (c). If the tracker doc has not
  landed yet when this is implemented, link `docs/pin-sync.md` and the getting-started
  adoption matrix instead and leave a TODO naming the tracker path.
- [x] Phase 2 — soften the absolute `unstructured` claim in "How it's enforced": "a
  screen with no model fails the build" describes static parity; add the one-line
  nuance that drive-clean covers driven paths and `allow_unstructured` exists for
  named, justified exceptions (consistent with `docs/agent-screen-model.md`
  "Coverage: what the gate actually proves").
- [x] Phase 3 — add a status banner near the top of README (before or just after the
  opening paragraphs) with one line per layer: framework spine (built, tested, in use);
  worker template (generates conformant workers); persona platform (tested libraries +
  local demos, no live Chat transport); fleet adoption (uneven — see tracker). Link
  `docs/persona-platform-getting-started.md` as the detailed status page.
- [x] Phase 4 — sweep `CLAUDE.md` for the same fleet-universal wording ("beneath every
  Clonway autoworker", "so every autoworker is …") and align it with the same
  guarantee-vs-adoption distinction, keeping its enforcement guidance intact.

## Acceptance criteria

- [x] README no longer asserts that every fleet worker is agent-navigable today; every
  fleet-wide statement is conditioned on pin + conformance, or scoped to
  template-generated workers.
- [x] README states the consumer obligations (pin supported tag, wire `--agent-stdio`,
  run the two contract asserts in CI) in one findable place.
- [x] The status banner exists, distinguishes the four layers above, and links the
  getting-started status doc; no README claim contradicts that doc.
- [x] The `unstructured` sentence in README matches the semantics documented in
  `docs/agent-screen-model.md` (path-specific drive-clean, named exceptions).
- [x] No technical capability that IS guaranteed (parity gate, guarded apply, dry-run
  default, schema versioning) gets hedged — the edit narrows scope claims only.

## Verification

```sh
grep -n 'inherited by every worker' README.md          # expect: no match
grep -n 'fleet-conformance\|pin-sync' README.md        # expect: at least one link
grep -ni 'status' README.md | head                     # banner present near the top
grep -n 'allow_unstructured\|driven paths\|drive-clean' README.md
grep -n 'every Clonway autoworker\|every autoworker' CLAUDE.md   # expect: reworded or conditioned
uv run pytest -q                                       # unchanged; docs-only change stays green
```

Expected: the absolute fleet-wide claim is gone, consumer obligations and the status
banner are present, and the suite is untouched.

## HANDOFF NOTES

**Status:** COMPLETE — all four phases implemented and verified.

**Phase:** Done. All checkboxes ticked.

**What was done:**
- Phase 1: Rewrote "Agent-navigable by construction" opening — replaced "enforced in CI, inherited by every worker" with the (a)/(b)/(c) three-part truth. Linked `docs/pin-sync.md` and the getting-started adoption matrix; left a TODO for `docs/fleet-conformance.md` once it lands.
- Phase 2: Expanded "How it's enforced" to distinguish static parity (`assert_render_model_parity`) from dynamic drive-clean (`assert_drives_clean`), and noted `allow_unstructured=True` for named exceptions.
- Phase 3: Added "## Framework status" table before "## Agent-navigable by construction" with four rows (spine / template / persona platform / fleet adoption) and a link to `docs/persona-platform-getting-started.md`.
- Phase 4: Rewrote CLAUDE.md opening — removed "beneath every Clonway autoworker" and "so every autoworker is …"; added a sentence explaining that consumers earn the property by pinning + wiring.

**Decisions taken:**
- `docs/fleet-conformance.md` had already landed on main (the plan assumed it might not be there). Linked it directly in Phase 1 rather than using the fallback (pin-sync + adoption matrix + TODO). Deviation from the plan's fallback path, in the direction the plan intended.
- No structural changes to README beyond the affected sections; no changes to `docs/agent-screen-model.md` or the template (per non-goals).

**Known-failing tests:** None — 956 passed, all pre-commit hooks green.
