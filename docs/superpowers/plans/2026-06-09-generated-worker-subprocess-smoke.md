# Generated Worker Subprocess Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a focused pytest smoke that generates a worker, installs it against this checkout, launches its real `--agent-stdio` CLI subprocess, and drives the scaffolded happy path with `CockpitClient`.

**Architecture:** Keep the change in `tests/test_worker_template.py` so template regressions are caught in the same unit suite that already proves generated-worker layout, contract, and safety. The test uses the existing `_generate(...)` helper, adds one local-install helper around `uv add`, then launches `uv run <worker> --agent-stdio` from the generated project root. Assertions inspect only protocol screen frames, confirming they are versioned and structured while avoiding a broader template redesign.

**Tech Stack:** Python 3.14 in this repo's `uv` test environment, pytest, Copier, Typer-generated console script, `subprocess.run`, `clonway_cockpit.agent.CockpitClient`, `clonway_cockpit.keys`.

---

## File Structure

- Modify `tests/test_worker_template.py`
  - Add `subprocess` import.
  - Add `_install_generated_worker_against_local_checkout(dst: Path) -> None`.
  - Add one subprocess smoke test next to AC-C6-4 coverage.

No production files or generated template files change in this workstream.

## Tasks

### Task 1: Add The Failing Subprocess Smoke

**Files:**
- Modify: `tests/test_worker_template.py`

- [ ] **Step 1: Add imports and a failing test that calls a not-yet-defined install helper**

Add `subprocess` only in Task 2. For RED, add the test first and intentionally call
`_install_generated_worker_against_local_checkout(...)` before defining it.

Insert this test after `test_ac_c6_4_generated_worker_serves_agent_and_drives_clean`:

```python
def test_ac_c6_4_generated_worker_cli_agent_stdio_subprocess_smoke(tmp_path: Path) -> None:
    from clonway_cockpit import agent, keys

    worker_id = "xgensubproc"
    dst = _generate(tmp_path, worker_id=worker_id)
    _install_generated_worker_against_local_checkout(dst)

    with agent.CockpitClient.spawn(
        ["uv", "run", worker_id, "--agent-stdio"],
        cwd=str(dst),
        timeout=10,
    ) as client:
        home = client.read_home()
        preflight = client.press("a")
        result = client.press(keys.ENTER)
        returned_home = client.press("x")
        extra = client.drain()

    frames = [home, preflight, result, returned_home, *extra]
    screen_frames = [frame for frame in frames if "kind" in frame]

    assert home["kind"] == "home"
    assert preflight["kind"] == "walk.preflight"
    assert result["kind"] == "walk.result"
    assert result["meta"]["ok"] is True
    assert result["meta"]["message"] == "Done."
    assert returned_home["kind"] == "home"
    assert screen_frames, frames
    assert all(frame["schema_version"] == "1.0" for frame in screen_frames)
    assert not any(frame["kind"] == "unstructured" for frame in screen_frames)
    assert client._proc is None or client._proc.poll() is not None
```

- [ ] **Step 2: Run the single test to verify RED**

Run:

```bash
uv run pytest tests/test_worker_template.py::test_ac_c6_4_generated_worker_cli_agent_stdio_subprocess_smoke -q
```

Expected:

```text
FAILED tests/test_worker_template.py::test_ac_c6_4_generated_worker_cli_agent_stdio_subprocess_smoke
NameError: name '_install_generated_worker_against_local_checkout' is not defined
```

- [ ] **Step 3: Commit the RED test**

```bash
git add tests/test_worker_template.py
git commit -m "test(template): cover generated worker CLI agent subprocess"
```

### Task 2: Add The Local Install Helper

**Files:**
- Modify: `tests/test_worker_template.py`

- [ ] **Step 1: Add the missing import**

Add this near the top with the standard-library imports:

```python
import subprocess
```

- [ ] **Step 2: Add the helper below `_generate(...)`**

```python
def _install_generated_worker_against_local_checkout(dst: Path) -> None:
    """Install the generated worker while pinning clonway-cockpit to this checkout."""
    subprocess.run(
        ["uv", "add", f"clonway-cockpit @ file://{_REPO_ROOT}"],
        cwd=dst,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
```

- [ ] **Step 3: Run the single test to verify GREEN or expose the next real failure**

Run:

```bash
uv run pytest tests/test_worker_template.py::test_ac_c6_4_generated_worker_cli_agent_stdio_subprocess_smoke -q
```

Expected:

```text
1 passed
```

If this fails because the generated CLI cannot launch or emits malformed frames, fix the minimal
broken path named by the failure. Do not broaden the smoke beyond the spec.

- [ ] **Step 4: Commit the helper**

```bash
git add tests/test_worker_template.py
git commit -m "test(template): install generated worker for subprocess smoke"
```

### Task 3: Run Template And Suite Verification

**Files:**
- Test only: `tests/test_worker_template.py`

- [ ] **Step 1: Run the worker-template test module**

Run:

```bash
uv run pytest tests/test_worker_template.py -q
```

Expected:

```text
8 passed
```

The exact runtime may vary because the new test performs a local `uv add`.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
uv run pytest -q
```

Expected:

```text
601 passed
```

- [ ] **Step 3: Check the working tree**

Run:

```bash
git status --short --branch
```

Expected:

```text
## Codex/generated-worker-subprocess-smoke...origin/main [ahead 4]
```

- [ ] **Step 4: Note residual verification**

Do not run `make check` unless the subprocess smoke or full pytest exposes formatting/type issues.
This workstream only changes tests and the full pytest gate is the acceptance check named in the
approved spec.

## Self-Review

- Spec coverage: Task 1 drives generated `uv run <worker> --agent-stdio` through
  `CockpitClient.spawn`; Task 2 installs the generated worker against the local checkout; Task 3
  runs the named verification commands.
- Placeholder scan: no unfinished markers or open-ended "add tests" instructions remain.
- Type consistency: helper name, `worker_id`, `dst`, and `CockpitClient.spawn(...)` signatures match
  the existing code.
