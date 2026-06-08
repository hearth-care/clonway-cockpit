"""Provider-agnostic model gateway (slice 1: port + OpenAI-compatible adapter + telemetry).

Public API::

    from pathlib import Path
    from clonway_cockpit.gateway import Gateway, GatewayConfig

    gw = Gateway(GatewayConfig.from_dict(cfg), telemetry_base=Path(".cockpit"))
    text = gw.complete([{"role": "user", "content": "hi"}], role="chat")
"""

from .adapters import OpenAICompatibleAdapter
from .config import GatewayConfig, RoleConfig
from .gateway import Gateway
from .telemetry import load_events, record_call
from .types import Completion, GatewayError, Message, Usage

__all__ = [
    "Completion",
    "Gateway",
    "GatewayConfig",
    "GatewayError",
    "Message",
    "OpenAICompatibleAdapter",
    "RoleConfig",
    "Usage",
    "load_events",
    "record_call",
]
