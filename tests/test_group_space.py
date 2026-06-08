"""End-to-end test of the in-memory group space: registry + orchestrator + transport
wired through GroupSpace. Proves the mechanics headlessly (the live Google Chat add-on
transport is an operator deploy, PARKED)."""

from clonway_cockpit.group_chat import (
    ChatMessage,
    FakeChatTransport,
    GroupSpace,
    echo_responder,
)
from clonway_cockpit.persona import Persona, PersonaRegistry


def _space(transport: FakeChatTransport | None = None) -> GroupSpace:
    registry = PersonaRegistry.from_personas(
        [
            Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "the books and cash"}),
            Persona.from_dict(
                {"handle": "quill", "name": "Quill", "domain": "the diary and front desk"}
            ),
        ]
    )
    return GroupSpace("ops", registry, transport or FakeChatTransport(), echo_responder)


def test_owner_general_question_routes_to_the_right_persona():
    replies = _space().owner_says("how much cash do we have?")
    assert [r.handle for r in replies] == ["milo"]  # matches 'cash'; quill quiet


def test_owner_addresses_persona_by_handle():
    replies = _space().owner_says("@quill anything on the diary?")
    assert [r.handle for r in replies] == ["quill"]


def test_greeting_keeps_everyone_quiet():
    assert _space().owner_says("morning all") == []


def test_replies_reach_the_transport_under_the_space_id():
    transport = FakeChatTransport()
    _space(transport).owner_says("how much cash do we have?")
    assert len(transport.posted) == 1
    assert transport.posted[0][0] == "ops"


def test_agent_says_is_chatter_not_a_command():
    # an agent posting a write-ish request triggers at most conversational replies, never an
    # action — is_command stays False for non-owner authors (proven in test_group_chat).
    replies = _space().agent_says("quill", "milo should pay invoice 8821")
    # quill's message isn't @-addressed to milo and isn't from the owner -> milo stays quiet
    assert replies == []


def test_echo_responder_speaks_in_persona_voice():
    milo = Persona.from_dict({"handle": "milo", "name": "Milo", "domain": "the books"})
    text = echo_responder(milo, ChatMessage.from_text("hi", author="owner", is_owner=True))
    assert "Milo" in text and "the books" in text
