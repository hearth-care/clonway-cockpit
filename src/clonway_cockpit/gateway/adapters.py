"""OpenAI-compatible chat-completions adapter over stdlib ``urllib`` — zero new
runtime dependency. Provider-agnostic by ``base_url``: the same adapter reaches
OpenAI, Groq/Together, a local Ollama/vLLM, or a LiteLLM proxy. Every failure
(non-2xx, transport, timeout, malformed body) becomes a ``GatewayError`` raised
to the caller — the call is NOT best-effort.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .types import AssistantTurn, Completion, GatewayError, Message, ToolCall, Usage


def _parse_arguments(raw: object) -> dict:
    """Tool-call arguments arrive as a JSON string (OpenAI) or already a dict. Parse
    leniently — a malformed argument blob becomes ``{}`` rather than crashing the turn."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str | bytes | bytearray):
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _post(self, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions", data=data, method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200] if hasattr(exc, "read") else b""
            raise GatewayError(f"HTTP {exc.code} from {self._base_url}: {detail!r}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GatewayError(f"transport error to {self._base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GatewayError(f"non-JSON response from {self._base_url}") from exc
        if not isinstance(payload, dict):
            raise GatewayError("completion response was not a JSON object")
        return payload

    def complete(self, model: str, messages: list[Message], **params: object) -> Completion:
        return self._parse(self._post({"model": model, "messages": list(messages), **params}))

    def complete_tools(
        self, model: str, messages: list[Message], tools: list[dict], **params: object
    ) -> AssistantTurn:
        payload = self._post(
            {"model": model, "messages": list(messages), "tools": list(tools), **params}
        )
        return self._parse_tools(payload)

    @staticmethod
    def _parse(payload: object) -> Completion:
        if not isinstance(payload, dict):
            raise GatewayError("completion response was not a JSON object")
        try:
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise GatewayError(f"malformed completion payload: {exc}") from exc
        if not isinstance(text, str):
            raise GatewayError("completion content was not a string")
        return Completion(
            text=text,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )

    @staticmethod
    def _parse_tools(payload: dict) -> AssistantTurn:
        try:
            message = payload["choices"][0]["message"]
            usage = payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(f"malformed tool-use payload: {exc}") from exc
        content = message.get("content")
        text = content if isinstance(content, str) and content else None
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            try:
                fn = tc["function"]
                tool_calls.append(
                    ToolCall(
                        id=str(tc.get("id", "")),
                        name=str(fn["name"]),
                        arguments=_parse_arguments(fn.get("arguments")),
                    )
                )
            except (KeyError, TypeError) as exc:
                raise GatewayError(f"malformed tool_call: {exc}") from exc
        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )


def _litellm() -> object:
    """Lazy import of the optional ``litellm`` dependency (kept out of the core so the
    framework stays ``rich``-only). Patchable in tests."""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - exercised via the patched seam in tests
        raise GatewayError(
            "the litellm provider needs the optional dependency — "
            "install `clonway-cockpit[litellm]`"
        ) from exc
    return litellm


class LiteLLMAdapter:
    """Adapter over `LiteLLM <https://docs.litellm.ai>`_ — one OpenAI-shaped interface
    routing to 100+ providers by the model's prefix (``anthropic/claude-haiku-4-5``,
    ``gpt-4o-mini``, ``ollama/llama3.1``…). This is where the gateway's passthrough
    *lands*: LiteLLM forwards Anthropic ``cache_control`` markers (realising prompt
    caching) and translates OpenAI ``image_url`` parts into each provider's native
    vision shape. Keys come from the provider's env var (``ANTHROPIC_API_KEY``,
    ``OPENAI_API_KEY``…) or an explicit ``api_key``. ``litellm`` is an optional extra.
    """

    def __init__(
        self, api_key: str | None, *, timeout: float = 30.0, api_base: str | None = None
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._api_base = api_base or None

    def _invoke(self, model: str, messages: list[Message], **params: object) -> object:
        litellm = _litellm()
        kwargs: dict[str, object] = {
            "model": model,
            "messages": list(messages),
            "timeout": self._timeout,
            **params,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        try:
            return litellm.completion(**kwargs)  # type: ignore[attr-defined]
        except GatewayError:
            raise
        except Exception as exc:  # noqa: BLE001 — litellm raises many types; normalise them
            raise GatewayError(f"litellm completion failed for {model!r}: {exc}") from exc

    def complete(self, model: str, messages: list[Message], **params: object) -> Completion:
        return self._parse(self._invoke(model, messages, **params))

    def complete_tools(
        self, model: str, messages: list[Message], tools: list[dict], **params: object
    ) -> AssistantTurn:
        return self._parse_tools(self._invoke(model, messages, tools=list(tools), **params))

    @staticmethod
    def _parse(response: object) -> Completion:
        # LiteLLM returns an OpenAI-shaped ModelResponse (attribute access).
        try:
            text = response.choices[0].message.content  # type: ignore[attr-defined]
            usage = response.usage  # type: ignore[attr-defined]
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(f"malformed litellm response: {exc}") from exc
        if not isinstance(text, str):
            raise GatewayError("litellm completion content was not a string")
        return Completion(
            text=text,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )

    @staticmethod
    def _parse_tools(response: object) -> AssistantTurn:
        try:
            message = response.choices[0].message  # type: ignore[attr-defined]
            usage = response.usage  # type: ignore[attr-defined]
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(f"malformed litellm tool-use response: {exc}") from exc
        content = getattr(message, "content", None)
        text = content if isinstance(content, str) and content else None
        tool_calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            try:
                fn = tc.function
                tool_calls.append(
                    ToolCall(
                        id=str(getattr(tc, "id", "")),
                        name=str(fn.name),
                        arguments=_parse_arguments(fn.arguments),
                    )
                )
            except (AttributeError, TypeError) as exc:
                raise GatewayError(f"malformed litellm tool_call: {exc}") from exc
        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )
