"""Shared, dependency-free types for the model gateway port.

``Message`` is OpenAI-shaped so the baseline adapter is a near pass-through.
``GatewayError`` is the single error every gateway layer raises (config,
transport, HTTP, parse, validation). ``Usage``/``Completion`` are what an
adapter returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class Message(TypedDict):
    """One chat message in OpenAI shape."""

    role: str  # "system" | "user" | "assistant"
    content: str


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
