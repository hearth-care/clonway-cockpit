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

from .types import Completion, GatewayError, Message, Usage


class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def complete(self, model: str, messages: list[Message], **params: object) -> Completion:
        body = {"model": model, "messages": list(messages), **params}
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
        return self._parse(payload)

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
