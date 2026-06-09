# Group chat — distributed self-selection

The owner and every persona share one space. Instead of a central router deciding who
answers (fragile — it must be flawless), each persona independently answers the narrow,
reliable question **"is this mine?"** and volunteers or stays quiet. A wrong self-selection
just means a persona is silent (or the owner re-asks) — never a mis-route that *acts*.

`clonway_cockpit.group_chat` owns the **mechanics**, headless. The live Google Chat add-on
transport is an operator deploy; a `ChatTransport` Protocol + `FakeChatTransport` run the
whole thing in tests. How a persona composes a reply is an injected `responder` — in
production the reference one is **`clonway_cockpit.colleague.gateway_responder`**, which wires
persona → soul → model gateway → reply for a whole fleet (see [personas.md](personas.md));
`echo_responder` is the no-model stub for demos/tests.

## The three safety traps (the shared room is shared blast radius)

- **quiet-by-default** — `should_respond(message, persona)` is `True` only when the persona
  is `@`-addressed, or the *owner's* general message is clearly its domain. Agent chatter it
  isn't addressed in is ignored.
- **owner-only commands** — `is_command(message)` is `True` only for the owner's messages. A
  persona may chat back to another persona, but an agent can never *instruct* it to act:
  agent messages are data, not commands. (The owner is the air-gap.)
- **turn cap** — after `max_persona_turns` consecutive persona turns without an owner
  message, persona→persona replies stop, defeating bot↔bot loops. The owner re-engaging
  resets the guard.

## Using it

```python
from clonway_cockpit.group_chat import ChatMessage, GroupChatOrchestrator, FakeChatTransport
from clonway_cockpit.persona import PersonaRegistry

orch = GroupChatOrchestrator(
    transport=FakeChatTransport(),
    registry=PersonaRegistry.load_dir(Path("config/personas")),
    responder=my_persona_reply_fn,     # (Persona, ChatMessage) -> str | None
    max_persona_turns=6,
    domain_matches=None,               # default keyword gate; inject a cheap-model "is this mine?"
)
owner_msg = ChatMessage.from_text("how much cash do we have?", author="owner", is_owner=True, space="s")
orch.run_round("s", [owner_msg])       # only the persona whose domain matches replies
```

The default `domain_matches` is `domain_match` — a cheap keyword overlap against the persona's
`domain`, a placeholder for a real cheap-model self-selection gate you inject the same way. It
extracts the domain's 2-letter-or-longer words and matches them on **word boundaries**, so a
short-named specialist (VAT, tax, HR, AR) is reachable by self-selection while a generic word
isn't falsely triggered (the domain word `ar` matches "ar", not "are"). The **receptionist uses
the same `domain_match`** (imported from here), so the front desk and the room never disagree —
inject one smart matcher into both.
