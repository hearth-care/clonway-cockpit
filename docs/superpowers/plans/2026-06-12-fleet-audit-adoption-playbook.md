# Plan — Worker cockpit adoption playbook

> Source: 2026-06-12 fleet audit (operator-held) · Wave 0 · docs-only planning artifact.
> Implementation lands on this same branch per the fleet dispatch protocol.

## Context

A worker scaffolded from `worker-template/` is born agent-navigable, and
`docs/onboarding-a-worker.md` ("Agent channel — inherited, not wired by hand") says so —
but it only covers the greenfield path. The fleet's gap is **brownfield**: the audit found
xletter and xquill expose no `--agent-stdio` at all, and xhr's `--agent-stdio` can block
~60s before a first frame, while xbook, xadmissions, xcqc, xsource and the xops bridge
already emit structured frames. There is no recipe for retrofitting the agent channel onto
a worker that predates the template.

A second, related audit gap: **`unstructured` frame semantics are stated more strongly than
they are implemented.** README says a screen with no model "fails the build"; the real
contract is more nuanced — `assert_render_model_parity` is the exhaustive static check,
while `assert_drives_clean(host, keys, allow_unstructured=False)` only rejects
`unstructured` on the paths the key script reaches, and `allow_unstructured=True` is a
legitimate, deliberate opt-out (`src/clonway_cockpit/contract.py`,
`docs/agent-screen-model.md` "Coverage: what the gate actually proves"). Adopting workers
need that nuance spelled out, or they will either over-trust a green drive-clean or
silently allow-list everything.

## Goal

A single docs recipe (`docs/adopting-the-agent-channel.md`) an implementing agent can
follow start-to-finish to retrofit `--agent-stdio` onto an existing worker, including the
exact conformance tests to add and the rules for any allowed `unstructured` output.

## Non-goals

- No changes to framework code, the template, or any worker repo — this playbook is the
  recipe those follow-up PRs will cite.
- Not the conformance tracker (separate plan; the playbook's final step is "update your
  row in the tracker").
- Not a rewrite of `docs/agent-screen-model.md` — the playbook links it for protocol
  detail and only adds the adoption-ordering and semantics guidance it lacks.

## Deliverables

- [x] Phase 1 — `docs/adopting-the-agent-channel.md` with the retrofit recipe, in order:
  1. Bump the cockpit pin to the supported tag per `docs/pin-sync.md`; `uv lock`.
  2. Add `--agent-stdio` / `--allow-apply` CLI flags mirroring
     `worker-template/src/{{ package_name }}/cli/__init__.py.jinja`.
  3. Wire `serve_agent_stdio(_host(agent_mode=True))`; if the worker rebuilds its host
     inside callbacks, use the ambient `_AGENT_MODE` pattern from
     `docs/agent-screen-model.md` so the flag survives the rebuild — this is the
     classic retrofit trap, call it out explicitly.
  4. Add the two contract tests: `contract.assert_render_model_parity(<render modules>)`
     pointed at every module defining a page-framing `render_*` (not just `cli.cockpit`),
     and `contract.assert_drives_clean(host, <keys>)` with a key script that walks at
     least one real capability, not just home `["q"]`.
  5. Add a subprocess smoke via `CockpitClient.spawn` (the pattern in
     `tests/test_worker_template.py`) so the channel is proven across a process boundary.
  6. First-frame latency budget: home must frame before any slow integration warm-up
     (the audit's xhr finding — ~60s before a first frame makes a driving agent assume a
     hang). State the rule: defer network/credential work until after the home frame, or
     emit a structured progress note.
- [x] Phase 2 — "`unstructured` semantics" section in the same doc: what each gate
  proves (static parity = exhaustive; drive-clean = path-specific), when
  `allow_unstructured=True` is acceptable, and the rule that every allowed
  `unstructured` path is named and justified in the worker repo (and mirrored in its
  conformance-tracker row's "known exceptions" column).
- [x] Phase 3 — cross-links: `docs/onboarding-a-worker.md`'s agent-channel section gains
  a "retrofitting an existing worker" pointer to the new doc; the new doc names the
  audit's adoption truth (who has the channel, who doesn't) without duplicating the
  tracker.

## Acceptance criteria

- [x] `docs/adopting-the-agent-channel.md` exists and contains all six recipe steps in
  the order above, each with the framework symbol it touches named exactly
  (`serve_agent_stdio`, `assert_render_model_parity`, `assert_drives_clean`,
  `CockpitClient.spawn`).
- [x] The agent-mode-on-host-rebuild trap and the first-frame latency rule each have
  their own subsection — a reader retrofitting xletter or xquill cannot miss them.
- [x] The `unstructured` section distinguishes static parity from drive-clean coverage
  and states the name-and-justify rule for `allow_unstructured` — consistent with
  `src/clonway_cockpit/contract.py` (no claim stronger than the code).
- [x] The playbook requires the drive-clean key script to reach beyond home, and says
  why the template's default `["q"]` is vacuous for bespoke screens.
- [x] `docs/onboarding-a-worker.md` links the new doc; no other file is modified.

## Verification

```sh
ls docs/adopting-the-agent-channel.md
grep -n 'serve_agent_stdio\|assert_render_model_parity\|assert_drives_clean\|CockpitClient' docs/adopting-the-agent-channel.md
grep -n 'allow_unstructured' docs/adopting-the-agent-channel.md src/clonway_cockpit/contract.py
grep -n 'adopting-the-agent-channel' docs/onboarding-a-worker.md
uv run pytest -q     # unchanged; docs-only change stays green
```

Expected: the playbook exists naming all four framework symbols, its `unstructured`
guidance matches the `contract.py` signature, and the onboarding doc links it.

## HANDOFF NOTES

**Status: COMPLETE** — all phases implemented and gates green.

- Phase 1: `docs/adopting-the-agent-channel.md` written with all six recipe steps.
- Phase 2: `unstructured` semantics section included in the same doc.
- Phase 3: `docs/onboarding-a-worker.md` agent-channel section updated with retrofit pointer.
- Gates: `uv run pytest -q` → 956 passed; `uv run pre-commit run --all-files` → all Passed.
- No deviations from plan. No operator TODO items.
- Next step: operator QA and merge.
