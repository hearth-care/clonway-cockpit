import builtins

import pytest

from clonway_cockpit.gateway.config import GatewayConfig
from clonway_cockpit.gateway.gateway import Gateway
from clonway_cockpit.gateway.types import GatewayError


def _config(data: dict | None = None) -> GatewayConfig:
    return GatewayConfig.from_dict(
        data
        or {
            "roles": {
                "chat": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.example/v1",
                    "model": "gpt-4o-mini",
                    "api_key_env": "GW_CHAT_KEY",
                },
                "local": {
                    "provider": "openai_compatible",
                    "base_url": "http://localhost:11434/v1",
                    "model": "llama3.1",
                },
            },
            "pricing": {"gpt-4o-mini": {"prompt": 0.001, "completion": 0.002}},
        }
    )


def test_validate_reports_missing_env_without_building_adapter(monkeypatch):
    monkeypatch.delenv("GW_CHAT_KEY", raising=False)
    called = False

    def factory(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("validate must not build adapters")

    problems = Gateway(_config(), adapter_factory=factory).validate(roles=("chat",))

    assert called is False
    assert problems == ["role 'chat': env var 'GW_CHAT_KEY' is unset"]


def test_validate_can_skip_env_check(monkeypatch):
    monkeypatch.delenv("GW_CHAT_KEY", raising=False)

    assert Gateway(_config()).validate(roles=("chat",), check_env=False) == []


def test_validate_reports_unknown_requested_role(monkeypatch):
    monkeypatch.setenv("GW_CHAT_KEY", "sk-test")

    assert Gateway(_config()).validate(roles=("chat", "ghost")) == ["unknown role: 'ghost'"]


def test_validate_reports_unmatched_pricing_model(monkeypatch):
    monkeypatch.setenv("GW_CHAT_KEY", "sk-test")
    cfg = _config(
        {
            "roles": {
                "chat": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.example/v1",
                    "model": "gpt-4o-mini",
                }
            },
            "pricing": {
                "gpt-4o-mini": {"prompt": 0.001},
                "gpt-4o-mini-typo": {"prompt": 0.001},
            },
        }
    )

    assert Gateway(cfg).validate() == [
        "pricing model 'gpt-4o-mini-typo' does not match any configured role model"
    ]


def test_validate_reports_missing_litellm_extra(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ImportError("no litellm")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    cfg = _config({"roles": {"chat": {"provider": "litellm", "model": "gpt-4o-mini"}}})

    assert Gateway(cfg).validate() == ["role 'chat': install clonway-cockpit[litellm]"]


def test_validate_clean_config_returns_empty(monkeypatch):
    monkeypatch.setenv("GW_CHAT_KEY", "sk-test")

    assert Gateway(_config()).validate() == []


def test_bad_pricing_entry_now_raises_gateway_error():
    with pytest.raises(GatewayError, match="pricing for 'gpt-4o-mini' must be a mapping"):
        _config(
            {
                "roles": {
                    "chat": {
                        "provider": "openai_compatible",
                        "base_url": "https://api.example/v1",
                        "model": "gpt-4o-mini",
                    }
                },
                "pricing": {"gpt-4o-mini": "cheap"},
            }
        )


def test_unknown_top_level_config_keys_are_recorded_as_warnings():
    cfg = _config(
        {
            "roles": {
                "chat": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.example/v1",
                    "model": "gpt-4o-mini",
                }
            },
            "future": True,
        }
    )

    assert cfg.warnings == ("unknown gateway config key: 'future'",)
