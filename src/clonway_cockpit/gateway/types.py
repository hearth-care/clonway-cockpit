"""Shared, dependency-free types for the model gateway port.

``Message`` is OpenAI-shaped so the baseline adapter is a near pass-through.
``GatewayError`` is the single error every gateway layer raises (config,
transport, HTTP, parse, validation). ``Usage``/``Completion`` are what an
adapter returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

# An OpenAI-shaped content part, e.g. {"type": "text", "text": "..."} or
# {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}. Parts may
# carry provider-specific extras (e.g. an Anthropic ``cache_control`` marker) — the
# gateway is transparent and passes them through untouched.
ContentPart = dict[str, Any]


class Message(TypedDict):
    """One chat message in OpenAI shape.

    ``content`` is either a plain string (the common case) or a list of OpenAI-shaped
    content parts for multimodal input (text + images) and provider passthrough markers
    (prompt caching). Build parts with :func:`text_part` / :func:`image_part`.
    """

    role: str  # "system" | "user" | "assistant"
    content: str | list[ContentPart]


def text_part(text: str, *, cache: bool = False) -> ContentPart:
    """An OpenAI-shaped text content part. ``cache=True`` adds an Anthropic-style
    ``cache_control: ephemeral`` marker for prompt caching — honoured by backends that
    support it (e.g. a LiteLLM proxy fronting Anthropic); ignored by others. Do NOT set
    it against a direct OpenAI endpoint (which auto-caches and may reject the field)."""
    part: ContentPart = {"type": "text", "text": text}
    if cache:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def image_part(url: str) -> ContentPart:
    """An OpenAI-shaped image content part. ``url`` may be an http(s) URL or a
    ``data:`` URL carrying base64 image bytes (e.g.
    ``data:image/png;base64,<...>``). Needs a vision-capable model behind the role."""
    return {"type": "image_url", "image_url": {"url": url}}


class GatewayError(RuntimeError):
    """Any model-gateway failure: config, transport, HTTP, parse, or validation."""


@dataclass(frozen=True)
class Usage:
    """Token counts for a single completion."""

    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class Completion:
    """An adapter's result: the assistant text plus token usage."""

    text: str
    usage: Usage
