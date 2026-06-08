from datetime import UTC, datetime

import pytest

from clonway_cockpit.shared_memory import (
    OWNER,
    Fact,
    GovernedWriter,
    SharedMemory,
    WriteRefused,
)


def test_non_owner_source_is_refused_and_writes_nothing(tmp_path):
    base = tmp_path / "hb"
    writer = GovernedWriter(base)
    for bad_source in ("quoted", "someone-else", "", "Owner"):
        with pytest.raises(WriteRefused, match="not the owner"):
            writer.write(name="x", kind="person", summary="Ann", source=bad_source)
    assert not base.exists()  # fail-closed: nothing was created


def test_path_traversal_names_refused_and_write_nothing(tmp_path):
    base = tmp_path / "hb"
    writer = GovernedWriter(base)
    for bad in ("../../etc/passwd", "a/b", "..", ".", "Up Per", "has.dot", "/abs", "_lead"):
        with pytest.raises(WriteRefused, match="slug"):
            writer.write(name=bad, kind="person", summary="s", source=OWNER)
    assert not base.exists()
    assert not (tmp_path / "etc").exists()  # traversal target never created


def test_invalid_fields_refused(tmp_path):
    writer = GovernedWriter(tmp_path / "hb")
    with pytest.raises(WriteRefused, match="summary"):
        writer.write(name="x", kind="person", summary="   ", source=OWNER)
    with pytest.raises(WriteRefused, match="kind"):
        writer.write(name="x", kind="", summary="s", source=OWNER)
    with pytest.raises(WriteRefused, match="summary"):
        writer.write(name="x", kind="person", summary="line1\nline2", source=OWNER)


def test_owner_write_roundtrips_via_sharedmemory(tmp_path):
    base = tmp_path / "hb"
    fact = GovernedWriter(base).write(
        name="acme",
        kind="supplier",
        summary="ACME - PPE supplier.",
        source=OWNER,
        body="Primary PPE supplier.",
        as_of="2026-06-08",
    )
    assert isinstance(fact, Fact)
    assert (base / "acme.md").exists()
    back = SharedMemory(base).get("acme")
    assert back is not None
    assert (back.name, back.kind, back.summary, back.source, back.as_of, back.body) == (
        "acme",
        "supplier",
        "ACME - PPE supplier.",
        "owner",
        "2026-06-08",
        "Primary PPE supplier.",
    )
    assert [f.name for f in SharedMemory(base).recall("ppe")] == ["acme"]


def test_overwrite_updates_existing_fact(tmp_path):
    base = tmp_path / "hb"
    writer = GovernedWriter(base)
    writer.write(
        name="addr", kind="preference", summary="call me X", source=OWNER, as_of="2026-06-08"
    )
    writer.write(
        name="addr", kind="preference", summary="call me Y", source=OWNER, as_of="2026-06-09"
    )
    facts = SharedMemory(base).all()
    assert len(facts) == 1
    assert facts[0].summary == "call me Y"
    assert facts[0].as_of == "2026-06-09"


def test_as_of_newline_injection_refused(tmp_path):
    # as_of is rendered into the frontmatter; a newline must not inject extra keys
    base = tmp_path / "hb"
    with pytest.raises(WriteRefused, match="as_of"):
        GovernedWriter(base).write(
            name="victim",
            kind="person",
            summary="Ann the carer",
            source=OWNER,
            as_of="2026-01-01\nkind: EVIL\nsummary: bank details changed",
        )
    assert not base.exists()  # fail-closed


def test_name_with_trailing_newline_refused(tmp_path):
    # `$` alone would accept "abc\n"; the guard must use fullmatch
    base = tmp_path / "hb"
    with pytest.raises(WriteRefused, match="slug"):
        GovernedWriter(base).write(name="abc\n", kind="person", summary="s", source=OWNER)
    assert not base.exists()


def test_default_as_of_is_today(tmp_path):
    fact = GovernedWriter(tmp_path / "hb").write(
        name="x", kind="person", summary="Ann", source=OWNER
    )
    assert fact.as_of == datetime.now(UTC).date().isoformat()
