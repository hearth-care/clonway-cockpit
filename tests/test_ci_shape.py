"""Shape tests for the reusable CI workflow and this repo's caller.

Asserts structural invariants that catch common mistakes (referencing @main,
missing workflow_call, dropped prod-import-package) before they reach CI or
propagate to worker repos via the template.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REUSABLE = _REPO_ROOT / ".github" / "workflows" / "reusable-ci.yml"
_CALLER = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_ADOPTION_DOC = _REPO_ROOT / "docs" / "ci-adoption.md"


def _on(workflow: dict) -> dict:
    # PyYAML parses the bare `on:` key as Python bool True; GitHub Actions also
    # accepts the quoted form "on". Handle both so tests remain correct regardless
    # of how the author wrote it.
    return workflow.get(True) or workflow.get("on") or {}


@pytest.fixture(scope="module")
def reusable() -> dict:
    return yaml.safe_load(_REUSABLE.read_text())


@pytest.fixture(scope="module")
def caller() -> dict:
    return yaml.safe_load(_CALLER.read_text())


# --- reusable-ci.yml invariants ---


def test_reusable_declares_workflow_call(reusable: dict) -> None:
    assert "workflow_call" in _on(reusable), "reusable-ci.yml must declare 'on: workflow_call'"


def test_reusable_has_lint_job(reusable: dict) -> None:
    assert "lint" in reusable["jobs"]


def test_reusable_has_test_job(reusable: dict) -> None:
    assert "test" in reusable["jobs"]


def test_reusable_has_prod_import_job(reusable: dict) -> None:
    assert "prod-import" in reusable["jobs"]


def test_reusable_prod_import_is_conditional(reusable: dict) -> None:
    job = reusable["jobs"]["prod-import"]
    assert "if" in job, "prod-import job must have an 'if' condition"


def test_reusable_has_documented_inputs(reusable: dict) -> None:
    inputs = _on(reusable).get("workflow_call", {}).get("inputs") or {}
    expected = {
        "lint-paths",
        "mypy-args",
        "pytest-args",
        "prod-import-package",
        "python-version",
        "runs-on",
        "uv-python-downloads",
    }
    missing = expected - set(inputs)
    assert not missing, f"reusable-ci.yml missing inputs: {missing}"


def test_reusable_has_no_concurrency_block(reusable: dict) -> None:
    assert "concurrency" not in reusable, (
        "reusable-ci.yml must NOT have a concurrency block — callers own their concurrency"
    )


def test_reusable_permissions_contents_read(reusable: dict) -> None:
    assert reusable.get("permissions", {}).get("contents") == "read"


def test_reusable_propagates_uv_python_downloads_inside_called_jobs(reusable: dict) -> None:
    """Caller workflow env does not reach reusable workflows, so this must be an input."""
    inputs = _on(reusable).get("workflow_call", {}).get("inputs") or {}
    assert inputs.get("uv-python-downloads", {}).get("default") == "automatic"

    for job_name in ("lint", "test", "prod-import"):
        env = reusable["jobs"][job_name].get("env") or {}
        assert env.get("UV_PYTHON_DOWNLOADS") == "${{ inputs.uv-python-downloads }}"


# --- caller ci.yml invariants ---


def test_caller_has_concurrency(caller: dict) -> None:
    assert "concurrency" in caller, "ci.yml (caller) must have its own concurrency stanza"


def test_caller_uses_line_references_reusable(caller: dict) -> None:
    jobs = caller.get("jobs") or {}
    uses_values = [job.get("uses", "") for job in jobs.values()]
    assert any("reusable-ci.yml" in u for u in uses_values), (
        "ci.yml must reference reusable-ci.yml in a 'uses:' line"
    )


def test_caller_uses_line_does_not_pin_main(caller: dict) -> None:
    jobs = caller.get("jobs") or {}
    for name, job in jobs.items():
        uses = job.get("uses", "")
        if "reusable-ci.yml" in uses:
            assert not uses.endswith("@main"), (
                f"job '{name}' pins reusable-ci.yml@main — use a tag, SHA, or relative path instead"
            )


def test_caller_passes_prod_import_package(caller: dict) -> None:
    jobs = caller.get("jobs") or {}
    for job in jobs.values():
        if "reusable-ci.yml" in job.get("uses", ""):
            with_block = job.get("with") or {}
            assert "prod-import-package" in with_block, (
                "The cockpit's ci.yml must pass prod-import-package to trigger the import-smoke job"
            )


def test_caller_pr_trigger_includes_synchronize(caller: dict) -> None:
    """PRs with an existing run-ci label must re-run CI on new commits."""
    on = _on(caller)
    pr_trigger = on.get("pull_request") or {}
    types = pr_trigger.get("types") or []
    assert "synchronize" in types, (
        "ci.yml pull_request trigger must include 'synchronize' so new commits run CI "
        "when the run-ci label is already applied"
    )


def test_caller_ci_job_checks_existing_run_ci_label(caller: dict) -> None:
    """The ci job condition must check for the run-ci label on synchronize events."""
    ci_text = _CALLER.read_text()
    assert "contains(github.event.pull_request.labels.*.name" in ci_text, (
        "ci.yml ci-job condition must use contains(...labels.*.name...) so synchronize "
        "events on PRs that already have run-ci label also run CI"
    )


def test_auto_orchestrator_adoption_uses_uv_python_downloads_input() -> None:
    text = _ADOPTION_DOC.read_text()
    section = text.split("### auto-orchestrator", 1)[1].split("\n### ", 1)[0]

    assert 'uv-python-downloads: "never"' in section
    assert "workflow-level `env:`" not in section
