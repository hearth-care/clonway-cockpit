# Model Gateway (slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin, provider-agnostic model gateway to `clonway-cockpit` — `complete()` + `complete_structured()` over an injected role→model config, through one zero-dependency OpenAI-compatible HTTP adapter, with best-effort per-call usage telemetry.

**Architecture:** A new `clonway_cockpit/gateway/` subpackage (mirroring `signals/`). Shared types in `types.py`; `config.py` validates a plain dict; `adapters.py` is a stdlib-`urllib` OpenAI-compatible client; `telemetry.py` appends best-effort JSONL events (mirroring `usage.py`); `gateway.py` ties them together via a `Gateway` object with an injectable `adapter_factory` (so tests need no network). Public API re-exported from `__init__.py`.

**Tech Stack:** Python ≥3.12, stdlib only (`urllib.request`, `json`, `dataclasses`, `typing.TypedDict`, `pathlib`, `datetime`). No new runtime dependency — the framework stays `rich`-only. Tests: pytest + `monkeypatch`/`tmp_path`.

**Spec:** `docs/superpowers/specs/2026-06-08-model-gateway-design.md`.

**Conventions to follow:**
- Tests are **flat** in `tests/` named `test_gateway_*.py` (mirrors `test_signal_*.py`).
- Best-effort modules use `except Exception:  # noqa: BLE001` exactly like `usage.py`.
- Run the suite with `uv run pytest -q`. Lint/type with `uv run ruff check .`, `uv run ruff format .`, `uv run mypy src`.
- Commit messages use `feat:` / `test:` / `docs:`. **No `Co-Authored-By` / "Generated with" trailers** (repo rule).

---

## File structure

| File | Responsibility |
|---|---|
| `src/clonway_cockpit/gateway/types.py` | `Message` (TypedDict), `Usage`, `Completion` (frozen dataclasses), `GatewayError` |
| `src/clonway_cockpit/gateway/config.py` | `RoleConfig`, `GatewayConfig.from_dict` + `resolve` + `cost_for` |
| `src/clonway_cockpit/gateway/telemetry.py` | `record_call` (best-effort JSONL append), `load_events` |
| `src/clonway_cockpit/gateway/adapters.py` | `OpenAICompatibleAdapter` (stdlib urllib) |
| `src/clonway_cockpit/gateway/gateway.py` | `Gateway` + `_extract_json` + `_validate_required` |
| `src/clonway_cockpit/gateway/__init__.py` | re-export the public API |
| `scripts/gateway_smoke.py` | watched-working driver (one real call) |
| `docs/model-gateway.md` | usage note (in the same PR) |
| `tests/test_gateway_config.py` `…_telemetry.py` `…_adapter.py` `…_port.py` `…_package.py` | unit tests |

---

## Task 1: Port types (`gateway/types.py`)

**Files:**
- Create: `src/clonway_cockpit/gateway/__init__.py` (empty for now — makes the package importable)
- Create: `src/clonway_cockpit/gateway/types.py`
- Test: `tests/test_gateway_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_types.py
from clonway_cockpit.gateway.types import Completion, GatewayError, Message, Usage


def test_completion_carries_text_and_usage():
    comp = Completion(text="hi", usage=Usage(prompt_tokens=3, completion_tokens=5))
    assert comp.text == "hi"
    assert comp.usage.prompt_tokens == 3
    assert comp.usage.completion_tokens == 5


def test_gateway_error_is_runtime_error():
    assert issubclass(GatewayError, RuntimeError)


def test_message_is_a_plain_mapping():
    msg: Message = {"role": "user", "content": "ping"}
    assert msg["role"] == "user"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_types.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.gateway.types`

- [ ] **Step 3: Create the package marker and the types**

```python
# src/clonway_cockpit/gateway/__init__.py
"""Provider-agnostic model gateway (slice 1: port + OpenAI-compatible adapter + telemetry)."""
```

```python
# src/clonway_cockpit/gateway/types.py
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_types.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/__init__.py src/clonway_cockpit/gateway/types.py tests/test_gateway_types.py
git commit -m "feat(gateway): port types (Message, Usage, Completion, GatewayError)"
```

---

## Task 2: Config (`gateway/config.py`)

