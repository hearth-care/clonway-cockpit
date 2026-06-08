"""Runnable demo of an in-memory group space — two personas self-select, no LLM, no live
transport. Run from the repo root:  uv run python examples/group_space_demo.py

The real surface is a Google Chat add-on (operator deploy); here a FakeChatTransport +
the echo_responder stand in so the mechanics run end-to-end headlessly.
"""

from pathlib import Path

from clonway_cockpit.group_chat import FakeChatTransport, GroupSpace, echo_responder
from clonway_cockpit.persona import PersonaRegistry


def main() -> None:
    space = GroupSpace(
        space_id="ops",
        registry=PersonaRegistry.load_dir(Path(__file__).parent / "personas"),
        transport=FakeChatTransport(),
        responder=echo_responder,
    )
    for question in [
        "how much cash do we have this month?",  # -> milo (the books)
        "@quill what's on the diary today?",  # -> quill (addressed)
        "morning all",  # -> everyone quiet (quiet-by-default)
    ]:
        replies = space.owner_says(question)
        who = ", ".join(f"@{r.handle}" for r in replies) or "(everyone stayed quiet)"
        print(f"owner: {question}\n  -> {who}")


if __name__ == "__main__":
    main()
