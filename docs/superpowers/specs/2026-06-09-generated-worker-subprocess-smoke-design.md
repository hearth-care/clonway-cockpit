# Generated Worker Subprocess Smoke Design

**Date:** 2026-06-09
**Repo:** `clonway-cockpit`
**Status:** approved design -> spec review

## Goal

Prove that a worker generated from `worker-template/` can be driven through its real CLI
`--agent-stdio` subprocess path, not only through imported Python modules.

## Context

The framework contract says new workers are born agent-navigable. Today the unit coverage in
`tests/test_worker_template.py` generates a worker and imports its cockpit module directly. That
proves the template emits a host, a `serve_agent` wrapper, a modeled home screen, and contract
tests. It does not prove the generated console command can be installed, launched, and driven over
line-delimited JSON by `CockpitClient`.

`scripts/template_smoke.sh` performs the heavier install-and-run path for generated workers, but it
currently runs the generated worker's own pytest, ruff, mypy, and signals scan commands. It also
does not drive `<worker> --agent-stdio`.

The missing check is a focused golden path:

1. Generate a throwaway worker from the current checkout.
2. Install that generated worker against the same local checkout under test.
3. Launch `uv run <worker> --agent-stdio`.
4. Drive it with `clonway_cockpit.agent.CockpitClient`.
5. Assert the emitted frames are structured, versioned, and navigable on the scaffolded happy path.

## Design

### Test Location

Add the smoke to `tests/test_worker_template.py`, next to the existing generated-worker acceptance
coverage. This keeps the assertion tied to template changes and makes the gap visible in normal
pytest runs.

The test can reuse `_generate(...)` for the Copier step. It should create one worker with a unique
package name, then make the generated project installable by running:

```bash
uv add "clonway-cockpit @ file://<repo root>"
```

from inside the generated worker directory. That mirrors `scripts/template_smoke.sh` and proves the
worker uses the framework checkout being tested.

### Subprocess Driver

Launch the generated CLI with:

```python
agent.CockpitClient.spawn(["uv", "run", worker_id, "--agent-stdio"], cwd=str(dst), timeout=10)
```

Then drive the real JSON protocol:

- `read_home()` reads the first frame.
- `press("a")` opens the scaffolded `Capabilities` shelf and runs the example walk.
- `drain()` collects any extra frames emitted before the shell returns to home.
- `quit()` closes the child process through the normal client lifecycle.

The key sequence should stay on the generated scaffold's existing happy path. It should not add a
write-gated scaffold capability in this PR. The current example capability is explicitly read-only;
the smoke should preserve that safety floor.

### Assertions

The smoke should assert:

- the home frame has `kind == "home"`;
- every `ScreenModel` frame emitted during the happy path carries `schema_version == "1.0"`;
- no emitted `ScreenModel` frame has `kind == "unstructured"`;
- at least one driven frame proves the scaffolded example capability ran, such as a `walk.done`
  frame with the generated example message;
- the generated process exits cleanly after `quit()`.

The test should ignore protocol helper objects that are not `ScreenModel` frames, such as future
`input_request` or `confirm_request` objects, when checking `schema_version`. This smoke is about
versioned screen frames, not every possible protocol control message.

### Failure Mode Protected

This catches breaks where:

- the generated Typer entry point stops routing `--agent-stdio` to `serve_agent`;
- the generated package metadata stops exposing the console command correctly;
- a generated worker only works by direct import but fails once installed and launched;
- the real stdio pipe path emits malformed or unversioned frames;
- the scaffolded happy path becomes agent-blind and emits `unstructured`.

## Out Of Scope

- Adding a write-gated generated scaffold capability.
- Testing `--allow-apply` token authorization in the generated worker.
- Expanding `scripts/template_smoke.sh` into a full operator workflow.
- Changing the agent protocol shape or bumping `schema_version`.
- Updating consumer worker repos.

If a write-gated scaffold is added later, a separate workstream should extend this smoke to prove
that default `--agent-stdio` declines/dry-runs and `--allow-apply` still requires a matched token
and policy authorization.

## Test Plan

- Red: add the subprocess smoke and run only that test. It should fail before the install/launch
  helper exists or before the generated CLI is driven through `CockpitClient`.
- Green: implement the minimal helper/test code needed to install the generated worker locally,
  launch `uv run <worker> --agent-stdio`, and assert the frames.
- Run `uv run pytest tests/test_worker_template.py -q`.
- Run `uv run pytest -q`.
