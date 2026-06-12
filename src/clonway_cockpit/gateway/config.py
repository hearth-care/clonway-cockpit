"""Validate a plain-dict role→model config (no YAML / JSON-Schema dependency).

A consumer (worker / operator) supplies the mapping; how they store it on disk
(YAML, JSON, TOML, hardcoded) is their choice. API keys are referenced by the
NAME of an env var, never stored here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import GatewayError, Usage

_SUPPORTED_PROVIDERS = ("openai_compatible", "litellm")


@dataclass(frozen=True)
class RoleConfig:
    """Resolved settings for one role (e.g. "chat", "gate")."""

    provider: str
    model: str
    base_url: str = ""
    api_key_env: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass(frozen=True)
class GatewayConfig:
    """A validated role→model map plus an optional pricing table."""

    roles: dict[str, RoleConfig]
    pricing: dict[str, dict[str, float]]
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> GatewayConfig:
        if not isinstance(data, Mapping):
            raise GatewayError("gateway config must be a mapping")
        known_keys = {"roles", "pricing"}
        warnings = tuple(
            f"unknown gateway config key: {key!r}" for key in data if key not in known_keys
        )
        roles_in = data.get("roles")
        if not isinstance(roles_in, Mapping) or not roles_in:
            raise GatewayError("gateway config needs a non-empty 'roles' mapping")
        roles: dict[str, RoleConfig] = {}
        for name, rc in roles_in.items():
            if not isinstance(rc, Mapping):
                raise GatewayError(f"role {name!r} must be a mapping")
            provider = rc.get("provider")
            if provider not in _SUPPORTED_PROVIDERS:
                raise GatewayError(f"role {name!r}: provider must be one of {_SUPPORTED_PROVIDERS}")
            if not rc.get("model"):
                raise GatewayError(f"role {name!r} missing 'model'")
            # base_url is the literal endpoint for openai_compatible (required); litellm
            # routes by the model's provider prefix, so base_url is optional there (it maps
            # to litellm's api_base when given — e.g. a local Ollama).
            if provider == "openai_compatible" and not rc.get("base_url"):
                raise GatewayError(f"role {name!r} (openai_compatible) missing 'base_url'")
            try:
                timeout = float(rc.get("timeout", 30.0))
            except (TypeError, ValueError):
                raise GatewayError(f"role {name!r}: 'timeout' must be a number") from None
            roles[name] = RoleConfig(
                provider=str(provider),
                model=str(rc["model"]),
                base_url=str(rc.get("base_url") or ""),
                api_key_env=(str(rc["api_key_env"]) if rc.get("api_key_env") else None),
                params=dict(rc.get("params") or {}),
                timeout=timeout,
            )
        pricing_in = data.get("pricing") or {}
        if not isinstance(pricing_in, Mapping):
            raise GatewayError("'pricing' must be a mapping if present")
        pricing: dict[str, dict[str, float]] = {}
        for model, rate in pricing_in.items():
            if not isinstance(rate, Mapping):
                raise GatewayError(f"pricing for {model!r} must be a mapping")
            try:
                pricing[str(model)] = {str(k): float(v) for k, v in rate.items()}
            except (TypeError, ValueError):
                raise GatewayError(f"pricing for {model!r} has a non-numeric rate") from None
        return cls(roles=roles, pricing=pricing, warnings=warnings)

    def resolve(self, role: str) -> RoleConfig:
        try:
            return self.roles[role]
        except KeyError:
            raise GatewayError(f"unknown role: {role!r}") from None

    def cost_for(self, model: str, usage: Usage) -> float | None:
        rate = self.pricing.get(model)
        if not rate:
            return None
        cost = usage.prompt_tokens / 1000 * rate.get(
            "prompt", 0.0
        ) + usage.completion_tokens / 1000 * rate.get("completion", 0.0)
        return round(cost, 6)
