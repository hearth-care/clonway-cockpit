# Model gateway — slice 1, the walking skeleton (design)

**Status:** approved-to-build (owner: "looks good, let's go"), 2026-06-08.
**Slice:** #3 of the persona platform — see [`docs/persona-platform-architecture.md`](../../persona-platform-architecture.md),
the "Model gateway" section. This spec is the thin first slice of that vision, not the whole gateway.
**Goal:** one thin, provider-agnostic seam in `clonway-cockpit` through which a model call passes —
`complete(messages) -> text` plus a structured variant — with the provider chosen by config
(role → model) and every call emitting per-call usage telemetry. The gateway is the chokepoint that
will later carry cost caps and feed xops the model-£ it currently cannot see; this slice lays the
seam and the telemetry, nothing more.

## Why this slice, and why thin

The gateway unblocks two things the owner cares about — wiring a live persona to a real model client,
and surfacing model spend in xops — so it comes before either. It is delivered as a **walking
skeleton**: prove a real model call can pass through *our own* interface (no vendor lock-in) and that
each call's token/cost usage is captured, end-to-end and watched working, before thickening it with
caps, a circuit-breaker, or more adapters. Keeping it thin is the point: a fat first slice is harder
to get demonstrably running in one PR.

## Scope

**In this slice:** the port (`complete` + `complete_structured`), one **OpenAI-compatible HTTP
adapter** (zero new runtime dependency), role → provider/model config (injected, secrets via env),
and per-call **usage telemetry** (best-effort, never-crash, mirroring `usage.py`).

**Explicitly NOT in this slice** (each a later slice): cost caps + circuit-breaker; the LiteLLM and
Anthropic-direct adapters (behind optional extras); xops *reading/surfacing* the telemetry; migrating
real call sites (Milo's Haiku, the WS-D router, the weekly report) onto the gateway.

## Placement

A `clonway_cockpit/gateway/` subpackage, mirroring the existing `signals/` precedent:

- `__init__.py` — the `Gateway` object + port types (`Message`, `Completion`, `GatewayError`).
- `adapters.py` — `OpenAICompatibleAdapter`.
- `config.py` — load + validate the role→model config and the pricing table.
- `telemetry.py` — the best-effort per-call usage emitter.

## The port (the only surface consumers see)

The framework hardcodes **no provider and ships no secret**. A `Gateway` is constructed from config
and **injected** into consumers, exactly like the `Conversation` seams (`conversation.py`) and the
`usage.py` injectable base.

```python
class Gateway:
    def __init__(self, config: GatewayConfig, *, telemetry_base: Path | None = None) -> None: ...

    def complete(self, messages: list[Message], *, role: str) -> str: ...
    def complete_structured(self, messages: list[Message], schema: dict, *, role: str) -> dict: ...
```

- `Message` is OpenAI-shaped — `{"role": "system"|"user"|"assistant", "content": str}` — so the
  baseline adapter is a near pass-through. (A `TypedDict` for mypy; a plain dict at runtime.)
- `role` (`"chat"`, `"gate"`, `"router"`, …) is the owner's **role → model** mapping made concrete:
  it selects the config entry that resolves provider + model + params. An unknown role is a
  `GatewayError` (config bug, fail loud).
- `complete` returns the assistant text. `complete_structured` returns a dict parsed from the
  model's JSON output and **validated against `schema`** (raises `GatewayError` on parse/validation
  failure); the adapter requests JSON via the OpenAI `response_format` field where supported, and the
  prompt carries the schema as a fallback for servers that ignore it.

## The adapter (OpenAI-compatible, zero new dependency)

```python
class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 30.0) -> None: ...
    def complete(self, model: str, messages: list[Message], **params) -> Completion: ...
```

- **Transport: stdlib `urllib.request`** — a true zero-dependency baseline; the framework stays
  `rich`-only. (`httpx` is deferred until we need async/streaming, and would then sit behind an
  optional extra.) POSTs `{base_url}/chat/completions` with `Authorization: Bearer <key>` when a key
  is present, JSON body `{model, messages, **params}`.
- **Provider-agnostic via `base_url`:** the same adapter reaches OpenAI, Groq/Together, a local
  Ollama/vLLM (`http://localhost:11434/v1`, no key), or a LiteLLM proxy. This is the no-lock-in proof.
- Parses `choices[0].message.content` into `Completion.text` and `usage` into
  `Completion.usage = Usage(prompt_tokens, completion_tokens)`.
- **Errors:** non-2xx, network failure, timeout, and malformed/missing fields all become a typed
  `GatewayError` — **raised** to the caller. The call is *not* best-effort: the caller decides what a
  failure means (a gate may degrade, a write path must not).

