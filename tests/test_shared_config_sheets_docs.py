from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_onboarding_docs_include_config_and_sheets_examples():
    text = _read("docs/onboarding-a-worker.md")

    assert 'rev = "<sha>"' not in text
    assert 'rev = "v0.1.0"' in text
    assert "docs/pin-sync.md" in text
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


def test_plan_contains_worker_migration_recipe():
    text = _read("docs/superpowers/plans/2026-06-fleet-audit-shared-config-sheets.md")

    assert "## Migration recipe" in text
    for worker in (
        "Auto-Bookkeeper",
        "Auto-Orchestrator",
        "Auto-Secretary",
        "Auto-HR",
        "Auto-Inspector",
        "Auto-Marketer",
        "Auto-Admissions",
    ):
        assert f"| {worker} |" in text
    assert "legacy single-underscore" in text
    assert "catalog/data YAML" in text
