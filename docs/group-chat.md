# Group chat — distributed self-selection

The owner and every persona share one space. Instead of a central router deciding who
answers (fragile — it must be flawless), each persona independently answers the narrow,
reliable question **"is this mine?"** and volunteers or stays quiet. A wrong self-selection
just means a persona is silent (or the owner re-asks) — never a mis-route that *acts*.

`clonway_cockpit.group_chat` owns the **mechanics**, headless. The live Google Chat add-on
transport is an operator deploy; a `ChatTransport` Protocol + `FakeChatTransport` run the
whole thing in tests. How a persona composes a reply is an injected `responder` (a gateway
loop in production; a stub in tests).

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

The default `domain_matches` is a cheap keyword overlap against the persona's `domain` — a
placeholder for a real cheap-model self-selection gate, which you inject the same way.
