# Platform Mail Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the stdlib-only mail identity helper and generated-worker safety guard described in the platform mail identity spec.

**Architecture:** `clonway_cockpit.mail_identity` owns address validation, optional display-name resolution, and MIME `From` formatting. Worker repos still own Gmail/OAuth/send/draft clients. The worker template inherits a safety test that detects direct ungoverned mail construction unless it lives in an approved local mail adapter that imports the platform helper.

**Tech Stack:** Python stdlib (`dataclasses`, `email.utils`, `ast`, `pathlib`), pytest, copier template smoke tests, Ruff, mypy.

---

### Task 1: Mail Identity Helper

**Files:**
- Create: `src/clonway_cockpit/mail_identity.py`
- Create: `tests/test_mail_identity.py`

- [ ] **Step 1: Write failing tests**

Add tests for named formatting, preformatted header preservation, resolver success, resolver exception fallback, and malformed address failure.

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest -q tests/test_mail_identity.py`
Expected: import failure because `clonway_cockpit.mail_identity` does not exist yet.

- [ ] **Step 3: Implement helper**

Create `MailIdentity`, `MailIdentityError`, `format_from_header`, and `resolve_mail_identity`.

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest -q tests/test_mail_identity.py`
Expected: all tests pass.

### Task 2: Worker Template Guardrail

**Files:**
- Modify: `worker-template/tests/test_safety.py.jinja`
- Modify: `tests/test_worker_template.py`

- [ ] **Step 1: Write failing generated-worker test**

Add a template smoke assertion that the generated `tests/test_safety.py` contains and exercises the platform mail identity guard.

- [ ] **Step 2: Run template test to verify red**

Run: `uv run pytest -q tests/test_worker_template.py -k mail_identity`
Expected: failure because the generated safety test has no guard yet.

- [ ] **Step 3: Add generated safety guard**

Update `worker-template/tests/test_safety.py.jinja` with an AST/path scan for direct Gmail send/draft calls and direct MIME `From` construction outside approved local mail adapter files. Approved local mail adapters must import `clonway_cockpit.mail_identity`.

- [ ] **Step 4: Run template tests to verify green**

Run: `uv run pytest -q tests/test_worker_template.py -k mail_identity`
Expected: pass.

### Task 3: Docs And Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-11-platform-mail-identity-design.md`

- [ ] **Step 1: Update spec status**

Change status from planning PR to implementation PR and mention the helper/template guard now exists.

- [ ] **Step 2: Run focused and full gates**

Run:
- `uv run pytest -q tests/test_mail_identity.py tests/test_worker_template.py tests/test_docs_delivery_truth.py`
- `uv run ruff check src tests`
- `uv run ruff format --check src tests`
- `uv run mypy`

- [ ] **Step 3: Commit and update PR**

Commit all files and push to PR #86.
