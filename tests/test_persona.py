"""Tests for clonway_cockpit.persona — the thin persona identity layer."""

from pathlib import Path

import pytest

from clonway_cockpit.persona import (
    Persona,
    PersonaError,
    PersonaRegistry,
    load_persona,
)


def test_from_dict_round_trips_all_fields():
    p = Persona.from_dict(
        {
            "handle": "milo",
            "name": "Milo Garth",
            "domain": "the books",
            "email": "milo@x.co",
            "avatar_ref": "🧮",
            "voice": "warm, precise",
        }
    )
    assert p == Persona("milo", "Milo Garth", "the books", "milo@x.co", "🧮", "warm, precise")


def test_from_dict_defaults_optional_fields():
    p = Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "the books"})
    assert (p.email, p.avatar_ref, p.voice) == ("", "", "")


@pytest.mark.parametrize("missing", ["handle", "name", "domain"])
def test_from_dict_missing_required_raises(missing):
    data = {"handle": "milo", "name": "Milo", "domain": "the books"}
    del data[missing]
    with pytest.raises(PersonaError, match="required field"):
        Persona.from_dict(data)


@pytest.mark.parametrize("bad", ["Milo", "mi lo", "-milo", "milo!", ""])
def test_from_dict_bad_handle_raises(bad):
    with pytest.raises(PersonaError):
        Persona.from_dict({"handle": bad, "name": "Milo", "domain": "the books"})


def test_from_dict_non_dict_raises():
    with pytest.raises(PersonaError):
        Persona.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_load_persona_from_toml(tmp_path: Path):
    f = tmp_path / "milo.toml"
    f.write_text('handle = "milo"\nname = "Milo"\ndomain = "the books"\n')
    assert load_persona(f).handle == "milo"


def test_load_persona_invalid_toml_raises(tmp_path: Path):
    f = tmp_path / "bad.toml"
    f.write_text("handle = ")  # malformed TOML
    with pytest.raises(PersonaError, match="invalid TOML"):
        load_persona(f)


def test_registry_dedup_get_all():
    milo = Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "books"})
    quill = Persona.from_dict({"handle": "quill", "name": "Quill", "domain": "desk"})
    reg = PersonaRegistry.from_personas([quill, milo])
    assert reg.get("milo") is milo
    assert reg.get("nobody") is None
    assert [p.handle for p in reg.all()] == ["milo", "quill"]  # sorted by handle


def test_registry_duplicate_handle_raises():
    p = Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "books"})
    with pytest.raises(PersonaError, match="duplicate"):
        PersonaRegistry.from_personas([p, p])


def test_registry_load_dir_reads_shipped_examples():
    reg = PersonaRegistry.load_dir(Path("examples/personas"))
    handles = [p.handle for p in reg.all()]
    assert "milo" in handles and "quill" in handles
    assert reg.get("milo").name == "Milo Garth"  # type: ignore[union-attr]


def test_registry_load_dir_missing_raises(tmp_path: Path):
    with pytest.raises(PersonaError, match="not found"):
        PersonaRegistry.load_dir(tmp_path / "nope")