**Files:**
- Create: `src/clonway_cockpit/gateway/config.py`
- Test: `tests/test_gateway_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_config.py
import pytest

from clonway_cockpit.gateway.config import GatewayConfig, RoleConfig
from clonway_cockpit.gateway.types import GatewayError, Usage

VALID = {
    "roles": {
        "chat": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
            "params": {"temperature": 0.2},
        },
        "gate": {
            "provider": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.1",
            "api_key_env": None,
        },
    },
    "pricing": {"gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006}},
}


def test_from_dict_parses_roles_and_pricing():
    cfg = GatewayConfig.from_dict(VALID)
    chat = cfg.resolve("chat")
    assert isinstance(chat, RoleConfig)
    assert chat.model == "gpt-4o-mini"
    assert chat.api_key_env == "OPENAI_API_KEY"
    assert chat.params == {"temperature": 0.2}
    assert cfg.resolve("gate").api_key_env is None
    # defaults
    assert cfg.resolve("gate").timeout == 30.0
    assert cfg.resolve("gate").params == {}


def test_resolve_unknown_role_raises():
    cfg = GatewayConfig.from_dict(VALID)
    with pytest.raises(GatewayError, match="unknown role"):
        cfg.resolve("nope")


def test_missing_roles_raises():
    with pytest.raises(GatewayError, match="roles"):
        GatewayConfig.from_dict({"pricing": {}})


def test_unsupported_provider_raises():
    bad = {"roles": {"x": {"provider": "anthropic", "base_url": "u", "model": "m"}}}
    with pytest.raises(GatewayError, match="openai_compatible"):
        GatewayConfig.from_dict(bad)


def test_missing_required_field_raises():
    bad = {"roles": {"x": {"provider": "openai_compatible", "model": "m"}}}
    with pytest.raises(GatewayError, match="base_url"):
        GatewayConfig.from_dict(bad)


def test_cost_for_priced_and_unpriced():
    cfg = GatewayConfig.from_dict(VALID)
    usage = Usage(prompt_tokens=1000, completion_tokens=1000)
    # 1000/1000*0.00015 + 1000/1000*0.0006 = 0.00075
    assert cfg.cost_for("gpt-4o-mini", usage) == pytest.approx(0.00075)
    assert cfg.cost_for("llama3.1", usage) is None  # not in pricing
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_config.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.gateway.config`

- [ ] **Step 3: Implement the config**

```python
# src/clonway_cockpit/gateway/config.py
"""Validate a plain-dict role→model config (no YAML / JSON-Schema dependency).

A consumer (worker / operator) supplies the mapping; how they store it on disk
(YAML, JSON, TOML, hardcoded) is their choice. API keys are referenced by the
NAME of an env var, never stored here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .types import GatewayError, Usage

_SUPPORTED_PROVIDERS = ("openai_compatible",)


@dataclass(frozen=True)
class RoleConfig:
    """Resolved settings for one role (e.g. "chat", "gate")."""

    provider: str
    base_url: str
    model: str
    api_key_env: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass(frozen=True)
class GatewayConfig:
    """A validated role→model map plus an optional pricing table."""

    roles: dict[str, RoleConfig]
    pricing: dict[str, dict[str, float]]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> GatewayConfig:
        if not isinstance(data, Mapping):
            raise GatewayError("gateway config must be a mapping")
        roles_in = data.get("roles")
        if not isinstance(roles_in, Mapping) or not roles_in:
            raise GatewayError("gateway config needs a non-empty 'roles' mapping")
        roles: dict[str, RoleConfig] = {}
        for name, rc in roles_in.items():
            if not isinstance(rc, Mapping):
                raise GatewayError(f"role {name!r} must be a mapping")
            provider = rc.get("provider")
            if provider not in _SUPPORTED_PROVIDERS:
                raise GatewayError(
                    f"role {name!r}: only 'openai_compatible' provider is supported in this slice"
                )
            for required in ("base_url", "model"):
                if not rc.get(required):
                    raise GatewayError(f"role {name!r} missing {required!r}")
            roles[name] = RoleConfig(
                provider=str(provider),
                base_url=str(rc["base_url"]),
                model=str(rc["model"]),
                api_key_env=(str(rc["api_key_env"]) if rc.get("api_key_env") else None),
                params=dict(rc.get("params") or {}),
                timeout=float(rc.get("timeout", 30.0)),  # type: ignore[arg-type]
            )
        pricing_in = data.get("pricing") or {}
        if not isinstance(pricing_in, Mapping):
            raise GatewayError("'pricing' must be a mapping if present")
        pricing = {
            str(model): {str(k): float(v) for k, v in rate.items()}
            for model, rate in pricing_in.items()
            if isinstance(rate, Mapping)
        }
        return cls(roles=roles, pricing=pricing)

    def resolve(self, role: str) -> RoleConfig:
        try:
            return self.roles[role]
        except KeyError:
            raise GatewayError(f"unknown role: {role!r}") from None

    def cost_for(self, model: str, usage: Usage) -> float | None:
        rate = self.pricing.get(model)
        if not rate:
            return None
        cost = (
            usage.prompt_tokens / 1000 * rate.get("prompt", 0.0)
            + usage.completion_tokens / 1000 * rate.get("completion", 0.0)
        )
        return round(cost, 6)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_config.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/config.py tests/test_gateway_config.py
git commit -m "feat(gateway): plain-dict role→model config with validation + pricing"
```

