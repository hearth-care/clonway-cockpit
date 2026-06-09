"""Tests for clonway_cockpit.receptionist — the front door that points, never acts."""

from clonway_cockpit.persona import Persona, PersonaRegistry
from clonway_cockpit.receptionist import Route, route


def _registry(*specs) -> PersonaRegistry:
    return PersonaRegistry.from_personas([Persona.from_dict(s) for s in specs])


def test_single_domain_match_points_to_the_persona():
    reg = _registry(
        {"handle": "milo", "name": "Milo", "domain": "invoicing and cash"},
        {"handle": "quill", "name": "Quill", "domain": "the diary and front desk"},
    )
    r = route("how much cash do we have?", reg)
    assert r.kind == "direct"
    assert r.persona is not None and r.persona.handle == "milo"
    assert "Milo" in r.message and "@milo" in r.message


def test_ambiguous_match_names_the_candidates_and_asks():
    reg = _registry(
        {"handle": "milo", "name": "Milo", "domain": "invoicing and cash"},
        {"handle": "banker", "name": "Banker", "domain": "banking and cash reconciliation"},
    )
    r = route("how is our cash?", reg)
    assert r.kind == "ambiguous"
    assert r.persona is None
    assert {p.handle for p in r.candidates} == {"milo", "banker"}
    assert "@milo" in r.message and "@banker" in r.message


def test_no_match_offers_to_list_the_team():
    reg = _registry({"handle": "milo", "name": "Milo", "domain": "invoicing and cash"})
    r = route("what's the weather like?", reg)
    assert r.kind == "none"
    assert r.persona is None and r.candidates == []
    assert "list the team" in r.message


def test_at_mention_overrides_domain_inference():
    reg = _registry(
        {"handle": "milo", "name": "Milo", "domain": "invoicing and cash"},
        {"handle": "quill", "name": "Quill", "domain": "the diary and front desk"},
    )
    # message is about cash (milo's domain) but explicitly addresses @quill
    r = route("@quill can you check the cash thing?", reg)
    assert r.kind == "direct"
    assert r.persona is not None and r.persona.handle == "quill"


def test_domain_matcher_is_injectable():
    reg = _registry({"handle": "milo", "name": "Milo", "domain": "anything"})
    # an injected matcher that always matches -> direct route regardless of keywords
    r = route("xyz", reg, domain_matches=lambda text, persona: True)
    assert r.kind == "direct" and r.persona.handle == "milo"  # type: ignore[union-attr]


def test_route_kind_property():
    p = Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "books"})
    assert Route(persona=p).kind == "direct"
    assert Route(persona=None, candidates=[p, p]).kind == "ambiguous"
    assert Route(persona=None).kind == "none"
