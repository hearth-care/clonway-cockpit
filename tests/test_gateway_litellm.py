import builtins
from types import SimpleNamespace

import pytest

import clonway_cockpit.gateway.adapters as adapters_mod
from clonway_cockpit.gateway import (
    Gateway,
    GatewayConfig,
    GatewayError,
    LiteLLMAdapter,
    OpenAICompatibleAdapter,
)


def _fake_response(text="hi", prompt=7, completion=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def _patch_litellm(monkeypatch, *, capture=None, exc=None, response=None):
    def completion(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        if exc is not None:
            raise exc
        return response if response is not None else _fake_response()

    monkeypatch.setattr(adapters_mod, "_litellm", lambda: SimpleNamespace(completion=completion))


def test_litellm_adapter_parses_and_threads_args(monkeypatch):
    capture: dict = {}
    _patch_litellm(monkeypatch, capture=capture)
    adapter = LiteLLMAdapter("sk-x", timeout=12.0, api_base="http://localhost:11434")
    comp = adapter.complete(
        "anthropic/claude-haiku-4-5", [{"role": "user", "content": "hi"}], temperature=0.0
    )
    assert comp.text == "hi"
    assert comp.usage.prompt_tokens == 7
    assert comp.usage.completion_tokens == 3
    assert capture["model"] == "anthropic/claude-haiku-4-5"
    assert capture["api_key"] == "sk-x"
    assert capture["api_base"] == "http://localhost:11434"
    assert capture["temperature"] == 0.0
    assert capture["timeout"] == 12.0


def test_litellm_adapter_omits_key_and_apibase_when_absent(monkeypatch):
    capture: dict = {}
    _patch_litellm(monkeypatch, capture=capture)
    LiteLLMAdapter(None).complete("gpt-4o-mini", [{"role": "user", "content": "hi"}])
    assert "api_key" not in capture
    assert "api_base" not in capture


def test_litellm_adapter_wraps_provider_errors(monkeypatch):
    _patch_litellm(monkeypatch, exc=RuntimeError("rate limited"))
    with pytest.raises(GatewayError, match="litellm completion failed"):
        LiteLLMAdapter("k").complete("m", [{"role": "user", "content": "hi"}])


def test_litellm_adapter_malformed_response(monkeypatch):
    _patch_litellm(monkeypatch, response=SimpleNamespace(choices=[]))
    with pytest.raises(GatewayError, match="malformed litellm"):
        LiteLLMAdapter("k").complete("m", [{"role": "user", "content": "hi"}])


def test_litellm_missing_dependency_raises_clear_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "litellm":
            raise ImportError("no litellm")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(GatewayError, match=r"clonway-cockpit\[litellm\]"):
        adapters_mod._litellm()


def test_config_accepts_litellm_without_base_url():
    cfg = GatewayConfig.from_dict(
        {"roles": {"chat": {"provider": "litellm", "model": "anthropic/claude-haiku-4-5"}}}
    )
    role = cfg.resolve("chat")
    assert role.provider == "litellm"
    assert role.base_url == ""


def test_config_openai_compatible_still_requires_base_url():
    with pytest.raises(GatewayError, match="base_url"):
        GatewayConfig.from_dict(
            {"roles": {"chat": {"provider": "openai_compatible", "model": "m"}}}
        )


def test_gateway_dispatches_by_provider():
    litellm_cfg = GatewayConfig.from_dict(
        {"roles": {"chat": {"provider": "litellm", "model": "gpt-4o-mini"}}}
    )
    assert isinstance(
        Gateway(litellm_cfg)._build_adapter(litellm_cfg.resolve("chat"), "k"), LiteLLMAdapter
    )
    oai_cfg = GatewayConfig.from_dict(
        {"roles": {"chat": {"provider": "openai_compatible", "base_url": "u", "model": "m"}}}
    )
    assert isinstance(
        Gateway(oai_cfg)._build_adapter(oai_cfg.resolve("chat"), "k"), OpenAICompatibleAdapter
    )
