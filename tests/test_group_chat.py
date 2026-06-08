"""Tests for clonway_cockpit.group_chat — self-selection, owner-only commands, turn cap."""

from clonway_cockpit.group_chat import (
    ChatMessage,
    FakeChatTransport,
    GroupChatOrchestrator,
    extract_mentions,
    is_command,
    should_respond,
)
from clonway_cockpit.persona import Persona, PersonaRegistry


def _milo() -> Persona:
    return Persona.from_dict(
        {"handle": "milo", "name": "Milo", "domain": "the books — invoicing, payroll, cash"}
    )


def _quill() -> Persona:
    return Persona.from_dict(
        {"handle": "quill", "name": "Quill", "domain": "the front desk and the diary"}
    )


def _registry() -> PersonaRegistry:
    return PersonaRegistry.from_personas([_milo(), _quill()])


# --- gates -----------------------------------------------------------------


def test_extract_mentions_dedupes_and_lowercases():
    assert extract_mentions("@milo and @quill, also @milo again") == ("milo", "quill")
    assert extract_mentions("no mentions here") == ()


def test_should_respond_rules():
    milo = _milo()
    addressed = ChatMessage.from_text("@milo hi", author="owner", is_owner=True)
    assert should_respond(addressed, milo) is True  # @-addressed
    general_on = ChatMessage.from_text("what is our cash position", author="owner", is_owner=True)
    assert should_respond(general_on, milo) is True  # owner general + own domain ("cash")
    general_off = ChatMessage.from_text("hello everyone", author="owner", is_owner=True)
    assert should_respond(general_off, milo) is False  # quiet by default
    agent_chatter = ChatMessage.from_text("milo is great", author="quill", is_owner=False)
    assert should_respond(agent_chatter, milo) is False  # not addressed, not owner
    own = ChatMessage.from_text("a note", author="milo", is_owner=False)
    assert should_respond(own, milo) is False  # never reply to your own message


def test_only_owner_messages_are_commands():
    agent = ChatMessage.from_text("@milo please pay invoice 8821", author="quill", is_owner=False)
    owner = ChatMessage.from_text("pay invoice 8821", author="owner", is_owner=True)
    assert is_command(agent) is False  # an agent 'asking' for a write is data, not a command
    assert is_command(owner) is True


def test_fake_transport_post_and_iter():
    seeded = {"s": [ChatMessage.from_text("hi", author="owner", is_owner=True)]}
    t = FakeChatTransport(seeded=seeded)
    t.post("s", "reply")
    assert t.posted == [("s", "reply")]
    assert [m.text for m in t.iter_messages("s")] == ["hi"]


# --- orchestrator ----------------------------------------------------------


def test_owner_general_question_only_matching_persona_responds():
    orch = GroupChatOrchestrator(
        FakeChatTransport(), _registry(), responder=lambda p, m: f"{p.handle}: on it"
    )
    msg = ChatMessage.from_text(
        "how much cash do we have?", author="owner", is_owner=True, space="s"
    )
    posted = orch.run_round("s", [msg])
    assert [r.handle for r in posted] == ["milo"]  # milo matches 'cash'; quill stays quiet


def test_owner_addressing_persona_responds_even_off_domain():
    orch = GroupChatOrchestrator(
        FakeChatTransport(), _registry(), responder=lambda p, m: f"{p.handle}: sure"
    )
    msg = ChatMessage.from_text("@quill can you check the room?", author="owner", is_owner=True)
    posted = orch.run_round("s", [msg])
    assert [r.handle for r in posted] == ["quill"]


def test_bot_to_bot_exchange_hits_turn_cap_and_terminates():
    def ping(persona, message):  # always pings the other persona → would loop forever
        other = "quill" if persona.handle == "milo" else "milo"
        return f"@{other} interesting point"

    orch = GroupChatOrchestrator(
        FakeChatTransport(), _registry(), responder=ping, max_persona_turns=4
    )
    seed = ChatMessage.from_text("@milo kick it off", author="owner", is_owner=True, space="s")
    posted = orch.run_round("s", [seed])
    assert len(posted) == 4  # capped at max_persona_turns — the loop stopped, didn't run away


def test_owner_message_resets_the_turn_guard():
    def ping(persona, message):
        other = "quill" if persona.handle == "milo" else "milo"
        return f"@{other} hmm"

    orch = GroupChatOrchestrator(
        FakeChatTransport(), _registry(), responder=ping, max_persona_turns=2
    )
    # Two owner messages each kick a (capped) exchange; the second owner msg resets the guard.
    seeds = [
        ChatMessage.from_text("@milo one", author="owner", is_owner=True, space="s"),
        ChatMessage.from_text("@quill two", author="owner", is_owner=True, space="s"),
    ]
    posted = orch.run_round("s", seeds)
    # each owner message permits up to max_persona_turns persona turns
    assert 0 < len(posted) <= 4
