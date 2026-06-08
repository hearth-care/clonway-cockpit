import json

from clonway_cockpit.gateway import OpenAICompatibleAdapter, image_part, text_part


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _capture_body(monkeypatch) -> dict:
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"choices": [{"message": {"content": "ok"}}], "usage": {}})

    monkeypatch.setattr("clonway_cockpit.gateway.adapters.urllib.request.urlopen", fake_urlopen)
    return captured


def test_content_part_helpers_shapes():
    assert text_part("hi") == {"type": "text", "text": "hi"}
    assert text_part("hi", cache=True) == {
        "type": "text",
        "text": "hi",
        "cache_control": {"type": "ephemeral"},
    }
    assert image_part("data:image/png;base64,AAAA") == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }


def test_multimodal_content_passes_through_to_request(monkeypatch):
    captured = _capture_body(monkeypatch)
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    content = [text_part("describe this", cache=True), image_part("data:image/png;base64,ZZ")]
    adapter.complete("gpt-4o", [{"role": "user", "content": content}])
    msg = captured["body"]["messages"][0]
    # the parts ride through untouched — incl. the cache_control passthrough marker
    assert msg["content"][0] == {
        "type": "text",
        "text": "describe this",
        "cache_control": {"type": "ephemeral"},
    }
    assert msg["content"][1]["type"] == "image_url"
    assert msg["content"][1]["image_url"]["url"] == "data:image/png;base64,ZZ"


def test_plain_string_content_still_works(monkeypatch):
    captured = _capture_body(monkeypatch)
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    comp = adapter.complete("m", [{"role": "user", "content": "plain"}])
    assert comp.text == "ok"
    assert captured["body"]["messages"][0]["content"] == "plain"
