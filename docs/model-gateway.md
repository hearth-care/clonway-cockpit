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

## Multimodal & prompt caching

A message's `content` is a plain string in the common case, but may also be a list of
OpenAI-shaped **content parts** for images and provider passthrough markers. Build them
with `text_part` / `image_part`:

```python
from clonway_cockpit.gateway import text_part, image_part

gw.complete([
    {"role": "user", "content": [
        text_part("What's in this photo?"),
        image_part("data:image/png;base64,<...>"),   # or an http(s) URL
    ]},
], role="vision")          # the role must map to a vision-capable model
```

The gateway is **transparent** — it passes content parts through untouched, so:

- **Multimodal:** image parts reach any vision model behind the role (OpenAI `gpt-4o`,
  a local `llava`/`qwen-vl`, …). A non-vision model will ignore or reject them.
- **Prompt caching:** `text_part(..., cache=True)` adds an Anthropic-style
  `cache_control: ephemeral` marker. It's honoured by backends that support it (a
  LiteLLM proxy fronting Anthropic); harmless-but-ignored elsewhere. Don't set it
  against a direct OpenAI endpoint (which auto-caches and may reject the field). The
  gateway neither implements nor strips caching — efficacy is the backend's.

## Providers: `openai_compatible` vs `litellm`

A role's `provider` picks the adapter:

- **`openai_compatible`** (default, zero-dependency) — POSTs to a literal
  `<base_url>/chat/completions`. Use for OpenAI, Groq/Together, a local Ollama/vLLM,
  or a LiteLLM proxy. `base_url` is required; `cache_control` and `image_url` parts
  pass through, but whether caching/vision actually happen is the *backend's* job.
- **`litellm`** — routes through [LiteLLM](https://docs.litellm.ai): one OpenAI-shaped
  interface to 100+ providers, selected by the model's prefix. This is where the
  passthrough *lands* — LiteLLM forwards Anthropic `cache_control` (realising prompt
  caching) and translates `image_url` parts into each provider's native vision shape.
  `base_url` is optional (the prefix routes; set it as LiteLLM's `api_base` for a local
  endpoint). Needs the optional extra — `pip install clonway-cockpit[litellm]`.

```yaml
roles:
  chat:  {provider: litellm, model: anthropic/claude-haiku-4-5, api_key_env: ANTHROPIC_API_KEY}
  vision:{provider: litellm, model: claude-opus-4-8, api_key_env: ANTHROPIC_API_KEY}
  gate:  {provider: litellm, model: ollama/qwen2.5:0.5b, base_url: http://localhost:11434}
```

Model ids are LiteLLM's provider-prefixed form (`anthropic/claude-haiku-4-5`,
`gpt-4o-mini`, `ollama/llama3.1`); keys come from the provider's env var. With a LiteLLM
backend, verify caching landed via the provider's `cache_read_input_tokens` (Anthropic's
minimum cacheable prefix is ~1024–4096 tokens depending on model — shorter prefixes
silently won't cache).

## Tool use

`complete_tools(messages, tools, role)` is one **tool-use turn**: pass OpenAI-shaped
function schemas and get back the assistant's free text and/or its tool-call requests.

```python
from clonway_cockpit.gateway import Gateway

turn = gw.complete_tools(
    [{"role": "user", "content": "any bills due?"}],
    tools=[{"type": "function", "function": {
        "name": "get_bills_due", "description": "List bills due", "parameters": {"type": "object"}}}],
    role="chat",          # role must map to a tool-capable model
)
# turn.text: str | None   ·   turn.tool_calls: list[ToolCall(id, name, arguments: dict)]
```

The gateway is **one-shot per turn and owns no loop** — the *caller* runs each requested
tool, appends a `{"role": "tool", "tool_call_id": ..., "content": ...}` message, and calls
`complete_tools` again until `tool_calls` is empty. `arguments` is parsed from the
provider's JSON-string form (a malformed blob degrades to `{}` rather than crashing the
turn). Works against any tool-capable backend (a recent Ollama with a tool model, OpenAI,
or LiteLLM→Anthropic). A model that can't tool-call simply returns text with no
`tool_calls`. The turn is recorded in telemetry like any other call.

## Telemetry

Every call appends one event to `<telemetry_base>/model_usage.jsonl`
(`ts, role, provider, model, prompt_tokens, completion_tokens, est_cost, ok, err`).
It is **content-free** (no prompt/completion text, tool names or args — only counts and
metadata) and best-effort, never breaking a call. A **failed** call is recorded too, with
`ok=false` and `err` set to the exception type (e.g. `GatewayError`), so failures are
visible fleet-wide. This is the per-call model-spend stream surfaced in the xops cost page.
Read it back with `load_events(base)`.

## Fleet fan-in

`model_usage.jsonl` is local to each worker. To build a fleet-wide view, a worker
fans its file out to a shared location under a per-worker path, and xops lists that
prefix (deriving the worker from the path):

```python
from clonway_cockpit.gateway import flush_model_usage, local_dir_sink

# at the end of a run — best-effort, never raises:
flush_model_usage(
    Path(".cockpit"), worker="xbook", run_id="run-123", date="2026-06-08",
    sink=local_dir_sink(Path("/mnt/fleet-telemetry")),  # → model-usage/xbook/2026-06-08/run-123.jsonl
)
```

The framework provides the **path convention** (`fanin_relpath`), the **flush logic**,
and a stdlib **`local_dir_sink`** (write under a local dir / a GCS-FUSE mount). The
GCS-client sink is the caller's — `sink(relpath, data_bytes)` — so the framework adds
**no** storage dependency. `worker`/`run_id` must be safe slugs and `date` a
`YYYY-MM-DD`, else the flush is a no-op (no path escape). xops reading the fan-in tree
by-worker is a follow-up on its cost page.

## Scope

Two adapters ship: the zero-dependency `openai_compatible` one (OpenAI, Groq/Together,
a local Ollama/vLLM, or a LiteLLM proxy via `base_url`) and the optional `litellm` one
(provider-prefixed routing to 100+ providers, with Anthropic prompt-caching and native
vision). Cost caps and a circuit-breaker are later slices.

## Watched-working

`scripts/gateway_smoke.py` makes one real call against an endpoint of your
choosing and prints the reply plus the telemetry record. See its header for the
env vars (`GATEWAY_BASE_URL`, `GATEWAY_MODEL`, `GATEWAY_API_KEY_ENV`).
