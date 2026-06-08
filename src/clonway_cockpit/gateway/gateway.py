"""The model-gateway port: ``complete`` + ``complete_structured`` over an
injected role→model config, through one adapter, recording per-call telemetry.

The adapter is built via an injectable ``adapter_factory`` (default the real
OpenAI-compatible one) so consumers can swap providers and tests need no network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .adapters import OpenAICompatibleAdapter
from .config import GatewayConfig
from .telemetry import record_call
from .types import Completion, GatewayError, Message


class _Adapter(Protocol):
    """Structural type for anything the gateway can drive."""

    def complete(self, model: str, messages: list[Message], **params: object) -> Completion: ...


AdapterFactory = Callable[..., _Adapter]


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        telemetry_base: Path | None = None,
        adapter_factory: AdapterFactory = OpenAICompatibleAdapter,
    ) -> None:
        self._config = config
        self._telemetry_base = telemetry_base
        self._adapter_factory = adapter_factory

    def complete(self, messages: list[Message], *, role: str) -> str:
        return self._call(list(messages), role, {}).text

    def complete_structured(self, messages: list[Message], schema: dict, *, role: str) -> dict:
        instruction: Message = {
            "role": "system",
            "content": (
                "Respond with ONLY a single JSON object that satisfies this schema "
                f"(no prose, no code fences): {json.dumps(schema)}"
            ),
        }
        comp = self._call(
            [instruction, *messages], role, {"response_format": {"type": "json_object"}}
        )
        return _validate_required(_extract_json(comp.text), schema)

    def _call(self, messages: list[Message], role: str, extra: dict[str, object]) -> Completion:
        role_cfg = self._config.resolve(role)  # raises on unknown role
        key: str | None = None
        if role_cfg.api_key_env:
            key = os.environ.get(role_cfg.api_key_env)
            if not key:
                raise GatewayError(f"env var {role_cfg.api_key_env!r} is unset for role {role!r}")
        adapter = self._adapter_factory(role_cfg.base_url, key, timeout=role_cfg.timeout)
        params = {**role_cfg.params, **extra}
        comp: Completion | None = None
        ok = True
        err: str | None = None
        try:
            comp = adapter.complete(role_cfg.model, messages, **params)
            return comp
        except GatewayError as exc:
            ok = False
            err = type(exc).__name__
            raise
        finally:
            usage = comp.usage if comp is not None else None
            record_call(
                self._telemetry_base,
                role=role,
                provider=role_cfg.provider,
                model=role_cfg.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                est_cost=self._config.cost_for(role_cfg.model, usage) if usage else None,
                ok=ok,
                err=err,
            )


def _extract_json(text: str) -> object:
    """Parse a JSON object out of model text, tolerating prose / ``` fences."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise GatewayError("structured output is not valid JSON") from None


def _validate_required(obj: object, schema: dict) -> dict:
    """Lightweight, dependency-free validation: it's an object and every
    ``schema['required']`` key is present. NOT full JSON Schema."""
    if not isinstance(obj, dict):
        raise GatewayError("structured output is not a JSON object")
    for key in schema.get("required", []):
        if key not in obj:
            raise GatewayError(f"structured output missing required key: {key!r}")
    return obj
