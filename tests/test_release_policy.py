import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _release_workflow() -> str:
    return (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def _pin_sync_doc() -> str:
    return (ROOT / "docs/pin-sync.md").read_text(encoding="utf-8")


def _public_history_checklist() -> str:
    return (ROOT / "docs/security/public-history-checklist.md").read_text(encoding="utf-8")


def _ci_workflow() -> str:
    return (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_project_version_has_matching_changelog_section() -> None:
    text = _changelog()

    assert f"## [{_project_version()}]" in text


def test_changelog_keeps_unreleased_section() -> None:
    text = _changelog()

    assert "## [Unreleased]" in text


def test_changelog_unreleased_section_has_unique_subheadings() -> None:
    text = _changelog()
    unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    subheadings = [line.strip() for line in unreleased.splitlines() if line.startswith("### ")]

    assert len(subheadings) == len(set(subheadings))


def test_release_workflow_tags_version_from_changelog() -> None:
    text = _release_workflow()

    assert "workflow_dispatch:" in text
    assert "branches: [main]" in text
    assert "pyproject.toml" in text
    assert "permissions:\n  contents: write" in text
    assert "tomllib" in text
    assert 'git rev-parse --verify --quiet "refs/tags/${TAG}"' in text
    assert 'gh release create "${TAG}"' in text
    assert "## [${VERSION}]" in text


def test_pin_sync_advisory_names_one_supported_tag_and_all_workers() -> None:
    text = _pin_sync_doc()

    assert text.count("Supported: v0.1.0") == 1
    assert 'rev = "v0.1.0"' in text
    assert 'rev = "main"' not in text
    for repo in (
        "auto-admissions",
        "auto-bookkeeper",
        "auto-hr",
        "auto-inspector",
        "auto-marketer",
        "Auto-Orchestrator",
        "Auto-Procurer",
        "auto-secretary",
    ):
        assert repo in text


def test_public_history_checklist_is_process_only() -> None:
    text = _public_history_checklist()

    assert "gitleaks detect --no-banner" in text
    assert "OAuth client configs" in text
    assert "API tokens" in text
    assert "service-account keys" in text
    assert "2026-06-11" in text
    for forbidden in ("hearth-care", "github.com", "@", "http://", "https://"):
        assert forbidden not in text


def test_ci_runs_pinned_gitleaks_pr_diff_scan() -> None:
    # Uses gitleaks CLI (no GITLEAKS_LICENSE required) pinned to a specific version.
    # The action-based approach (gitleaks/gitleaks-action) requires a paid license
    # even with GITLEAKS_ENABLE_UPLOAD_ARTIFACT=false — see ci.yml for the CLI form.
    text = _ci_workflow()

    assert "name: Gitleaks PR diff" in text
    assert "gitleaks_8.21.2" in text
    assert "continue-on-error: false" in text
    assert "gitleaks detect --no-banner" in text
