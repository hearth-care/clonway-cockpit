from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _release_workflow() -> str:
    return (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def test_project_version_has_matching_changelog_section() -> None:
    text = _changelog()

    assert f"## [{_project_version()}]" in text


def test_changelog_keeps_unreleased_section() -> None:
    text = _changelog()

    assert "## [Unreleased]" in text


def test_release_workflow_tags_version_from_changelog() -> None:
    text = _release_workflow()

    assert "workflow_dispatch:" in text
    assert "branches: [main]" in text
    assert "pyproject.toml" in text
    assert "permissions:\n  contents: write" in text
    assert "tomllib" in text
    assert "git rev-parse --verify --quiet \"refs/tags/${TAG}\"" in text
    assert "gh release create \"${TAG}\"" in text
    assert "## [${VERSION}]" in text
