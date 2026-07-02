"""Private per-persona working memory — each persona owns an isolated store nobody else reads,
optionally scoped per thread/space for multi-turn. Reuses the shared markdown ``Fact`` format;
the load-bearing guarantee is isolation, and the owner-only shared boundary stays intact.
"""

import pytest

from clonway_cockpit.private_memory import WORKING, PersonaMemory, PrivateScope
from clonway_cockpit.shared_memory import OWNER, GovernedWriter, SharedMemory, WriteRefused, today

# --- round-trip: a persona remembers within its own scope -----------------------------------


def test_remember_roundtrips_and_defaults_as_of_today(tmp_path):
    fact = PersonaMemory(tmp_path, "milo").working.remember(
        name="xero-login", kind="note", summary="Xero MFA via authenticator app", body="detail."
    )
    assert fact.as_of == today()
    got = PersonaMemory(tmp_path, "milo").working.get("xero-login")
    assert got is not None
    assert got.summary == "Xero MFA via authenticator app"
    assert got.body == "detail."


def test_remember_then_recall_within_a_thread(tmp_path):
    pm = PersonaMemory(tmp_path, "milo")
    pm.thread("space-123").remember(
        name="ask", kind="note", summary="owner asked for the Q2 figures"
    )
    hits = pm.thread("space-123").recall("Q2 figures")
    assert [f.name for f in hits] == ["ask"]


def test_remember_overwrites_same_name(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="n", kind="k", summary="first")
    w.remember(name="n", kind="k", summary="second")
    fresh = PersonaMemory(tmp_path, "milo").working
    assert fresh.get("n").summary == "second"
    assert len(fresh.all()) == 1


def test_all_kind_filter(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="a", kind="campaign", summary="spring ppe push")
    w.remember(name="b", kind="note", summary="random note")
    assert [f.name for f in w.all(kind="campaign")] == ["a"]


# --- isolation: the whole point -------------------------------------------------------------


def test_no_leak_across_personas(tmp_path):
    PersonaMemory(tmp_path, "bob").working.remember(
        name="secret", kind="note", summary="bob's private secret"
    )
    alice = PersonaMemory(tmp_path, "alice").working
    assert alice.get("secret") is None
    assert alice.all() == []
    assert alice.recall("secret") == []


def test_thread_scoping_isolates(tmp_path):
    pm = PersonaMemory(tmp_path, "milo")
    pm.thread("t1").remember(name="n", kind="k", summary="in thread one")
    assert pm.thread("t2").get("n") is None  # not in a sibling thread
    assert pm.working.get("n") is None  # not in persona-global working memory
    pm.working.remember(name="w", kind="k", summary="in working")
    assert pm.thread("t1").get("w") is None  # working not visible from a thread


def test_on_disk_layout_separates_working_and_threads(tmp_path):
    pm = PersonaMemory(tmp_path, "milo")
    pm.working.remember(name="w", kind="k", summary="working note")
    pm.thread("space-123").remember(name="t", kind="k", summary="thread note")
    assert (tmp_path / "milo" / WORKING / "w.md").exists()
    assert (tmp_path / "milo" / "threads" / "space-123" / "t.md").exists()


# --- path-traversal: a handle/scope/name can never escape the persona subtree ----------------


def test_unsafe_handle_refused_at_construction(tmp_path):
    for bad in ("..", ".", "a/b", "/abs", "Up-Per", "has.dot", "", "a b", "x\n"):
        with pytest.raises(ValueError):
            PersonaMemory(tmp_path, bad)
    assert not (tmp_path / "etc").exists()


def test_unsafe_scope_refused(tmp_path):
    pm = PersonaMemory(tmp_path, "milo")
    for bad in ("..", "a/b", "/abs", "has.dot", ""):
        with pytest.raises(ValueError):
            pm.thread(bad)