---

## Task 3: Telemetry (`gateway/telemetry.py`)

**Files:**
- Create: `src/clonway_cockpit/gateway/telemetry.py`
- Test: `tests/test_gateway_telemetry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_telemetry.py
from pathlib import Path

from clonway_cockpit.gateway.telemetry import load_events, record_call


def _record(base: Path, **over: object) -> None:
    kw: dict[str, object] = dict(
        role="chat", provider="openai_compatible", model="gpt-4o-mini",
        prompt_tokens=10, completion_tokens=20, est_cost=0.0001, ok=True, err=None,
    )
    kw.update(over)
    record_call(base, **kw)  # type: ignore[arg-type]


def test_record_then_load_roundtrip(tmp_path: Path):
    _record(tmp_path)
    _record(tmp_path, ok=False, err="GatewayError", prompt_tokens=0, completion_tokens=0,
            est_cost=None)
    events = load_events(tmp_path)
    assert len(events) == 2
    first = events[0]
    assert first["role"] == "chat"
    assert first["model"] == "gpt-4o-mini"
    assert first["prompt_tokens"] == 10
    assert first["completion_tokens"] == 20
    assert first["ok"] is True
    assert "ts" in first
    assert events[1]["ok"] is False
    assert events[1]["err"] == "GatewayError"
    assert events[1]["est_cost"] is None


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_events(tmp_path / "nope") == []


def test_record_never_crashes_on_unwritable_base(tmp_path: Path):
    # base path lives *inside* a regular file → mkdir/open must fail and be swallowed
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    bad_base = blocker / "sub"
    _record(bad_base)  # must NOT raise
    assert load_events(bad_base) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_telemetry.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.gateway.telemetry`

