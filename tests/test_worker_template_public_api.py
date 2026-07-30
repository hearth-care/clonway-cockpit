"""Structural guard for generated workers' framework API consumption."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_SRC = _REPO_ROOT / "worker-template" / "src"

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


def _find_forbidden(path: str, source: str) -> list[str]:
    findings = [name for name in _FORBIDDEN if name in source]
    is_doc = path.endswith(".md")
    if (path.endswith("cli/home_hooks.py") and "_host()" in source) or (
        is_doc and re.search(r"\bhost\s*=\s*_host\(\)", source)
    ):
        findings.append("Home hook reconstructs _host()")
    normalized = " ".join(source.lower().split())
    if "ambient" in normalized and "_agent_mode" in normalized:
        findings.append("ambient agent-mode Host reconstruction guidance")
    return findings


def test_generated_production_uses_only_public_framework_seams() -> None:
    findings: list[str] = []
    for path in sorted(_TEMPLATE_SRC.rglob("*.jinja")):
        relative = path.relative_to(_TEMPLATE_SRC).as_posix().removesuffix(".jinja")
        findings.extend(
            f"{relative}: {item}" for item in _find_forbidden(relative, path.read_text())
        )
    assert findings == []


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
