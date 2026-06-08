"""Watched-working driver for the model gateway — makes ONE real call.

Run it with a single bare line (no env vars, nothing for the shell to mangle):

    python3 /Users/olliepage/Developer/clonway-cockpit/.claude/worktrees/model-gateway/scripts/gateway_smoke.py

It self-bootstraps its import path (the gateway is stdlib-only, so no uv / active
venv is needed) and PROMPTS for the endpoint, model, and key. What to enter:

  - local Ollama (free):  base URL http://localhost:11434/v1   model llama3.1     key (blank)
  - OpenAI (cheap):       base URL https://api.openai.com/v1    model gpt-4o-mini  key sk-...
  - Groq (free tier):     base URL https://api.groq.com/openai/v1  model llama-3.1-8b-instant  key gsk-...

It prints the model's reply and the telemetry event written to the worktree's
.cockpit/model_usage.jsonl.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make this runnable with a bare `python3 <path>` from anywhere: add the worktree's
# src/ so clonway_cockpit imports without uv or an active venv (the gateway is
# stdlib-only — nothing to install).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clonway_cockpit.gateway import Gateway, GatewayConfig, load_events  # noqa: E402


def _ask(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    # zsh paste-escaping can insert literal backslashes before URL punctuation; undo it.
    for esc in ("\\?", "\\=", "\\&", "\\:"):
        raw = raw.replace(esc, esc[1])
    return raw or default


def main() -> None:
    print("Model-gateway smoke — one real call. Press Enter to accept each [default].\n")
    base_url = _ask("Endpoint base URL", "http://localhost:11434/v1")
    model = _ask("Model", "llama3.1")
    api_key = _ask("API key (blank for keyless local servers)", "")

    api_key_env: str | None = None
    if api_key:
        os.environ["GATEWAY_SMOKE_KEY"] = api_key
        api_key_env = "GATEWAY_SMOKE_KEY"

    telemetry_base = Path(__file__).resolve().parent.parent / ".cockpit"
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

    print(f"\n→ calling {model} at {base_url} ...")
    try:
        reply = gw.complete(
            [{"role": "user", "content": "Reply with exactly: gateway online"}], role="chat"
        )
    except Exception as exc:  # noqa: BLE001 — surface any failure plainly to the operator
        print(f"\n✗ call failed: {type(exc).__name__}: {exc}")
        events = load_events(telemetry_base)
        if events:
            print(f"telemetry record (failure): {events[-1]}")
        raise SystemExit(1) from exc

    print(f"← reply: {reply!r}")
    events = load_events(telemetry_base)
    print(f"telemetry record: {events[-1] if events else '(none written)'}")


if __name__ == "__main__":
    main()
