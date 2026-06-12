# Plan — Template acceptance checklist for generated workers

> Source: 2026-06-12 fleet audit (operator-held) · Wave 0 · docs-only planning artifact.
> Implementation lands on this same branch per the fleet dispatch protocol.

## Context

The worker template generates a cockpit that is agent-navigable out of the box, but the
generated contract test is deliberately minimal: `tests/test_cockpit_contract.py.jinja`
drives only home `["q"]`, and its parity check is vacuously true until the worker adds
bespoke render modules. The audit's conclusion: the template proves a **baseline**, not
that a new worker's real flows are covered — "it gives a baseline, not proof that future
worker-specific flows stay covered." Nothing today tells the author of a brand-new
generated worker what evidence their first PR must contain before the worker is treated
as a conformant fleet member, and nothing tells them to grow the drive script as screens
are added.

## Goal

A written acceptance checklist — the minimum evidence a newly generated worker pastes
into its first PR — plus guidance on extending the generated contract tests as the worker
grows, so "born agent-navigable" stays true past the scaffold.

## Non-goals

- No changes to template code or test logic in this plan's implementation beyond docs
  (the checklist may be referenced from `worker-template/README.md.jinja`, which is a
  docs surface of the template).
- No CI enforcement of the checklist (a later template test could assert a richer drive
  script; out of scope here).
- Not the brownfield retrofit recipe (separate adoption-playbook plan) and not the
  conformance tracker (separate plan; a new worker's final checklist step is "add your
  row to the tracker").

## Deliverables

- [ ] Phase 1 — `docs/generated-worker-acceptance.md` defining the minimum acceptance
  evidence, each item with the command that produces it:
  1. **Home frame renders**: `uv run <worker> --agent-stdio` produces a first frame with
     `kind == "home"` and the current `schema_version` (paste the JSON line).
  2. **At least one capability walk**: a drive script that enters a real capability
     beyond home — frames for the walk screens, keyed by their `kind`s.
  3. **No `unstructured`**: `assert_drives_clean` passes over that extended script with
     `allow_unstructured=False`; any exception must be named and justified.
  4. **Dry-run decline path**: drive a write-bearing walk to its gate in agent mode and
     show the decline produces zero side effects (the dry-run-by-default posture).
  5. **Guarded apply against a mock**: with `--allow-apply` and a mocked external
     client, show the `awaiting_apply` frame and a token-matched apply hitting only the
     mock — never a live credential or external system.
- [ ] Phase 2 — "growing the gate" section: extend the generated
  `tests/test_cockpit_contract.py` key script in the same change that adds any shelf or
  screen; point `assert_render_model_parity` at every worker render module (not just
  `cli.cockpit`); treat the scaffold's `["q"]` script as a placeholder to outgrow, per
  the test's own docstring.
- [ ] Phase 3 — surface it from the template: a short "Acceptance evidence" section in
  `worker-template/README.md.jinja` linking the new doc, so every generated worker
  repo carries the pointer from birth.

## Acceptance criteria

- [ ] `docs/generated-worker-acceptance.md` exists with the five evidence items, each
  paired with a concrete command or test snippet and a description of the expected
  output (frame `kind`, gate state) an author can compare against.
- [ ] Item 5 explicitly forbids live credentials or external systems in acceptance
  evidence — mocks only — and item 3 states the name-and-justify rule for any
  `unstructured` exception.
- [ ] The "growing the gate" section quotes or cites the generated contract test's
  guidance and makes "extend the key script when you add screens" a checklist rule,
  not advice.
- [ ] `worker-template/README.md.jinja` gains the link; rendered template output remains
  valid Jinja (`make template-smoke` is the existing proof path).
- [ ] The checklist's final step instructs adding/updating the worker's row in the fleet
  conformance tracker (`docs/fleet-conformance.md`, planned separately) once it exists.

## Verification

```sh
ls docs/generated-worker-acceptance.md
grep -n 'home\|capability\|unstructured\|dry-run\|awaiting_apply' docs/generated-worker-acceptance.md | head
grep -n 'generated-worker-acceptance' worker-template/README.md.jinja
make template-smoke        # template still generates and tests green
uv run pytest -q           # framework suite unchanged
```

Expected: the acceptance doc covers all five evidence items, the template README links
it, and both the template smoke and the framework suite stay green.