## Config (role → provider/model; secrets stay out of the repo)

Injected by the consumer (worker/operator); the framework provides only the loader + validation.

```yaml
roles:
  chat:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY        # the NAME of the env var, never the key itself
    params: {temperature: 0.2}
  gate:                                 # the cheap/local "is this mine?" gate
    provider: openai_compatible
    base_url: http://localhost:11434/v1
    model: llama3.1
    api_key_env: null
pricing:                               # $ per 1K tokens, for cost estimation
  gpt-4o-mini: {prompt: 0.00015, completion: 0.0006}
```

- API keys come from the **named env var only** — never the file, never the repo (house rule:
  secrets in env / Secret Manager). A role whose `api_key_env` is set but unset in the environment is
  a `GatewayError` at call time.
- `pricing` lets telemetry estimate cost. A model absent from `pricing` records `est_cost: null` —
  tokens are still recorded. Provider `!= openai_compatible` is a validation error this slice (only
  one adapter exists yet).

## Telemetry (mirrors `usage.py`: local, best-effort, never-crash)

Every `complete` / `complete_structured` call appends one event to **`model_usage.jsonl`** in the
injectable state dir (an event stream — distinct from `usage.py`'s counter rollup, which suits
capability-open counts but not per-call cost). Fields:

```
{ts, role, provider, model, prompt_tokens, completion_tokens, est_cost|null, ok, err|null}
```

- Same two hard guarantees as `usage.py`: **local-only, no extra network**, and **never crashes the
  call** — every read/write is wrapped; an unwritable/locked base degrades to a silent no-op. A
  telemetry failure must not turn a successful model call into a failed one.
- A failed call (a raised `GatewayError`) still emits a record with `ok: false` and the error class,
  so the spend / reliability view later sees failures too.
- This is exactly the per-call model-£ stream the owner noted xops cannot currently see (it bills
  outside GCP). This slice **emits** it in a clean shape; a later slice has xops read and surface it.

## Errors & robustness

- `GatewayError` — single typed error for config, transport, HTTP, parse, and validation failures;
  raised to the caller. Telemetry swallows its own errors separately.
- 30s default timeout on the adapter — also sets up the later Chat ~30s round-trip constraint.
- No caps / circuit-breaker this slice. The telemetry emitted here is precisely what a cap will read
  in the next slice, so nothing is wasted.

## Dependency packaging

**Zero new runtime dependency** (stdlib `urllib`). The framework stays `rich`-only so its zero-LLM
consumers (contract, render, signals) gain nothing to install. Future heavy adapters (LiteLLM, the
Anthropic SDK) go behind optional extras — `clonway-cockpit[litellm]`, `clonway-cockpit[anthropic]` —
documented when built, not added now.

## Testing & the watched-working proof

Per the project's verify-before-claiming rule, the slice is not "done" until a real call is watched.

- **Unit (fast, in CI):**
  - adapter parse over mocked HTTP — success, non-2xx, timeout, malformed/missing `content`/`usage`;
  - gateway role-resolution — known role resolves; unknown role / missing env key → `GatewayError`;
  - telemetry — record shape on success and on a raised error; **never-crash** when the base dir is
    unwritable;
  - `complete_structured` — valid JSON matching schema passes; non-JSON and schema-mismatch raise.
- **Watched-working (the real proof — run by hand, output pasted into the PR):** `scripts/gateway_smoke.py`
  loads a real config + key from env, makes **one real `complete()` call** against a real
  OpenAI-compatible endpoint, and prints the reply *and* the `model_usage.jsonl` record written. The
  endpoint is a build-time logistics choice (not a design blocker): the cheapest real option — a local
  **Ollama** (free, no key) or a cheap cloud model (**OpenAI `gpt-4o-mini`** / Groq free tier).
  Confirm which at build time.
- **Docs in the same PR:** this spec + a short `docs/model-gateway.md` usage note (construct a
  `Gateway`, the config shape, `complete`/`complete_structured`, where telemetry lands).

## Acceptance

1. A `Gateway` built from a role→model config makes a **real** `complete()` call through the
   OpenAI-compatible adapter and returns the model's text — watched, output in the PR.
2. That call writes a `model_usage.jsonl` record with non-zero token counts (and a cost estimate when
   the model is priced).
3. Unit suite green; ruff / format / mypy clean; the framework gains **no** new runtime dependency.
4. `complete_structured` returns a validated dict for a simple schema (watched in the same smoke run
   or a unit test against a stub).
