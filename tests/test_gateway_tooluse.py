"""Tests for the gateway tool-use port: complete_tools + adapter tool_call parsing.

The 0.5B local model can't reliably tool-call, so these prove the parse/shape/telemetry
with fake adapters + fake provider payloads (no live tool-call proof — that needs a
tool-capable model the owner can pull). The loop stays in the caller; the gateway is
one-shot per turn.
"""

from types import SimpleNamespace

from clonway_cockpit.gateway import (
    AssistantTurn,
    Gateway,
    GatewayConfig,
    ToolCall,
    Usage,
)
from clonway_cockpit.gateway.adapters import (
    LiteLLMAdapter,
    OpenAICompatibleAdapter,
    _parse_arguments,
)

_CFG = {
    "roles": {"chat": {"provider": "openai_compatible", "base_url": "http://x/v1", "model": "m"}}
}


def _openai_payload(tool_calls=None, content=None):
    msg: dict = {"content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}


def test_openai_parse_tools_extracts_calls():
    payload = _openai_payload(
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_bills", "arguments": '{"due": true}'},
            }
        ],
        content=None,
    )
    turn = OpenAICompatibleAdapter._parse_tools(payload)
    assert turn.text is None
    assert turn.tool_calls == [ToolCall(id="call_1", name="get_bills", arguments={"due": True})]
    assert turn.usage.prompt_tokens == 7


def test_openai_parse_tools_text_only_has_no_calls():
    turn = OpenAICompatibleAdapter._parse_tools(_openai_payload(content="all done"))
    assert turn.text == "all done"
    assert turn.tool_calls == []


def test_parse_arguments_is_lenient():
    assert _parse_arguments('{"a": 1}') == {"a": 1}
    assert _parse_arguments({"a": 1}) == {"a": 1}
    assert _parse_arguments("not json") == {}  # malformed -> {} (never crash a turn)
    assert _parse_arguments(None) == {}
    assert _parse_arguments("[1, 2]") == {}  # non-object json -> {}


def test_gateway_complete_tools_returns_turn_and_records_telemetry(tmp_path):
    captured: dict = {}

    class _FakeAdapter:
        def __init__(self, *a, **k):
            pass

        def complete(self, model, messages, **params):  # pragma: no cover - not used here
            raise AssertionError("complete_tools should be used, not complete")

        def complete_tools(self, model, messages, tools, **params):
            captured.update(model=model, tools=tools)
            return AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="x", name="t", arguments={"k": 1})],
                usage=Usage(prompt_tokens=4, completion_tokens=2),
            )

    gw = Gateway(
        GatewayConfig.from_dict(_CFG),
        telemetry_base=tmp_path,  # not .cockpit — no repo-root leak
        adapter_factory=lambda base_url, key, *, timeout: _FakeAdapter(),
    )
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    turn = gw.complete_tools([{"role": "user", "content": "hi"}], tools, role="chat")

    assert turn.tool_calls[0].name == "t"
    assert turn.tool_calls[0].arguments == {"k": 1}
    assert captured["model"] == "m" and captured["tools"] == tools
    assert (tmp_path / "model_usage.jsonl").exists()  # telemetry recorded the tool turn


def test_litellm_parse_tools():
    fn = SimpleNamespace(name="search", arguments='{"q": "x"}')
    tc = SimpleNamespace(id="c1", function=fn)
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
    )
    turn = LiteLLMAdapter._parse_tools(resp)
    assert turn.tool_calls == [ToolCall(id="c1", name="search", arguments={"q": "x"})]
    assert turn.text is None
    assert turn.usage.completion_tokens == 2
