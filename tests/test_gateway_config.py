import pytest

from clonway_cockpit.gateway.config import GatewayConfig, RoleConfig
from clonway_cockpit.gateway.types import GatewayError, Usage

VALID = {
    "roles": {
        "chat": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
            "params": {"temperature": 0.2},
        },
        "gate": {
            "provider": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.1",
            "api_key_env": None,
        },
    },
    "pricing": {"gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006}},
}


def test_from_dict_parses_roles_and_pricing():
    cfg = GatewayConfig.from_dict(VALID)
    chat = cfg.resolve("chat")
    assert isinstance(chat, RoleConfig)
    assert chat.model == "gpt-4o-mini"
    assert chat.api_key_env == "OPENAI_API_KEY"
    assert chat.params == {"temperature": 0.2}
    assert cfg.resolve("gate").api_key_env is None
    assert cfg.resolve("gate").timeout == 30.0
    assert cfg.resolve("gate").params == {}


def test_resolve_unknown_role_raises():
    cfg = GatewayConfig.from_dict(VALID)
    with pytest.raises(GatewayError, match="unknown role"):
        cfg.resolve("nope")


def test_missing_roles_raises():
    with pytest.raises(GatewayError, match="roles"):
        GatewayConfig.from_dict({"pricing": {}})


def test_unsupported_provider_raises():
    bad = {"roles": {"x": {"provider": "anthropic", "base_url": "u", "model": "m"}}}
    with pytest.raises(GatewayError, match="openai_compatible"):
        GatewayConfig.from_dict(bad)


def test_missing_required_field_raises():
    bad = {"roles": {"x": {"provider": "openai_compatible", "model": "m"}}}
    with pytest.raises(GatewayError, match="base_url"):
        GatewayConfig.from_dict(bad)


def test_bad_timeout_raises_gateway_error():
    bad = {
        "roles": {
            "x": {"provider": "openai_compatible", "base_url": "u", "model": "m", "timeout": "soon"}
        }
    }
    with pytest.raises(GatewayError, match="timeout"):
        GatewayConfig.from_dict(bad)


def test_bad_pricing_rate_raises_gateway_error():
    bad = {
        "roles": {"x": {"provider": "openai_compatible", "base_url": "u", "model": "m"}},
        "pricing": {"m": {"prompt": "cheap"}},
    }
    with pytest.raises(GatewayError, match="non-numeric"):
        GatewayConfig.from_dict(bad)


def test_cost_for_priced_and_unpriced():
    cfg = GatewayConfig.from_dict(VALID)
    usage = Usage(prompt_tokens=1000, completion_tokens=1000)
    # 1000/1000*0.00015 + 1000/1000*0.0006 = 0.00075
    assert cfg.cost_for("gpt-4o-mini", usage) == pytest.approx(0.00075)
    assert cfg.cost_for("llama3.1", usage) is None  # not in pricing
