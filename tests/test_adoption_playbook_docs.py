from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _adoption_doc() -> str:
    return (ROOT / "docs/adopting-the-agent-channel.md").read_text(encoding="utf-8")


def test_host_rebuild_pattern_latches_agent_mode_once() -> None:
    text = _adoption_doc()

    assert "_AGENT_MODE = agent_mode" not in text
    assert "def _host() -> shell.Host:" in text
    assert "agent_mode=_AGENT_MODE" in text
    assert "_AGENT_MODE = True" in text
    assert "serve_agent_stdio(_host()," in text
    assert "_host(agent_mode=_AGENT_MODE)" not in text
