import pytest

from clonway_cockpit.gateway.config import GatewayConfig
from clonway_cockpit.gateway.gateway import Gateway
from clonway_cockpit.gateway.telemetry import load_events
from clonway_cockpit.gateway.types import Completion, GatewayError, Usage

CFG = {
    "roles": {
        "chat": {
            "provider": "openai_compatible",
            "base_url": "https://api.x/v1",
            "model": "gpt-4o-mini",
            "api_key_env": "TEST_GW_KEY",
            "params": {"temperature": 0.0},
        }
    },
    "pricing": {"gpt-4o-mini": {"prompt": 0.001, "completion": 0.002}},
}


class _FakeAdapter:
    """Records construction + call args, then returns ``_reply()``.

    Subclasses override ``_reply`` to vary the model output (the base ``complete``
    still records params, so structured tests can assert on what was sent). A
    subclass that needs to *fail* overrides ``complete`` directly.
    """

    last: dict = {}

    def __init__(self, base_url, api_key, *, timeout=30.0):
        _FakeAdapter.last = {"base_url": base_url, "api_key": api_key, "timeout": timeout}

    def complete(self, model, messages, **params):
        _FakeAdapter.last["model"] = model
        _FakeAdapter.last["messages"] = messages
        _FakeAdapter.last["params"] = params
        return self._reply()

    def _reply(self):
        return Completion(text="ok", usage=Usage(prompt_tokens=4, completion_tokens=6))


def _gw(tmp_path, factory=_FakeAdapter):
    return Gateway(GatewayConfig.from_dict(CFG), telemetry_base=tmp_path, adapter_factory=factory)


def test_complete_returns_text_and_records_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")
    gw = _gw(tmp_path)
    out = gw.complete([{"role": "user", "content": "hi"}], role="chat")
    assert out == "ok"
    # adapter built from the role config, key read from env, params threaded
    assert _FakeAdapter.last["base_url"] == "https://api.x/v1"
    assert _FakeAdapter.last["api_key"] == "sk-live"
    assert _FakeAdapter.last["params"]["temperature"] == 0.0
    # telemetry recorded with cost = 4/1000*0.001 + 6/1000*0.002 = 0.000016
    events = load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["ok"] is True
    assert events[0]["prompt_tokens"] == 4
    assert events[0]["est_cost"] == pytest.approx(0.000016)


def test_unknown_role_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")
    with pytest.raises(GatewayError, match="unknown role"):
        _gw(tmp_path).complete([{"role": "user", "content": "hi"}], role="ghost")


def test_missing_env_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_GW_KEY", raising=False)
    with pytest.raises(GatewayError, match="TEST_GW_KEY"):
        _gw(tmp_path).complete([{"role": "user", "content": "hi"}], role="chat")


def test_adapter_failure_raises_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Boom(_FakeAdapter):
        def complete(self, model, messages, **params):
            raise GatewayError("HTTP 500 from upstream")

    with pytest.raises(GatewayError, match="500"):
        _gw(tmp_path, factory=_Boom).complete([{"role": "user", "content": "hi"}], role="chat")
    events = load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["ok"] is False
    assert events[0]["err"] == "GatewayError"
    assert events[0]["prompt_tokens"] == 0


def test_complete_structured_parses_and_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Json(_FakeAdapter):
        def _reply(self):
            # server wraps JSON in prose + fences — _extract_json must cope
            txt = 'Sure!\n```json\n{"name": "Ada", "age": 36}\n```'
            return Completion(text=txt, usage=Usage(prompt_tokens=2, completion_tokens=2))

    gw = _gw(tmp_path, factory=_Json)
    schema = {"type": "object", "required": ["name", "age"]}
    out = gw.complete_structured([{"role": "user", "content": "who"}], schema, role="chat")
    assert out == {"name": "Ada", "age": 36}
    # response_format requested
    assert _FakeAdapter.last["params"].get("response_format") == {"type": "json_object"}


def test_complete_structured_missing_required_key_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Json(_FakeAdapter):
        def _reply(self):
            return Completion(
                text='{"name": "Ada"}', usage=Usage(prompt_tokens=1, completion_tokens=1)
            )

    schema = {"type": "object", "required": ["name", "age"]}
    with pytest.raises(GatewayError, match="age"):
        _gw(tmp_path, factory=_Json).complete_structured(
            [{"role": "user", "content": "who"}], schema, role="chat"
        )


def test_complete_structured_non_json_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Prose(_FakeAdapter):
        def _reply(self):
            return Completion(
                text="no json here", usage=Usage(prompt_tokens=1, completion_tokens=1)
            )

    with pytest.raises(GatewayError, match="JSON"):
        _gw(tmp_path, factory=_Prose).complete_structured(
            [{"role": "user", "content": "who"}], {"required": []}, role="chat"
        )
