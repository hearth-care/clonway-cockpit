from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNG_COLUMNS = ("Designed", "Coded", "Deployed", "Watched-working")
RUNG_VALUES = {"yes", "no", "—"}


def _doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_delivery_marks_governed_write_done() -> None:
    text = _doc("docs/persona-platform-architecture.md")
    governed_line = next(line for line in text.splitlines() if "| 6. **Governed write**" in line)

    cells = _cells(governed_line)
    assert cells[1:5] == ["yes", "yes", "no", "no"]
    assert "#51" in cells[5]
    assert "open" not in governed_line.lower()
    assert "parked" not in governed_line.lower()
    assert "not merged" not in governed_line.lower()


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _delivery_tables(text: str) -> list[list[str]]:
    delivery = text.split("## Delivery — agile thin slices (the running thread)", 1)[1]
    tables: list[list[str]] = []
    current: list[str] = []
    for line in delivery.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return [table for table in tables if set(RUNG_COLUMNS).issubset(_cells(table[0]))]


def test_delivery_tables_use_explicit_rung_columns() -> None:
    text = _doc("docs/persona-platform-architecture.md")
    tables = _delivery_tables(text)

    assert len(tables) == 2
    for table in tables:
        header = _cells(table[0])
        assert header[:6] == ["Slice", *RUNG_COLUMNS, "Refs"]


def test_delivery_table_rungs_use_closed_vocabulary_and_ladder_order() -> None:
    text = _doc("docs/persona-platform-architecture.md")

    for table in _delivery_tables(text):
        header = _cells(table[0])
        indexes = [header.index(column) for column in RUNG_COLUMNS]
        for row in table[2:]:
            cells = _cells(row)
            assert len(cells) == len(header), row
            values = [cells[index] for index in indexes]
            assert set(values) <= RUNG_VALUES, row
            seen_not_yes = False
            for value in values:
                if value != "yes":
                    seen_not_yes = True
                assert not (seen_not_yes and value == "yes"), row


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
    assert "has no live caller" not in text
