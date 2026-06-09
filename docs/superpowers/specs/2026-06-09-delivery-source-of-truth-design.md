# Delivery Source Of Truth Refresh Design

**Date:** 2026-06-09
**Repo:** `clonway-cockpit`
**Status:** approved -> plan/build

## Goal

Refresh the persona-platform delivery documentation so it reflects the current framework state and
gives future agents one compact, verified adoption matrix instead of stale PR notes.

## Context

`clonway-cockpit` is now more than the cockpit framework: it also owns the model gateway, shared
memory, persona identity, souls, group chat, receptionist, colleague wire, conversation trust
boundary, and governed shared-memory write.

The delivery docs lag that reality. In particular:

- `docs/persona-platform-architecture.md` still says governed write is "PR #51 open, parked".
- `docs/persona-platform-getting-started.md` still lists clonway-cockpit PR #51 as operator work.
- The docs mention xbook's stale pin but do not show the broader fleet adoption state.

## Observed Fleet State

Observed from fetched sibling repo `origin/main` refs on 2026-06-09:

| Worker | Repo | Package | Cockpit pin on `origin/main` | Agent channel | Persona/platform notes |
|---|---|---|---|---|---|
| Bookkeeper | Auto-Bookkeeper | `xbook` | `a75f7a02e9da214d6eb55cd6b6f444d03251b114` | `xbook --agent-stdio` + `--allow-apply` documented/tested | Has xbook Chat bot, model gateway config, Milo gateway/shared-memory work; still not a live platform Chat transport in this repo |
| Orchestrator | Auto-Orchestrator | `xops` | `200493cc77d4c3aa0bcb2a8d27ae1cc7f198a259` | `xops bridge --agent-stdio`; drives workers via `CockpitClient` | PR #170 is merged on `origin/main`; xops is oversight, not a persona |
| HR | Auto-HR | `xhr` | `21d68b3527fb37f6f6082324643cc68cf9cd11de` | `xhr --agent-stdio` + `--allow-apply` documented/tested | Strong cockpit adoption; no persona-live surface observed |
| Marketer | Auto-Marketer | `xletter` | `991b639e2f9d89544f831604c1419a03c877dd8f` | No `--agent-stdio` marker observed on `origin/main` | Has Google Chat/intake and model gateway telemetry; not a cockpit/persona adoption proof |
| Secretary | Auto-Secretary | `xquill` | `21597f4` | No `--agent-stdio` marker observed on `origin/main` | Has its own live Milo forward-concierge and Chat digest; not this platform's cockpit/persona path |
| Admissions | Auto-Admissions | `xadmissions` | none observed | No `--agent-stdio` marker observed on `origin/main` | Early worker; no cockpit pin observed |

This matrix must be labelled as repo-observed state, not production verification.

## Design

### Architecture doc

Update the delivery table in `docs/persona-platform-architecture.md`:

- Mark governed write as done on PR #51.
- Mark xops-chat retirement as merged on Auto-Orchestrator PR #170, with any external cleanup script
  left as operator cleanup if still needed.
- Keep "still ahead" focused on actual remaining slices: per-persona multi-turn memory, live Google
  Chat transport, xops model-spend consumer, and worker adoption/pin rollout.

### Getting-started doc

Update `docs/persona-platform-getting-started.md`:

- Keep the practical "what can I use today" section.
- Add an "Adoption matrix" section with the observed fleet table above.
- Split the checklist into:
  - repo-local platform status
  - model/operator config
  - consumer adoption/pin work
  - live-surface work
- Remove stale "clear parked PR #51" wording.
- Avoid claiming a live deployed persona surface unless the sibling repo docs explicitly demonstrate it.

### Regression test

Add a lightweight docs test to prevent this exact drift from returning:

- `docs/persona-platform-architecture.md` must not say PR #51 is open/parked/not merged.
- It must mark governed write as done.
- `docs/persona-platform-getting-started.md` must include adoption matrix rows for the six observed
  worker repos.
- It must not list clonway-cockpit PR #51 as operator work.

## Out Of Scope

- Updating sibling repo pins.
- Verifying production traffic or deployed environment flags.
- Building the Chat transport.
- Writing specs/plans for the remaining nine workstreams.

## Test Plan

- Red: add the docs regression test and run it against the stale docs; it must fail.
- Green: update the docs until the test passes.
- Run `uv run pytest tests/test_docs_delivery_truth.py -q`.
- Run full `make check`.
