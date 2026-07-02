import io
import json

from clonway_cockpit.chat_addon import (
    CHAT_EVENTS_PATH,
    MAX_BODY_BYTES,
    build_addon_app,
    fake_dm_envelope,
    run_inline,
)
from clonway_cockpit.chat_transport import MESSAGE, ChatRouter, normalize_event, parse_allowlist
from clonway_cockpit.group_chat import FakeChatTransport
from clonway_cockpit.persona import Persona, PersonaRegistry


def _milo() -> Persona:
    return Persona.from_dict(
        {"handle": "milo", "name": "Milo", "domain": "the books - invoicing, payroll, cash"}
    )


def _stub_responder(persona: Persona, message) -> str:
    return f"{persona.name}: on it."


def _make_app(transport: FakeChatTransport, *, background=run_inline, **router_kw):
    router = ChatRouter(
        registry=PersonaRegistry.from_personas([_milo()]),
        responder=_stub_responder,
        transport=transport,
        allowlist=parse_allowlist("owner@clonway.example"),
        **router_kw,
    )
    return build_addon_app(router, background=background)


def _call(app, method: str, path: str, body: bytes = b"") -> tuple[str, bytes]:
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status

    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    out = b"".join(app(env, start_response))
    return captured["status"], out


def test_fake_envelope_is_on_contract_with_the_core_normaliser():
    assert normalize_event(fake_dm_envelope("x")).kind == MESSAGE


def test_routing_edge_states():
    app = _make_app(FakeChatTransport())
    assert _call(app, "GET", "/healthz")[0] == "200 OK"
    assert _call(app, "GET", CHAT_EVENTS_PATH)[0] == "405 Method Not Allowed"
    assert _call(app, "POST", "/nope", b"{}")[0] == "404 Not Found"
    assert _call(app, "POST", CHAT_EVENTS_PATH, b"{not json")[0] == "400 Bad Request"


def test_oversized_body_is_rejected_without_reading():
    app = _make_app(FakeChatTransport())
    big = b"x" * (MAX_BODY_BYTES + 1)
    assert _call(app, "POST", CHAT_EVENTS_PATH, big)[0] == "413 Payload Too Large"
