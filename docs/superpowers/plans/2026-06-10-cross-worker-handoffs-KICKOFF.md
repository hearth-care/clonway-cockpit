# Kickoff prompt — cross-worker handoffs implementation

Paste the block below as the FIRST message of a fresh agent session (any capable model; the plan
is written so a smaller model can execute it without re-deriving design decisions).

---

Implement the **cross-worker task negotiation & handoffs** feature in this repo
(`clonway-cockpit`) by executing an already-approved plan. Do not redesign anything — the
thinking is done; your job is faithful, test-first execution.

**Use the superpowers workflow.** Invoke the `superpowers:executing-plans` skill now (or
`superpowers:subagent-driven-development` if you are dispatching one subagent per task) and
follow it to execute, task by task, with its review checkpoints:

- Plan: `docs/superpowers/plans/2026-06-10-cross-worker-handoffs.md` — 14 tasks, four stacked
  PR slices (A envelope → B reflex → C responder → D ledger/space). Every step has the exact
  code, command, and expected output. Tick the `- [ ]` checkboxes as you complete steps.
- Spec: `docs/superpowers/specs/2026-06-10-cross-worker-handoffs-design.md` — read it BEFORE
  the first task. It defines 12 safety invariants (S1–S12) and 20 dragons (D1–D20) the plan's
  tests pin. When the plan and the spec seem to disagree, STOP and re-read the named dragon
  before changing either; if still unresolved, ask the owner rather than improvising.

**Ground rules (non-negotiable):**

1. Work in a git worktree on the existing branch `claude/cross-worker-handoffs` (it carries the
   spec + plan). If the worktree `.claude/worktrees/cross-worker-handoffs` exists, enter it;
   otherwise create one from that branch. Never check out or commit to `main`.
2. Create the stacked branches exactly as the plan's Branch/PR map says
   (`claude/cwh-a-envelope` → `cwh-b-reflex` → `cwh-c-responder` → `cwh-d-ledger`), each off the
   previous. Do NOT open or merge any PR — the owner merges the stack on explicit say-so.
3. You may CREATE `src/clonway_cockpit/handoff.py`, `reflex.py`, `negotiation.py` and their four
   test files, and EDIT `docs/cross-worker-handoffs.md`, the delivery table in
   `docs/persona-platform-architecture.md`, and the plan's checkboxes. You may not touch any
   other module — if a task seems to need it, that's a misreading; re-read the task.
4. TDD as written: write the failing test, watch it fail, implement, watch it pass, commit.
   Write each new module in ONE Write call (imports + code together) — the repo's post-write
   ruff hook deletes imports that look unused (plan preamble, Dragon D17).
5. Gates: `uv run pytest -q` plus ruff/format/mypy as each task's ship-check step says.
   Conventional commit messages; no `Co-Authored-By` trailers, no "Generated with" footers.
6. Report honestly. When done, quote the actual pytest output for the three drive scenarios
   (worked example / degraded / stall). Never claim more than the tests demonstrated: this
   feature is DONE = coded + merged, and it is NOT "watched working" until the live Chat
   transport carries it — say so in your summary.

Start now: read the spec, then open the plan at Task 1.
