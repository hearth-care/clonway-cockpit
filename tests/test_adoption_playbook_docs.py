from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _adoption_doc() -> str:
    return (ROOT / "docs/adopting-the-agent-channel.md").read_text(encoding="utf-8")


def test_nested_callback_guidance_reuses_active_shell_session() -> None:
    text = _adoption_doc()

    assert "def activate_pill_with_session(pill, session: shell.ShellSession)" in text
    assert "def handle_extra_key_with_session(" in text
    assert 'session.open_capability("sync-status")' in text
    assert "Host(activate_pill_with_session=..., handle_extra_key_with_session=...)" in text
    assert "guarded-apply authorization, audit sink, and agent prompt callbacks" in text

    assert "_AGENT_MODE" not in text
    assert "host = _host()" not in text
    assert "ambient module-level flag" not in text
