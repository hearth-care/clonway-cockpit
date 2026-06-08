"""Provider-agnostic model gateway: port + adapters (OpenAI-compatible, LiteLLM) + telemetry.

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
    AssistantTurn,
    Completion,
    ContentPart,
    GatewayError,
    Message,
    ToolCall,
    Usage,
    image_part,
    text_part,
)

__all__ = [
    "AssistantTurn",
    "Completion",
    "ContentPart",
    "Gateway",
    "GatewayConfig",
    "GatewayError",
    "LiteLLMAdapter",
    "Message",
    "OpenAICompatibleAdapter",
    "RoleConfig",
    "ToolCall",
    "Usage",
    "fanin_relpath",
    "flush_model_usage",
    "image_part",
    "load_events",
    "local_dir_sink",
    "record_call",
    "text_part",
]
