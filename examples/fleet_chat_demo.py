"""Runnable demo: a FLEET of colleagues converse through the model-gateway wire.

Unlike ``group_space_demo.py`` (which uses the ``echo_responder`` stub), this drives the
reference :func:`clonway_cockpit.colleague.gateway_responder` — each persona's OWN soul is
composed into a system prompt and sent through a ``Completer``. Run it headless with no network
using a tiny fake completer:

    uv run python examples/fleet_chat_demo.py

To drive a REAL (or local) model instead, swap the fake for a
:class:`clonway_cockpit.gateway.gateway.Gateway` — see the commented block at the bottom. One
line changes; the wiring is identical.
"""

from pathlib import Path

from clonway_cockpit.colleague import gateway_responder, load_colleagues
from clonway_cockpit.gateway.types import Message
from clonway_cockpit.group_chat import FakeChatTransport, GroupSpace


class _FakeCompleter:
    """Stands in for a Gateway with no network. It reads the persona's name out of the system
    prompt it was handed and replies in that voice — proof that each colleague's DISTINCT soul
    reached the 'model', which is the whole point of the wire."""

    def complete(self, messages: list[Message], *, role: str) -> str:
        system = str(messages[0]["content"])
        name = system.split(" — ", 1)[0].removeprefix("You are ").strip()
        user = str(messages[-1]["content"])
        return f"[{role}] {name}: I'll take {user!r}."


def main() -> None:
    here = Path(__file__).parent
    fleet = load_colleagues(here / "personas", here / "souls")
    space = GroupSpace(
        space_id="ops",
        registry=fleet.registry,
        transport=FakeChatTransport(),
        responder=gateway_responder(fleet, _FakeCompleter(), role="chat"),
    )
    for question in [
        "how much cash do we have this month?",  # -> milo (the books)
        "@quill what's on the diary today?",  # -> quill (addressed)
        "morning all",  # -> everyone quiet (quiet-by-default)
    ]:
        replies = space.owner_says(question)
        print(f"owner: {question}")
        for r in replies:
            print(f"  @{r.handle}: {r.text}")
        if not replies:
            print("  (everyone stayed quiet)")

    # --- to drive a real / local model, swap the fake for a Gateway (one line): ---
    # from clonway_cockpit.gateway.config import GatewayConfig
    # from clonway_cockpit.gateway.gateway import Gateway
    # cfg = GatewayConfig.from_dict({"roles": {"chat": {
    #     "provider": "openai_compatible",
    #     "base_url": "http://localhost:11434/v1",   # a local Ollama, no API key, no PII leaving the box
    #     "model": "qwen2.5:0.5b",
    # }}})
    # responder = gateway_responder(fleet, Gateway(cfg), role="chat")
    # ...then pass responder= to GroupSpace exactly as above.


if __name__ == "__main__":
    main()
