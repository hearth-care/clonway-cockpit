"""serve_agent_stdio — the framework one-liner a worker's --agent-stdio callback calls."""

from __future__ import annotations

import io

from clonway_cockpit import agent


def test_serve_agent_stdio_delegates_to_serve_stdio(monkeypatch):
    seen = {}

    def fake_serve_stdio(host, *, stdin, stdout, allow_apply=False, on_apply=None, policy=None):
        seen.update(
            host=host,
            stdin=stdin,
            stdout=stdout,
            allow_apply=allow_apply,
            on_apply=on_apply,
            policy=policy,
        )

    monkeypatch.setattr(agent, "serve_stdio", fake_serve_stdio)
    sentinel_host = object()
    sin, sout = io.StringIO(), io.StringIO()
    agent.serve_agent_stdio(sentinel_host, allow_apply=True, stdin=sin, stdout=sout)
    assert seen == {
        "host": sentinel_host,
        "stdin": sin,
        "stdout": sout,
        "allow_apply": True,
        "on_apply": None,
        "policy": None,
    }


def test_serve_agent_stdio_forwards_policy_and_on_apply(monkeypatch):
    seen = {}

    def fake_serve_stdio(host, *, stdin, stdout, allow_apply=False, on_apply=None, policy=None):
        seen.update(on_apply=on_apply, policy=policy)

    monkeypatch.setattr(agent, "serve_stdio", fake_serve_stdio)
    pol, aud = (lambda p: True), (lambda p: None)
    agent.serve_agent_stdio(
        object(), stdin=io.StringIO(), stdout=io.StringIO(), policy=pol, on_apply=aud
    )
    assert seen == {"on_apply": aud, "policy": pol}
