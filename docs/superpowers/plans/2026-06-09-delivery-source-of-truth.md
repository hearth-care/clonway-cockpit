# Delivery Source Of Truth Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh persona-platform delivery docs so current repo-local state and fleet adoption status are explicit and regression-tested.

**Architecture:** This is a docs-first change with one lightweight pytest guard. The target docs remain the operator-facing source of truth; the test only pins the most failure-prone status claims so future updates stay current.

**Tech Stack:** Markdown docs, Python 3.12+ pytest, existing `make check` gates.

---

## File Structure

| File | Responsibility |
|---|---|
| `tests/test_docs_delivery_truth.py` | Regression tests for stale delivery claims and adoption-matrix presence |
| `docs/persona-platform-architecture.md` | Architecture-level delivery table and remaining-work statement |
| `docs/persona-platform-getting-started.md` | Operator-facing current status, adoption matrix, and pre-launch checklist |

## Task 1: Add Delivery Truth Regression Tests

**Files:**
- Create: `tests/test_docs_delivery_truth.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_delivery_marks_governed_write_done() -> None:
    text = _doc("docs/persona-platform-architecture.md")
    governed_line = next(
        line for line in text.splitlines() if "| 6 | **Governed write**" in line
    )

    assert "**DONE** (#51" in governed_line
    assert "open" not in governed_line.lower()
    assert "parked" not in governed_line.lower()
    assert "not merged" not in governed_line.lower()


def test_getting_started_has_current_fleet_adoption_matrix() -> None:
    text = _doc("docs/persona-platform-getting-started.md")

    assert "## Fleet adoption matrix" in text
    for repo in (
        "Auto-Bookkeeper",
        "Auto-Orchestrator",
        "Auto-HR",
        "Auto-Marketer",
        "Auto-Secretary",
        "Auto-Admissions",
    ):
        assert repo in text

    assert "clonway-cockpit PR #51" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_docs_delivery_truth.py -q`

Expected: FAIL because governed write is still documented as open/parked and the getting-started doc has no fleet adoption matrix.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_docs_delivery_truth.py
git commit -m "test(docs): pin persona platform delivery truth"
```

## Task 2: Refresh Architecture Delivery Status

**Files:**
- Modify: `docs/persona-platform-architecture.md`
- Test: `tests/test_docs_delivery_truth.py`

- [ ] **Step 1: Update the delivery table and remaining-work note**

Replace the stale delivery rows with:

```markdown
| 2 | **Retire xops-chat** — the dead fleet-router service + its IAM + the `xops.converse` chat code | **DONE** — Auto-Orchestrator #170 merged; any infrastructure cleanup script remains operator-run cleanup |
| 6 | **Governed write** (the owner-only trust boundary) | **DONE** (#51 — `GovernedWriter` refuses non-owner provenance and validates fact writes before touching disk) |
```

Replace the final "Still ahead" paragraph with:

```markdown
Still ahead: **per-persona multi-turn memory**; the **live Google Chat transport** (a Workspace
add-on — the in-memory wire is proven, the production surface is not built); **surfacing
model spend in the xops cost page** (the gateway already emits and fans out telemetry); and
**consumer adoption / pin rollout** so worker repos inherit the newest platform slices. Each gets
its own slice, its own PR, and its own design note linked back here. **Lock only the next slice.**
```

- [ ] **Step 2: Run the architecture-focused test**

Run: `uv run pytest tests/test_docs_delivery_truth.py::test_architecture_delivery_marks_governed_write_done -q`

Expected: PASS.

- [ ] **Step 3: Commit the architecture docs update**

```bash
git add docs/persona-platform-architecture.md
git commit -m "docs(platform): refresh delivery status"
```

## Task 3: Add Getting-Started Fleet Matrix And Checklist Split

**Files:**
- Modify: `docs/persona-platform-getting-started.md`
- Test: `tests/test_docs_delivery_truth.py`

- [ ] **Step 1: Replace stale status/checklist sections**

Update the status wording so it keeps the local-vs-live distinction and add this matrix:

```markdown
## Fleet adoption matrix

_Observed from fetched sibling repo `origin/main` refs on 2026-06-09. This is repo state, not a
production traffic claim._

| Worker | Repo | Package | Cockpit pin | Agent channel | Platform adoption note |
|---|---|---|---|---|---|
| Bookkeeper | Auto-Bookkeeper | `xbook` | `a75f7a02e9da214d6eb55cd6b6f444d03251b114` | `xbook --agent-stdio` + `--allow-apply` | Has xbook Chat bot, model gateway config, Milo gateway/shared-memory work; needs pin rollout for newest cockpit platform slices |
| Orchestrator | Auto-Orchestrator | `xops` | `200493cc77d4c3aa0bcb2a8d27ae1cc7f198a259` | `xops bridge --agent-stdio` | Drives workers via `CockpitClient`; oversight pane, not a persona |
| HR | Auto-HR | `xhr` | `21d68b3527fb37f6f6082324643cc68cf9cd11de` | `xhr --agent-stdio` + `--allow-apply` | Strong cockpit adoption; no live persona surface observed |
| Marketer | Auto-Marketer | `xletter` | `991b639e2f9d89544f831604c1419a03c877dd8f` | No `--agent-stdio` marker observed | Has Google Chat intake and model gateway telemetry; not yet a cockpit/persona adoption proof |
| Secretary | Auto-Secretary | `xquill` | `21597f4` | No `--agent-stdio` marker observed | Has its own live Milo forward-concierge and Chat digest; not this platform's cockpit/persona path |
| Admissions | Auto-Admissions | `xadmissions` | none observed | No `--agent-stdio` marker observed | Early worker; no cockpit pin observed |
```

Replace the old parked-work checklist with sections for:

- repo-local platform status
- model/operator config
- consumer adoption/pin work
- live-surface work

The text must not mention `clonway-cockpit PR #51` as an open/parked operator action.

- [ ] **Step 2: Run the full docs truth test**

Run: `uv run pytest tests/test_docs_delivery_truth.py -q`

Expected: PASS.

- [ ] **Step 3: Commit the getting-started docs update**

```bash
git add docs/persona-platform-getting-started.md
git commit -m "docs(platform): add fleet adoption matrix"
```

## Task 4: Final Verification

**Files:**
- All changed files

- [ ] **Step 1: Run full checks**

Run: `make check`

Expected:

- `ruff check .` passes.
- `ruff format --check .` passes.
- `mypy src` passes.
- `pytest -q` passes.

- [ ] **Step 2: Inspect git state**

Run: `git status --short`

Expected: only intentional uncommitted files, if any. Ideally clean after the plan commits.

- [ ] **Step 3: Self-review the docs**

Run:

```bash
rg -n "PR #51|parked|not merged|Fleet adoption matrix|Governed write" docs/persona-platform-architecture.md docs/persona-platform-getting-started.md
```

Expected: governed write appears as done; no stale `PR #51 open/parked/not merged` claim remains.
