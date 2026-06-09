from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_delivery_marks_governed_write_done() -> None:
    text = _doc("docs/persona-platform-architecture.md")
    governed_line = next(line for line in text.splitlines() if "| 6 | **Governed write**" in line)

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
