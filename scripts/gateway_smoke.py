"""Watched-working driver for the model gateway — makes ONE real call.

Run against the cheapest real OpenAI-compatible endpoint you have. Examples:

  # local Ollama (free, no key) — `ollama serve` + `ollama pull llama3.1`
  GATEWAY_BASE_URL=http://localhost:11434/v1 GATEWAY_MODEL=llama3.1 \
      python scripts/gateway_smoke.py

  # OpenAI (cheap) — needs OPENAI_API_KEY in the env
  GATEWAY_BASE_URL=https://api.openai.com/v1 GATEWAY_MODEL=gpt-4o-mini \
      GATEWAY_API_KEY_ENV=OPENAI_API_KEY python scripts/gateway_smoke.py

It prints the model's reply and the telemetry event written to ./.cockpit/model_usage.jsonl.
"""

from __future__ import annotations

import os
from pathlib import Path

from clonway_cockpit.gateway import Gateway, GatewayConfig, load_events


def main() -> None:
    base_url = os.environ.get("GATEWAY_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("GATEWAY_MODEL", "llama3.1")
    api_key_env = os.environ.get("GATEWAY_API_KEY_ENV")  # None for keyless local servers
    telemetry_base = Path(".cockpit")

    cfg = GatewayConfig.from_dict(
        {
            "roles": {
                "chat": {
                    "provider": "openai_compatible",
                    "base_url": base_url,
                    "model": model,
                    "api_key_env": api_key_env,
                    "params": {"temperature": 0.0},
                }
            },
            "pricing": {"gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006}},
        }
    )
    gw = Gateway(cfg, telemetry_base=telemetry_base)

    print(f"→ calling {model} at {base_url} ...")
    reply = gw.complete(
        [{"role": "user", "content": "Reply with exactly: gateway online"}], role="chat"
    )
    print(f"← reply: {reply!r}")

    events = load_events(telemetry_base)
    print(f"telemetry record: {events[-1] if events else '(none written)'}")


if __name__ == "__main__":
    main()