- [ ] **Step 3: Implement the telemetry (mirror `usage.py`'s contract)**

```python
# src/clonway_cockpit/gateway/telemetry.py
"""Best-effort, local-only per-call usage telemetry for the model gateway.

Mirrors ``clonway_cockpit.usage`` exactly in posture: local file, no extra
network, and NEVER crashes the call. The difference is the shape — this is a
per-call EVENT stream (one JSONL line per model call, carrying tokens + an
estimated cost) rather than usage.py's capability-open counter rollup. It is the
model-£ stream xops cannot currently see (providers bill outside GCP); a later
slice has xops read it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_BASE = Path(".cockpit")
_FILENAME = "model_usage.jsonl"


def _path(base: Path | None) -> Path:
    return (base or _DEFAULT_BASE) / _FILENAME


def record_call(
    base: Path | None,
    *,
    role: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    est_cost: float | None,
    ok: bool,
    err: str | None,
) -> None:
    """Append one usage event as a JSONL line. Best-effort: any failure
    (unwritable base, encode error) is swallowed — telemetry must never turn a
    good model call into a failed one."""
    try:
        event = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "role": role,
            "provider": provider,
            "model": model,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "est_cost": est_cost,
            "ok": bool(ok),
            "err": err,
        }
        path = _path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 — telemetry is best-effort; never break a call
        return


def load_events(base: Path | None = None) -> list[dict]:
    """Read the recorded events back (tests + a later xops reader). Best-effort:
    a missing / unreadable file returns ``[]``; corrupt lines are skipped."""
    try:
        text = _path(base).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — missing/unreadable → empty, never raise
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_telemetry.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/telemetry.py tests/test_gateway_telemetry.py
git commit -m "feat(gateway): best-effort per-call usage telemetry (JSONL events)"
```

---

## Task 4: OpenAI-compatible adapter (`gateway/adapters.py`)

**Files:**
- Create: `src/clonway_cockpit/gateway/adapters.py`
- Test: `tests/test_gateway_adapter.py`

**Note on testing without network:** the adapter calls `urllib.request.urlopen`. Tests
monkeypatch `clonway_cockpit.gateway.adapters.urllib.request.urlopen` with a fake that returns a
context manager whose `.read()` yields a canned JSON body, or raises `urllib.error.HTTPError` /
`TimeoutError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_adapter.py
import io
import json
import urllib.error

import pytest

from clonway_cockpit.gateway.adapters import OpenAICompatibleAdapter
from clonway_cockpit.gateway.types import GatewayError


class _FakeResp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _patch_urlopen(monkeypatch, *, payload=None, exc=None, capture=None):
    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture["req"] = req
            capture["timeout"] = timeout
        if exc is not None:
            raise exc
        return _FakeResp(payload)

    monkeypatch.setattr(
        "clonway_cockpit.gateway.adapters.urllib.request.urlopen", fake_urlopen
    )


def test_complete_parses_text_and_usage(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "hello there"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    capture: dict = {}
    _patch_urlopen(monkeypatch, payload=payload, capture=capture)
    adapter = OpenAICompatibleAdapter("https://api.x/v1/", "sk-abc", timeout=12.0)
    comp = adapter.complete("gpt-4o-mini", [{"role": "user", "content": "hi"}], temperature=0.1)
    assert comp.text == "hello there"
    assert comp.usage.prompt_tokens == 7
    assert comp.usage.completion_tokens == 3
    # request shape: trailing slash trimmed, auth header, body carries model + params
    req = capture["req"]
    assert req.full_url == "https://api.x/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-abc"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.1
    assert capture["timeout"] == 12.0


def test_no_auth_header_when_keyless(monkeypatch):
    capture: dict = {}
    _patch_urlopen(
        monkeypatch,
        payload={"choices": [{"message": {"content": "x"}}], "usage": {}},
        capture=capture,
    )
    adapter = OpenAICompatibleAdapter("http://localhost:11434/v1", None)
    comp = adapter.complete("llama3.1", [{"role": "user", "content": "hi"}])
    assert comp.usage.prompt_tokens == 0  # missing usage tolerated → 0
    assert "Authorization" not in capture["req"].headers


def test_http_error_becomes_gateway_error(monkeypatch):
    err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b"slow down"))
    _patch_urlopen(monkeypatch, exc=err)
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="429"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])


def test_transport_error_becomes_gateway_error(monkeypatch):
    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("no route"))
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="transport"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])


def test_malformed_payload_becomes_gateway_error(monkeypatch):
    _patch_urlopen(monkeypatch, payload={"unexpected": True})
    adapter = OpenAICompatibleAdapter("https://api.x/v1", "k")
    with pytest.raises(GatewayError, match="malformed"):
        adapter.complete("m", [{"role": "user", "content": "hi"}])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.gateway.adapters`

- [ ] **Step 3: Implement the adapter (stdlib urllib, zero new dependency)**

```python
# src/clonway_cockpit/gateway/adapters.py
"""OpenAI-compatible chat-completions adapter over stdlib ``urllib`` — zero new
runtime dependency. Provider-agnostic by ``base_url``: the same adapter reaches
OpenAI, Groq/Together, a local Ollama/vLLM, or a LiteLLM proxy. Every failure
(non-2xx, transport, timeout, malformed body) becomes a ``GatewayError`` raised
to the caller — the call is NOT best-effort.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .types import Completion, GatewayError, Message, Usage


class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def complete(self, model: str, messages: list[Message], **params: object) -> Completion:
        body = {"model": model, "messages": list(messages), **params}
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions", data=data, method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 — fixed https/http API base
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200] if hasattr(exc, "read") else b""
            raise GatewayError(f"HTTP {exc.code} from {self._base_url}: {detail!r}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GatewayError(f"transport error to {self._base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GatewayError(f"non-JSON response from {self._base_url}") from exc
        return self._parse(payload)

    @staticmethod
    def _parse(payload: object) -> Completion:
        try:
            assert isinstance(payload, dict)
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
            return Completion(
                text=str(text),
                usage=Usage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                ),
            )
        except (AssertionError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(f"malformed completion payload: {exc}") from exc
```

Note: `# noqa: S310` is harmless even though `S` (flake8-bandit) is not in the selected ruff set — it documents intent and ruff ignores unselected codes (same pattern as `usage.py`'s `# noqa: BLE001`).

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_adapter.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/adapters.py tests/test_gateway_adapter.py
git commit -m "feat(gateway): OpenAI-compatible urllib adapter (zero new dep)"
```

---

## Task 5: The `Gateway` port (`gateway/gateway.py`)

**Files:**
- Create: `src/clonway_cockpit/gateway/gateway.py`
- Test: `tests/test_gateway_port.py`

**Design:** `Gateway` constructs an adapter via an injectable `adapter_factory` (default the real
one), so tests pass a fake factory and need no network. `_call` resolves the role, reads the env key,
calls the adapter, and **always** records telemetry (success and failure) in a `finally`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_port.py
import pytest

from clonway_cockpit.gateway.config import GatewayConfig
from clonway_cockpit.gateway.gateway import Gateway
from clonway_cockpit.gateway.telemetry import load_events
from clonway_cockpit.gateway.types import Completion, GatewayError, Usage

CFG = {
    "roles": {
        "chat": {
            "provider": "openai_compatible",
            "base_url": "https://api.x/v1",
            "model": "gpt-4o-mini",
            "api_key_env": "TEST_GW_KEY",
            "params": {"temperature": 0.0},
        }
    },
    "pricing": {"gpt-4o-mini": {"prompt": 0.001, "completion": 0.002}},
}


class _FakeAdapter:
    """Records construction + call args; returns a canned completion or raises."""

    last: dict = {}

    def __init__(self, base_url, api_key, *, timeout=30.0):
        _FakeAdapter.last = {"base_url": base_url, "api_key": api_key, "timeout": timeout}
        self._reply = "ok"

    def complete(self, model, messages, **params):
        _FakeAdapter.last["model"] = model
        _FakeAdapter.last["messages"] = messages
        _FakeAdapter.last["params"] = params
        return Completion(text=self._reply, usage=Usage(prompt_tokens=4, completion_tokens=6))


def _gw(tmp_path, factory=_FakeAdapter):
    return Gateway(GatewayConfig.from_dict(CFG), telemetry_base=tmp_path, adapter_factory=factory)


def test_complete_returns_text_and_records_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")
    gw = _gw(tmp_path)
    out = gw.complete([{"role": "user", "content": "hi"}], role="chat")
    assert out == "ok"
    # adapter built from the role config, key read from env, params threaded
    assert _FakeAdapter.last["base_url"] == "https://api.x/v1"
    assert _FakeAdapter.last["api_key"] == "sk-live"
    assert _FakeAdapter.last["params"]["temperature"] == 0.0
    # telemetry recorded with cost = 4/1000*0.001 + 6/1000*0.002 = 0.000016
    events = load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["ok"] is True
    assert events[0]["prompt_tokens"] == 4
    assert events[0]["est_cost"] == pytest.approx(0.000016)


def test_unknown_role_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")
    with pytest.raises(GatewayError, match="unknown role"):
        _gw(tmp_path).complete([{"role": "user", "content": "hi"}], role="ghost")


def test_missing_env_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_GW_KEY", raising=False)
    with pytest.raises(GatewayError, match="TEST_GW_KEY"):
        _gw(tmp_path).complete([{"role": "user", "content": "hi"}], role="chat")


def test_adapter_failure_raises_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Boom(_FakeAdapter):
        def complete(self, model, messages, **params):
            raise GatewayError("HTTP 500 from upstream")

    with pytest.raises(GatewayError, match="500"):
        _gw(tmp_path, factory=_Boom).complete([{"role": "user", "content": "hi"}], role="chat")
    events = load_events(tmp_path)
    assert len(events) == 1
    assert events[0]["ok"] is False
    assert events[0]["err"] == "GatewayError"
    assert events[0]["prompt_tokens"] == 0


def test_complete_structured_parses_and_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Json(_FakeAdapter):
        def complete(self, model, messages, **params):
            # server wraps JSON in prose + fences — _extract_json must cope
            txt = 'Sure!\n```json\n{"name": "Ada", "age": 36}\n```'
            return Completion(text=txt, usage=Usage(prompt_tokens=2, completion_tokens=2))

    gw = _gw(tmp_path, factory=_Json)
    schema = {"type": "object", "required": ["name", "age"]}
    out = gw.complete_structured([{"role": "user", "content": "who"}], schema, role="chat")
    assert out == {"name": "Ada", "age": 36}
    # response_format requested
    assert _FakeAdapter.last["params"].get("response_format") == {"type": "json_object"}


def test_complete_structured_missing_required_key_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Json(_FakeAdapter):
        def complete(self, model, messages, **params):
            return Completion(text='{"name": "Ada"}', usage=Usage(prompt_tokens=1, completion_tokens=1))

    schema = {"type": "object", "required": ["name", "age"]}
    with pytest.raises(GatewayError, match="age"):
        _gw(tmp_path, factory=_Json).complete_structured(
            [{"role": "user", "content": "who"}], schema, role="chat"
        )


def test_complete_structured_non_json_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GW_KEY", "sk-live")

    class _Prose(_FakeAdapter):
        def complete(self, model, messages, **params):
            return Completion(text="no json here", usage=Usage(prompt_tokens=1, completion_tokens=1))

    with pytest.raises(GatewayError, match="JSON"):
        _gw(tmp_path, factory=_Prose).complete_structured(
            [{"role": "user", "content": "who"}], {"required": []}, role="chat"
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_port.py -q`
Expected: FAIL — `ModuleNotFoundError: clonway_cockpit.gateway.gateway`

- [ ] **Step 3: Implement the `Gateway`**

```python
# src/clonway_cockpit/gateway/gateway.py
"""The model-gateway port: ``complete`` + ``complete_structured`` over an
injected role→model config, through one adapter, recording per-call telemetry.

The adapter is built via an injectable ``adapter_factory`` (default the real
OpenAI-compatible one) so consumers can swap providers and tests need no network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from .adapters import OpenAICompatibleAdapter
from .config import GatewayConfig
from .telemetry import record_call
from .types import Completion, GatewayError, Message

AdapterFactory = Callable[..., "_Adapter"]


class _Adapter:  # structural hint only — anything with this .complete works
    def complete(self, model: str, messages: list[Message], **params: object) -> Completion: ...


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        telemetry_base: Path | None = None,
        adapter_factory: AdapterFactory = OpenAICompatibleAdapter,
    ) -> None:
        self._config = config
        self._telemetry_base = telemetry_base
        self._adapter_factory = adapter_factory

    def complete(self, messages: list[Message], *, role: str) -> str:
        return self._call(list(messages), role, {}).text

    def complete_structured(
        self, messages: list[Message], schema: dict, *, role: str
    ) -> dict:
        instruction: Message = {
            "role": "system",
            "content": (
                "Respond with ONLY a single JSON object that satisfies this schema "
                f"(no prose, no code fences): {json.dumps(schema)}"
            ),
        }
        comp = self._call(
            [instruction, *messages], role, {"response_format": {"type": "json_object"}}
        )
        return _validate_required(_extract_json(comp.text), schema)

    def _call(self, messages: list[Message], role: str, extra: dict[str, object]) -> Completion:
        role_cfg = self._config.resolve(role)  # raises on unknown role
        key: str | None = None
        if role_cfg.api_key_env:
            key = os.environ.get(role_cfg.api_key_env)
            if not key:
                raise GatewayError(
                    f"env var {role_cfg.api_key_env!r} is unset for role {role!r}"
                )
        adapter = self._adapter_factory(role_cfg.base_url, key, timeout=role_cfg.timeout)
        params = {**role_cfg.params, **extra}
        comp: Completion | None = None
        ok = True
        err: str | None = None
        try:
            comp = adapter.complete(role_cfg.model, messages, **params)
            return comp
        except GatewayError as exc:
            ok = False
            err = type(exc).__name__
            raise
        finally:
            usage = comp.usage if comp is not None else None
            record_call(
                self._telemetry_base,
                role=role,
                provider=role_cfg.provider,
                model=role_cfg.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                est_cost=self._config.cost_for(role_cfg.model, usage) if usage else None,
                ok=ok,
                err=err,
            )


def _extract_json(text: str) -> object:
    """Parse a JSON object out of model text, tolerating prose / ``` fences."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise GatewayError("structured output is not valid JSON") from None


def _validate_required(obj: object, schema: dict) -> dict:
    """Lightweight, dependency-free validation: it's an object and every
    ``schema['required']`` key is present. NOT full JSON Schema."""
    if not isinstance(obj, dict):
        raise GatewayError("structured output is not a JSON object")
    for key in schema.get("required", []):
        if key not in obj:
            raise GatewayError(f"structured output missing required key: {key!r}")
    return obj
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_port.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/gateway.py tests/test_gateway_port.py
git commit -m "feat(gateway): Gateway port — complete + complete_structured + telemetry"
```

---

## Task 6: Public API (`gateway/__init__.py`)

**Files:**
- Modify: `src/clonway_cockpit/gateway/__init__.py`
- Test: `tests/test_gateway_package.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_package.py
def test_public_api_is_importable_from_package_root():
    from clonway_cockpit.gateway import (
        Completion,
        Gateway,
        GatewayConfig,
        GatewayError,
        Message,
        OpenAICompatibleAdapter,
        RoleConfig,
        Usage,
        load_events,
        record_call,
    )

    assert Gateway is not None
    assert issubclass(GatewayError, RuntimeError)
    # smoke: build a config + gateway object (no call)
    cfg = GatewayConfig.from_dict(
        {"roles": {"chat": {"provider": "openai_compatible", "base_url": "u", "model": "m"}}}
    )
    assert isinstance(Gateway(cfg), Gateway)
    assert callable(record_call) and callable(load_events)
    assert RoleConfig and Completion and Usage and Message and OpenAICompatibleAdapter
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_gateway_package.py -q`
Expected: FAIL — `ImportError: cannot import name 'Gateway' from 'clonway_cockpit.gateway'`

- [ ] **Step 3: Re-export the public API**

```python
# src/clonway_cockpit/gateway/__init__.py
"""Provider-agnostic model gateway (slice 1: port + OpenAI-compatible adapter + telemetry).

Public API::

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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_gateway_package.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clonway_cockpit/gateway/__init__.py tests/test_gateway_package.py
git commit -m "feat(gateway): re-export public API from package root"
```

---

## Task 7: Smoke driver + usage doc

**Files:**
- Create: `scripts/gateway_smoke.py`
- Create: `docs/model-gateway.md`

This task has no unit test — `scripts/gateway_smoke.py` is the *watched-working* driver run by hand
in Task 8. Keep it import-safe (no work at import time) so it can't break collection.

- [ ] **Step 1: Write the smoke driver**

```python
# scripts/gateway_smoke.py
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
```

- [ ] **Step 2: Verify it imports cleanly (no real call)**

Run: `uv run python -c "import importlib.util, pathlib; importlib.util.spec_from_file_location('s', 'scripts/gateway_smoke.py')"`
Expected: no output, exit 0. (Full run is Task 8.)

- [ ] **Step 3: Write the usage doc**

```markdown
# Using the model gateway

`clonway_cockpit.gateway` is a thin, provider-agnostic seam for model calls. The
framework hardcodes no provider and stores no key; a consumer injects a config.

## Construct

​```python
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
​```

The config is a **plain dict** — store it as YAML/JSON/TOML and parse it however
you like; the framework adds no config-format dependency. API keys come from the
**named env var**, never the config.

## Call

​```python
text = gw.complete([{"role": "user", "content": "cash position?"}], role="chat")

schema = {"type": "object", "required": ["summary", "amount"]}
obj = gw.complete_structured([{"role": "user", "content": "summarise"}], schema, role="chat")
​```

`role` selects the model. Failures raise `GatewayError`. `complete_structured`
parses JSON from the reply and checks the `required` keys are present (lightweight
— not full JSON Schema).

## Telemetry

Every call appends one event to `<telemetry_base>/model_usage.jsonl`
(`ts, role, provider, model, prompt_tokens, completion_tokens, est_cost, ok, err`).
It is best-effort and never breaks a call. This is the per-call model-spend stream
a later slice surfaces in xops.

## Scope (slice 1)

One OpenAI-compatible adapter (works against OpenAI, Groq/Together, local
Ollama/vLLM, or a LiteLLM proxy via `base_url`). Cost caps, a circuit-breaker, and
LiteLLM/Anthropic adapters are later slices.
```

(Remove the zero-width `​` characters around the code fences — they are only here to nest the block in this plan.)

- [ ] **Step 4: Commit**

```bash
git add scripts/gateway_smoke.py docs/model-gateway.md
git commit -m "docs(gateway): smoke driver + usage note"
```

---

## Task 8: Watched-working proof (the acceptance)

**No new files.** This is the verify-before-claiming step: a real call, watched, output captured.

- [ ] **Step 1: Confirm an endpoint** (build-time logistics — ask the owner if unknown). Cheapest:
  local Ollama (`ollama serve`; `ollama pull llama3.1`; no key) or OpenAI `gpt-4o-mini` (needs
  `OPENAI_API_KEY`).

- [ ] **Step 2: Run the smoke driver against the real endpoint**

Local Ollama:
```bash
GATEWAY_BASE_URL=http://localhost:11434/v1 GATEWAY_MODEL=llama3.1 \
    uv run python scripts/gateway_smoke.py
```
OpenAI:
```bash
GATEWAY_BASE_URL=https://api.openai.com/v1 GATEWAY_MODEL=gpt-4o-mini \
    GATEWAY_API_KEY_ENV=OPENAI_API_KEY uv run python scripts/gateway_smoke.py
```
Expected: a printed reply AND a `telemetry record: {...}` line with non-zero `prompt_tokens` /
`completion_tokens`. Capture this output verbatim for the PR body.

- [ ] **Step 3: Confirm the telemetry file**

Run: `cat .cockpit/model_usage.jsonl`
Expected: at least one JSONL event with `"ok": true` and token counts.

- [ ] **Step 4: Do NOT commit `.cockpit/`** — it is gitignored state. Confirm `git status` is clean
  of it (`.cockpit/` should not appear, or add it to `.gitignore` if missing).

---

## Final gate (before opening the PR)

- [ ] `uv run ruff check .` → All checks passed
- [ ] `uv run ruff format --check .` → all files formatted (run `uv run ruff format .` if not)
- [ ] `uv run mypy src` → Success, no issues (22 + new files)
- [ ] `uv run pytest -q` → all green (452 existing + ~22 new)
- [ ] Confirm **no new runtime dependency** in `pyproject.toml` (`dependencies` still `["rich>=15.0.0"]`)

Ship with the `ship-pr` skill. The PR body's Test plan MUST paste the Task 8 watched-working output
(the real reply + the telemetry record) — that is the slice's acceptance evidence.

---

## Self-review (plan ↔ spec)

- **Port (`complete`/`complete_structured`, role→model, injected, no baked secret):** Tasks 5, 6. ✓
- **OpenAI-compatible adapter, stdlib urllib, provider-agnostic via base_url, typed errors:** Task 4. ✓
- **Config: plain dict, env-var keys, pricing, validation, unsupported-provider rejected:** Task 2. ✓
- **Telemetry: best-effort never-crash JSONL events, ok:false on failure, injectable base:** Tasks 3, 5. ✓
- **Zero new runtime dependency; future adapters behind extras:** stdlib-only across all tasks; final gate asserts `dependencies` unchanged. ✓
- **Lightweight structured validation (required-keys, not JSON Schema):** Task 5 `_validate_required`. ✓
- **Watched-working real call + telemetry record:** Tasks 7–8. ✓
- **Docs in the same PR (spec already committed + usage note):** Task 7. ✓
- **Not in scope (caps/breaker, LiteLLM/Anthropic adapters, xops surfacing, call-site migration):** absent from all tasks by design. ✓

Type consistency check: `Completion.text`/`.usage`, `Usage.prompt_tokens`/`.completion_tokens`,
`GatewayConfig.from_dict`/`.resolve`/`.cost_for`, `RoleConfig.{provider,base_url,model,api_key_env,params,timeout}`,
`record_call(base, *, role, provider, model, prompt_tokens, completion_tokens, est_cost, ok, err)`,
`load_events(base)`, `Gateway(config, *, telemetry_base, adapter_factory)` — names match across Tasks 1–8. ✓
