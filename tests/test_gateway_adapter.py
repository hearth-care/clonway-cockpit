import io
import json
import urllib.error

import pytest

from clonway_cockpit.gateway.adapters import OpenAICompatibleAdapter
from clonway_cockpit.gateway.types import GatewayError


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _patch_urlopen(monkeypatch, *, payload=None, exc=None, capture=None):
    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture["req"] = req
            capture["timeout"] = timeout
        if exc is not None:
            raise exc
        return _FakeResp(payload)

    monkeypatch.setattr("clonway_cockpit.gateway.adapters.urllib.request.urlopen", fake_urlopen)


def test_complete_parses_text_and_usage(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "hello there"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    capture: dict = {}
    _patch_urlopen(monkeypatch, payload=payload, capture=capture)
    adapter = OpenAICompatibleAdapter("https://api.x/v1/", "sk-abc", timeout=12.0)
    comp = adapter.complete("gpt-4o-mini", [{"role": "user", "content": "hi"}], temperature=0.1)
    assert comp.text == "hello there"
    assert comp.usage.prompt_tokens == 7
    assert comp.usage.completion_tokens == 3
    # request shape: trailing slash trimmed, auth header, body carries model + params
    req = capture["req"]
    assert req.full_url == "https://api.x/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-abc"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.1
    assert capture["timeout"] == 12.0


def test_no_auth_header_when_keyless(monkeypatch):
    capture: dict = {}
    _patch_urlopen(
        monkeypatch,
        payload={"choices": [{"message": {"content": "x"}}], "usage": {}},
        capture=capture,
    )
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", None)
    comp = adapter.complete("llama3.1", [{"role": "user", "content": "hi"}])
    assert comp.usage.prompt_tokens == 0  # missing usage tolerated → 0
    assert "Authorization" not in capture["req"].headers


def test_http_error_becomes_gateway_error(monkeypatch):
    err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b"slow down"))
    _patch_urlopen(monkeypatch, exc=err)
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="429"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])


def test_transport_error_becomes_gateway_error(monkeypatch):
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("no route"))
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="transport"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])


def test_malformed_payload_becomes_gateway_error(monkeypatch):
    _patch_urlopen(monkeypatch, payload={"unexpected": True})
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="malformed"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])


def test_null_content_becomes_gateway_error(monkeypatch):
    # a server returning content: null must not yield the literal string "None"
    _patch_urlopen(
        monkeypatch,
        payload={"choices": [{"message": {"content": None}}], "usage": {}},
    )
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="not a string"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])
