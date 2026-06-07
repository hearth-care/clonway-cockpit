"""serve_agent_stdio — the framework one-liner a worker's --agent-stdio callback calls."""

from __future__ import annotations

import io

from clonway_cockpit import agent


def test_serve_agent_stdio_delegates_to_serve_stdio(monkeypatch):
    seen = {}

    def fake_serve_stdio(host, *, stdin, stdout, allow_apply=False, on_apply=None):
        seen.update(host=host, stdin=stdin, stdout=stdout, allow_apply=allow_apply)

    monkeypatch.setattr(agent, "serve_stdio", fake_serve_stdio)
    sentinel_host = object()
    sin, sout = io.StringIO(), io.StringIO()
    agent.serve_agent_stdio(sentinel_host, allow_apply=True, stdin=sin, stdout=sout)
    assert seen == {"host": sentinel_host, "stdin": sin, "stdout": sout, "allow_apply": True}
