# Using the model gateway

`clonway_cockpit.gateway` is a thin, provider-agnostic seam for model calls. The
framework hardcodes no provider and stores no key; a consumer injects a config.
It is the chokepoint every model call passes through — the place a later slice
adds cost caps and from which xops reads model spend. See the design spec at
[`superpowers/specs/2026-06-08-model-gateway-design.md`](superpowers/specs/2026-06-08-model-gateway-design.md)
and the platform context in [`persona-platform-architecture.md`](persona-platform-architecture.md).

## Construct

```python
from pathlib import Path
from clonway_cockpit.gateway import Gateway, GatewayConfig

cfg = GatewayConfig.from_dict({
    "roles": {
        "chat": {"provider": "openai_compatible",
                 "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
                 "api_key_env": "OPENAI_API_KEY", "params": {"temperature": 0.2}},
        "gate": {"provider": "openai_compatible",
                 "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    },
    "pricing": {"gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006}},
})
gw = Gateway(cfg, telemetry_base=Path(".cockpit"))
```

The config is a **plain dict** — store it as YAML/JSON/TOML and parse it however
you like; the framework adds no config-format dependency. API keys come from the
**named env var**, never the config file.

## Call

```python
text = gw.complete([{"role": "user", "content": "cash position?"}], role="chat")

schema = {"type": "object", "required": ["summary", "amount"]}
obj = gw.complete_structured([{"role": "user", "content": "summarise"}], schema, role="chat")
```

`role` selects the model. Failures raise `GatewayError`. `complete_structured`
parses JSON from the reply and checks the `required` keys are present
(lightweight — not full JSON Schema).

## Telemetry

Every call appends one event to `<telemetry_base>/model_usage.jsonl`
(`ts, role, provider, model, prompt_tokens, completion_tokens, est_cost, ok, err`).
It is best-effort and never breaks a call. This is the per-call model-spend stream
a later slice surfaces in xops. Read it back with `load_events(base)`.

## Scope (slice 1)

One OpenAI-compatible adapter — works against OpenAI, Groq/Together, a local
Ollama/vLLM, or a LiteLLM proxy via `base_url`. Cost caps, a circuit-breaker, and
the LiteLLM / Anthropic adapters are later slices.

## Watched-working

`scripts/gateway_smoke.py` makes one real call against an endpoint of your
choosing and prints the reply plus the telemetry record. See its header for the
env vars (`GATEWAY_BASE_URL`, `GATEWAY_MODEL`, `GATEWAY_API_KEY_ENV`).