def test_unsafe_note_name_refused_and_writes_nothing(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    for bad in ("../escape", "a/b", "..", "Up", ""):
        with pytest.raises(ValueError, match="slug"):
            w.remember(name=bad, kind="k", summary="s")
    assert not (tmp_path / "escape").exists()
    assert PersonaMemory(tmp_path, "milo").working.all() == []


def test_remember_rejects_multiline_fields(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    with pytest.raises(ValueError, match="summary"):
        w.remember(name="n", kind="k", summary="line1\nline2")
    with pytest.raises(ValueError, match="kind"):
        w.remember(name="n", kind="", summary="s")


# --- the shared boundary holds: private writes never become shared truth ---------------------


def test_private_write_is_not_visible_in_shared_memory(tmp_path):
    shared_dir = tmp_path / "shared"
    private_root = tmp_path / "private"
    # the owner writes one real shared fact
    GovernedWriter(shared_dir).write(
        name="boss", kind="preference", summary="call me Mr Page", source=OWNER
    )
    # a persona writes a *private* note that happens to share a name
    PersonaMemory(private_root, "milo").working.remember(
        name="boss", kind="preference", summary="PRIVATE — do not share"
    )
    shared = SharedMemory(shared_dir)
    # shared memory only ever sees the owner-written fact
    assert shared.get("boss").summary == "call me Mr Page"
    assert len(shared.all()) == 1
    # and promotion into shared truth still requires the owner gate — a private note can't sneak in
    with pytest.raises(WriteRefused, match="not the owner"):
        GovernedWriter(shared_dir).write(name="snuck", kind="k", summary="s", source="self")


# --- never-crash reads ----------------------------------------------------------------------


def test_reads_never_crash_on_missing_dirs(tmp_path):
    w = PersonaMemory(tmp_path / "nonexistent", "ghost").working
    assert w.all() == []
    assert w.get("anything") is None
    assert w.recall("anything") == []


def test_malformed_file_is_skipped_not_fatal(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="good", kind="k", summary="a good note")
    (tmp_path / "milo" / WORKING / "broken.md").write_text(
        "---\nno closing fence", encoding="utf-8"
    )
    names = [f.name for f in PersonaMemory(tmp_path, "milo").working.all()]
    assert names == ["good"]


def test_remember_is_atomic_under_replace_failure(tmp_path, monkeypatch):
    scope = PersonaMemory(tmp_path, "milo").thread("dm-x")
    scope.remember(name="note", kind="note", summary="v1", body="v1")

    def boom(src, dst):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr("clonway_cockpit.obs.atomicio.os.replace", boom)
    with pytest.raises(OSError):
        scope.remember(name="note", kind="note", summary="v2", body="v2")
    monkeypatch.undo()
    fresh = PersonaMemory(tmp_path, "milo").thread("dm-x")
    fact = fresh.get("note")
    assert fact is not None and fact.body == "v1"  # never a torn/half file
    assert not list((tmp_path / "milo" / "threads" / "dm-x").glob("*.tmp"))


# --- forget ---------------------------------------------------------------------------------


def test_forget_removes_and_reports(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="temp", kind="k", summary="temporary")
    assert w.forget("temp") is True
    assert PersonaMemory(tmp_path, "milo").working.get("temp") is None
    assert w.forget("temp") is False  # already gone
    assert w.forget("never-existed") is False


def test_working_and_thread_return_private_scopes(tmp_path):
    pm = PersonaMemory(tmp_path, "milo")
    assert isinstance(pm.working, PrivateScope)
    assert isinstance(pm.thread("t"), PrivateScope)


# --- audit regressions (Final Boss Audit) ---------------------------------------------------


def test_forget_propagates_real_oserror_not_swallowed(tmp_path, monkeypatch):
    # FBA-03: a permission-denied delete must NOT be reported as "wasn't there".
    import pathlib

    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="pii", kind="note", summary="sensitive note to erase")

    def boom(self):
        raise PermissionError("denied")

    monkeypatch.setattr(pathlib.Path, "unlink", boom)
    with pytest.raises(PermissionError):
        w.forget("pii")


def test_crlf_body_roundtrips_as_lf(tmp_path):
    # FBA-04: a CRLF body must round-trip (the reader rejoins with \n, so we normalise on write).
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="multi", kind="note", summary="s", body="line1\r\nline2\r\nline3")
    got = PersonaMemory(tmp_path, "milo").working.get("multi")
    assert "\r" not in got.body
    assert got.body == "line1\nline2\nline3"


def test_overlong_name_refused_before_any_io(tmp_path):
    # FBA-08: a valid-charset but overlong name is a ValueError before mkdir — no bare OSError,
    # no orphan scope directory.
    w = PersonaMemory(tmp_path, "milo").working
    with pytest.raises(ValueError, match="slug"):
        w.remember(name="a" * 200, kind="k", summary="s")
    assert PersonaMemory(tmp_path, "milo").working.all() == []
    assert not (tmp_path / "milo" / WORKING).exists()


def test_source_is_advisory_and_roundtrips(tmp_path):
    # FBA-07: optional advisory provenance on a private note round-trips; default is None.
    w = PersonaMemory(tmp_path, "milo").working
    w.remember(name="tip", kind="note", summary="resident pays late", source="the daughter")
    assert PersonaMemory(tmp_path, "milo").working.get("tip").source == "the daughter"
    w.remember(name="plain", kind="note", summary="no source given")
    assert PersonaMemory(tmp_path, "milo").working.get("plain").source is None


def test_source_must_be_single_line(tmp_path):
    w = PersonaMemory(tmp_path, "milo").working
    with pytest.raises(ValueError, match="source"):
        w.remember(name="n", kind="k", summary="s", source="line1\nline2")


def test_thread_scope_from_normalised_chat_id(tmp_path):
    # FBA-02: the transport slice must slugify a raw Chat space id before calling thread().
    raw_chat_space_id = "spaces/AAAAbCdEf"
    scope = raw_chat_space_id.lower().replace("/", "-")  # the documented normalisation
    pm = PersonaMemory(tmp_path, "milo")
    pm.thread(scope).remember(name="turn1", kind="note", summary="owner asked for the Q2 figures")
    assert [f.name for f in pm.thread(scope).recall("Q2 figures")] == ["turn1"]
