from pathlib import Path

from clonway_cockpit.shared_memory import Fact, SharedMemory, parse_frontmatter


def _write(base: Path, filename: str, content: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    path.write_text(content, encoding="utf-8")
    return path


FACT = """\
---
name: acme-supplier
kind: supplier
summary: ACME Care Supplies — PPE and incontinence; 30-day terms.
source: owner
as_of: 2026-06-08
---
ACME is the primary PPE supplier. Rep is Dana.
"""


def test_parse_frontmatter_basic():
    meta, body = parse_frontmatter(FACT)
    assert meta["kind"] == "supplier"
    assert meta["summary"].startswith("ACME Care Supplies")
    assert meta["as_of"] == "2026-06-08"
    assert body == "ACME is the primary PPE supplier. Rep is Dana."


def test_parse_frontmatter_absent():
    meta, body = parse_frontmatter("just a body, no fence")
    assert meta == {}
    assert body == "just a body, no fence"


def test_parse_frontmatter_unclosed_fence_is_not_a_fact():
    meta, body = parse_frontmatter("---\nkind: x\n(no closing fence)")
    assert meta == {}  # unterminated → treated as no frontmatter


def test_load_fact_fields_and_name_defaults_to_stem(tmp_path):
    _write(tmp_path, "acme-supplier.md", FACT)
    fact = SharedMemory(tmp_path).get("acme-supplier")
    assert isinstance(fact, Fact)
    assert fact.kind == "supplier"
    assert fact.source == "owner"
    assert fact.as_of == "2026-06-08"
    assert fact.body == "ACME is the primary PPE supplier. Rep is Dana."

    # name omitted → falls back to the file stem
    _write(tmp_path, "no-name.md", "---\nkind: preference\nsummary: call me X.\n---\nbody")
    assert SharedMemory(tmp_path).get("no-name").kind == "preference"


def test_missing_required_fields_are_skipped(tmp_path):
    _write(tmp_path, "ok.md", FACT)
    _write(tmp_path, "no-kind.md", "---\nsummary: orphan summary.\n---\nbody")
    _write(tmp_path, "no-summary.md", "---\nkind: person\n---\nbody")
    _write(tmp_path, "plain.md", "no frontmatter at all")
    names = [f.name for f in SharedMemory(tmp_path).all()]
    assert names == ["acme-supplier"]  # only the valid one


def test_get_miss_returns_none(tmp_path):
    _write(tmp_path, "acme-supplier.md", FACT)
    assert SharedMemory(tmp_path).get("nope") is None


def test_all_filters_by_kind_and_sorts_by_name(tmp_path):
    _write(tmp_path, "b.md", "---\nname: b\nkind: person\nsummary: Bob.\n---\n")
    _write(tmp_path, "a.md", "---\nname: a\nkind: person\nsummary: Ann.\n---\n")
    _write(tmp_path, "p.md", "---\nname: p\nkind: preference\nsummary: call me X.\n---\n")
    mem = SharedMemory(tmp_path)
    assert [f.name for f in mem.all()] == ["a", "b", "p"]
    assert [f.name for f in mem.all(kind="person")] == ["a", "b"]
    assert [f.name for f in mem.all(kind="preference")] == ["p"]


def test_recall_ranks_summary_above_body(tmp_path):
    # "ppe" in summary (high signal) should outrank "ppe" only in body
    _write(
        tmp_path,
        "in-summary.md",
        "---\nname: in-summary\nkind: supplier\nsummary: PPE supplier.\n---\nunrelated body",
    )
    _write(
        tmp_path,
        "in-body.md",
        "---\nname: in-body\nkind: supplier\nsummary: a supplier.\n---\nthey sell ppe sometimes",
    )
    _write(
        tmp_path,
        "unrelated.md",
        "---\nname: unrelated\nkind: person\nsummary: a person.\n---\nnothing here",
    )
    hits = SharedMemory(tmp_path).recall("ppe")
    assert [f.name for f in hits] == ["in-summary", "in-body"]  # unrelated excluded, summary first


def test_recall_kind_filter_limit_and_empty_query(tmp_path):
    _write(tmp_path, "s1.md", "---\nname: s1\nkind: supplier\nsummary: ppe supplier one.\n---\n")
    _write(tmp_path, "s2.md", "---\nname: s2\nkind: supplier\nsummary: ppe supplier two.\n---\n")
    _write(tmp_path, "p1.md", "---\nname: p1\nkind: person\nsummary: ppe-allergic resident.\n---\n")
    mem = SharedMemory(tmp_path)
    assert {f.name for f in mem.recall("ppe", kind="supplier")} == {"s1", "s2"}
    assert len(mem.recall("ppe", limit=1)) == 1
    assert mem.recall("") == []
    assert mem.recall("   ") == []


def test_recall_strips_query_punctuation(tmp_path):
    _write(tmp_path, "s.md", "---\nname: s\nkind: supplier\nsummary: ppe supplier.\n---\n")
    mem = SharedMemory(tmp_path)
    assert [f.name for f in mem.recall("ppe,")] == ["s"]  # trailing punctuation stripped
    assert [f.name for f in mem.recall("ppe supplier?")] == ["s"]  # both tokens survive


def test_kind_filter_is_case_insensitive(tmp_path):
    _write(tmp_path, "s.md", "---\nname: s\nkind: Supplier\nsummary: ppe supplier.\n---\n")
    mem = SharedMemory(tmp_path)
    assert [f.name for f in mem.all(kind="supplier")] == ["s"]
    assert [f.name for f in mem.recall("ppe", kind="SUPPLIER")] == ["s"]


def test_crlf_frontmatter_parses(tmp_path):
    _write(
        tmp_path, "crlf.md", "---\r\nname: crlf\r\nkind: person\r\nsummary: Ada.\r\n---\r\nbody\r\n"
    )
    fact = SharedMemory(tmp_path).get("crlf")
    assert fact is not None
    assert fact.kind == "person"
    assert fact.summary == "Ada."


def test_recall_ties_break_by_name(tmp_path):
    _write(tmp_path, "z.md", "---\nname: z\nkind: person\nsummary: ppe note.\n---\n")
    _write(tmp_path, "a.md", "---\nname: a\nkind: person\nsummary: ppe note.\n---\n")
    assert [f.name for f in SharedMemory(tmp_path).recall("ppe")] == ["a", "z"]


def test_missing_base_dir_returns_empty(tmp_path):
    mem = SharedMemory(tmp_path / "does-not-exist")
    assert mem.all() == []
    assert mem.recall("anything") == []
    assert mem.get("x") is None


def test_malformed_file_does_not_break_load(tmp_path):
    _write(tmp_path, "good.md", FACT)
    # a file with frontmatter fence but garbage content still loads the rest
    _write(tmp_path, "weird.md", "---\n: : :\nnonsense\n---\nbody")  # no kind/summary → skipped
    assert [f.name for f in SharedMemory(tmp_path).all()] == ["acme-supplier"]


def test_example_handbook_acceptance():
    # the shipped example handbook is real files in the repo
    handbook = Path(__file__).resolve().parent.parent / "examples" / "handbook"
    mem = SharedMemory(handbook)
    facts = mem.all()
    assert len(facts) >= 3  # at least the supplier, preference, calendar examples
    # recall finds the PPE supplier ahead of unrelated facts
    hits = mem.recall("ppe supplier")
    assert hits, "expected the ACME supplier example to be recalled"
    assert hits[0].kind == "supplier"
    # kind filter works against the real example set
    assert all(f.kind == "preference" for f in mem.all(kind="preference"))
