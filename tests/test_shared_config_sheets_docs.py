from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_onboarding_docs_include_config_and_sheets_examples():
    text = _read("docs/onboarding-a-worker.md")

    assert "## Shared config loader" in text
    assert "class WorkerConfig(BaseModel):" in text
    assert "load_config(WorkerConfig" in text
    assert "## Shared Sheets helper" in text
    assert "SheetsClient(service, spreadsheet_id" in text


def test_changelog_records_public_config_and_sheets_surfaces():
    text = _read("CHANGELOG.md")

    assert "## [Unreleased]" in text
    assert "`clonway_cockpit.config`" in text
    assert "`clonway_cockpit.gsheets`" in text
    assert "`clonway-cockpit[config]`" in text
