"""Provider-agnostic model gateway (slice 1: port + OpenAI-compatible adapter + telemetry).

Public API::

    from pathlib import Path
    from clonway_cockpit.gateway import Gateway, GatewayConfig

    gw = Gateway(GatewayConfig.from_dict(cfg), telemetry_base=Path(".cockpit"))
    text = gw.complete([{"role": "user", "content": "hi"}], role="chat")
"""

from .adapters import LiteLLMAdapter, OpenAICompatibleAdapter
from .config import GatewayConfig, RoleConfig
from .gateway import Gateway
from .telemetry import (
    fanin_relpath,
    flush_model_usage,
    load_events,
    local_dir_sink,
    record_call,
)
from .types import (
    Completion,
    ContentPart,
    GatewayError,
    Message,
    Usage,
    image_part,
    text_part,
)

__all__ = [
    "Completion",
    "ContentPart",
    "Gateway",
    "GatewayConfig",
    "GatewayError",
    "LiteLLMAdapter",
    "Message",
    "OpenAICompatibleAdapter",
    "RoleConfig",
    "Usage",
    "fanin_relpath",
    "flush_model_usage",
    "image_part",
    "load_events",
    "local_dir_sink",
    "record_call",
    "text_part",
]
