"""Structural guard for generated workers' framework API consumption."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_ROOT = _REPO_ROOT / "worker-template"

_FORBIDDEN = (
    "shell._home",
    "shell._activate",
    "shell._activate_need",
    "shell._doctor",
    "shell._open_capability",
    "shell._show",
    "shell._safe_emit",
    "shell._PROGRESS_TICK",
    "walk._present",
    "walk._await",
    "walk._emit",
    "walk._first_blocked_remedy",
    "walk._PROGRESS_TICK",
    "render_panels._DEFAULT_HELP_LINES",
    "obs._telemetry._RUN_BUFFERS",
)


def _template_sources() -> list[Path]:
    return sorted(_TEMPLATE_ROOT.rglob("*.jinja"))


def _find_forbidden(path: str, source: str) -> list[str]:
    findings = [name for name in _FORBIDDEN if name in source]
    is_doc = path.endswith(".md")
    callback_host_rebuild = any(
        re.search(
            r"\bdef\s+(?:activate_pill|handle_extra_key)(?:_with_session)?\s*\(",
            block,
        )
        and re.search(r"\b_host\s*\(", block)
        for block in re.findall(r"```[^\n]*\n(.*?)```", source, flags=re.DOTALL)
    )
    if (path.endswith("cli/home_hooks.py") and re.search(r"\b_host\s*\(", source)) or (
        is_doc and callback_host_rebuild
    ):
        findings.append("Home hook reconstructs _host()")
    normalized = " ".join(source.lower().split())
    if "ambient" in normalized and "_agent_mode" in normalized:
        findings.append("ambient agent-mode Host reconstruction guidance")
    return findings


def test_generated_production_uses_only_public_framework_seams() -> None:
    findings: list[str] = []
    for path in _template_sources():
        relative = path.relative_to(_TEMPLATE_ROOT).as_posix().removesuffix(".jinja")
        findings.extend(
            f"{relative}: {item}" for item in _find_forbidden(relative, path.read_text())
        )
    assert findings == []


def test_template_guard_inventory_includes_generated_readme() -> None:
    assert _REPO_ROOT / "worker-template" / "README.md.jinja" in _template_sources()


def test_framework_documentation_examples_use_public_worker_seams() -> None:
    docs = _REPO_ROOT / "docs"
    findings: list[str] = []
    for path in sorted(docs.rglob("*.md")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative.startswith(("docs/superpowers/", "docs/findings/")):
            continue
        findings.extend(
            f"{relative}: {item}" for item in _find_forbidden(relative, path.read_text())
        )
    assert findings == []


def test_private_seam_guard_covers_every_bound_spelling_and_public_equivalents() -> None:
    for forbidden in _FORBIDDEN:
        assert forbidden in _find_forbidden("package/cli/cockpit.py", f"use {forbidden}")

    accepted = """
shell.run_home(host, screen, read_key)
shell.activate_item(host, item, state, screen, read_key)
shell.activate_need(host, item, screen, read_key)
shell.run_doctor(host, screen, read_key)
shell.open_capability(host, "key", screen, read_key)
shell.show_and_wait(screen, panel, read_key)
shell.emit_model(host, model)
shell.PROGRESS_TICK
walk.present(ctx, panel)
walk.await_key(ctx)
walk.emit(ctx, model)
walk.first_blocked_remedy(preconditions)
walk.PROGRESS_TICK
render_panels.DEFAULT_HELP_LINES
obs.event_buffer("worker")
"""
    assert _find_forbidden("package/cli/cockpit.py", accepted) == []


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        (
            "package/cli/home_hooks.py",
            "def activate_pill(pill, screen, read_key):\n    host = _host()\n",
            "Home hook reconstructs _host()",
        ),
        (
            "docs/adopting-the-agent-channel.md",
            "read an\nambient module-level `_AGENT_MODE` flag before rebuilding `_host()`",
            "ambient agent-mode Host reconstruction guidance",
        ),
    ],
)
def test_private_seam_guard_covers_hand_written_rules(path, source, expected) -> None:
    assert expected in _find_forbidden(path, source)


@pytest.mark.parametrize(
    "rebuild",
    [
        "h = _host()",
        "return _host()",
        "self._host()",
        "_host(agent_mode=True)",
    ],
)
@pytest.mark.parametrize("callback", ["activate_pill", "handle_extra_key"])
def test_private_seam_guard_rejects_host_rebuild_spellings_in_doc_callbacks(
    rebuild, callback
) -> None:
    source = f"```python\ndef {callback}(*args):\n    {rebuild}\n```"
    assert "Home hook reconstructs _host()" in _find_forbidden(
        "docs/adopting-the-agent-channel.md", source
    )


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "package/cli/home_hooks.py",
            "def handle_extra_key_with_session(state, selection, key, session):\n"
            "    session.open_capability('child')\n",
        ),
        (
            "docs/adopting-the-agent-channel.md",
            "Reuse the exact active `ShellSession`; never rebuild the Host in a callback.",
        ),
    ],
)
def test_private_seam_guard_accepts_session_guidance(path, source) -> None:
    assert _find_forbidden(path, source) == []
