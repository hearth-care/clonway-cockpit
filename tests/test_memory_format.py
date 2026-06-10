"""The shared markdown-memory *format* primitives, exposed on ``shared_memory`` for reuse by
both tiers (shared + private). The format is defined once: the read parses, the write renders,
and ``private_memory`` builds on the same primitives rather than duplicating them.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from clonway_cockpit.shared_memory import (
    Fact,
    is_safe_slug,
    load_fact,
    parse_frontmatter,
    render_fact,
    score,
    single_line,
    today,
)


def _write(base: Path, name: str, text: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(text, encoding="utf-8")
    return path


FACT = """\
---
name: acme
kind: supplier
summary: ACME — PPE supplier.
source: owner
as_of: 2026-06-08
---
Primary PPE supplier.
"""


def test_load_fact_parses_a_valid_fact(tmp_path):
    fact = load_fact(_write(tmp_path, "acme.md", FACT))
    assert isinstance(fact, Fact)
    assert fact.name == "acme"
    assert fact.kind == "supplier"
    assert fact.summary == "ACME — PPE supplier."
    assert fact.body == "Primary PPE supplier."


def test_load_fact_skips_non_facts(tmp_path):
    # missing the required `kind` → not a fact
    assert load_fact(_write(tmp_path, "note.md", "---\nsummary: no kind\n---\nbody")) is None


def test_load_fact_name_defaults_to_stem(tmp_path):
    path = _write(tmp_path, "stemmed.md", "---\nkind: preference\nsummary: call me X.\n---\nb")
    assert load_fact(path).name == "stemmed"


def test_score_ranks_name_summary_above_kind_body():
    name_hit = Fact("ppe", "x", "s", "b", None, None, Path("a"))
    body_hit = Fact("n", "x", "s", "ppe", None, None, Path("b"))
    assert score(name_hit, ["ppe"]) == 2  # name match: high signal
    assert score(body_hit, ["ppe"]) == 1  # body match: low signal


def test_parse_frontmatter_roundtrips():
    meta, body = parse_frontmatter(FACT)
    assert meta["kind"] == "supplier"
    assert body == "Primary PPE supplier."


def test_is_safe_slug_accepts_slugs_rejects_unsafe():
    for ok in ("milo", "a-b_c9", "x", "0"):
        assert is_safe_slug(ok)
    for bad in ("..", ".", "a/b", "/abs", "Has-Upper", "has.dot", "", "a b", "_lead", "x\n"):
        assert not is_safe_slug(bad)


def test_single_line_strips_and_rejects_multiline_or_empty():
    assert single_line("  ok ", "field") == "ok"
    for bad in ("", "   ", "a\nb", "a\rb"):
        with pytest.raises(ValueError, match="field"):
            single_line(bad, "field")


def test_render_fact_roundtrips_through_load_fact(tmp_path):
    text = render_fact("acme", "supplier", "ACME — PPE.", "owner", "2026-06-08", "Body here.")
    path = _write(tmp_path, "acme.md", text)
    fact = load_fact(path)
    assert fact.kind == "supplier"
    assert fact.source == "owner"
    assert fact.body == "Body here."


def test_today_is_utc_iso_date():
    assert today() == datetime.now(UTC).date().isoformat()


def test_is_safe_slug_bounds_length():
    # FBA-08: a valid-charset but overlong slug is rejected (so it never reaches the filesystem
    # as an ENAMETOOLONG OSError).
    assert is_safe_slug("a" * 128)
    assert not is_safe_slug("a" * 129)


def test_render_fact_normalises_crlf_body(tmp_path):
    # FBA-04: render normalises body line endings to \n so it matches what the reader returns.
    text = render_fact("n", "k", "s", "owner", "2026-06-10", "a\r\nb\rc")
    assert "\r" not in text
    fact = load_fact(_write(tmp_path, "n.md", text))
    assert fact.body == "a\nb\nc"
