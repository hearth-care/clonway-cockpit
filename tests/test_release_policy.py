from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_project_version_has_matching_changelog_section() -> None:
    text = _changelog()

    assert f"## [{_project_version()}]" in text


def test_changelog_keeps_unreleased_section() -> None:
    text = _changelog()

    assert "## [Unreleased]" in text
