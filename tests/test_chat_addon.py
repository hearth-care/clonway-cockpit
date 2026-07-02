import io
import json
import os
import threading
import time
from urllib.error import URLError

import pytest

from clonway_cockpit.chat_addon import (
    CHAT_EVENTS_PATH,
    ChatAddonConfigError,
    FileSeenStore,
    MAX_BODY_BYTES,
    RestChatTransport,
    build_serve_app,
    build_addon_app,
    fake_dm_envelope,
    metadata_token_supplier,
    run_fake,
    run_inline,
    spawn_daemon_thread,
)
from clonway_cockpit.chat_transport import (
    ADDED_TO_SPACE,
    CARD_CLICKED,
    MESSAGE,
    REMOVED_FROM_SPACE,
    ChatRouter,
    normalize_event,
    parse_allowlist,
)
from clonway_cockpit.group_chat import FakeChatTransport
from clonway_cockpit.persona import Persona, PersonaRegistry


def _milo() -> Persona:
    return Persona.from_dict(
        {"handle": "milo", "name": "Milo", "domain": "the books - invoicing, payroll, cash"}
    )


def _quill() -> Persona:
    return Persona.from_dict(
        {"handle": "quill", "name": "Quill", "domain": "the front desk and the diary"}
    )


def _stub_responder(persona: Persona, message) -> str:
    return f"{persona.name}: on it."


def _make_app(
    transport: FakeChatTransport,
    *,
    background=run_inline,
    personas: list[Persona] | None = None,
    responder=_stub_responder,
    **router_kw,
):
    router = ChatRouter(
        registry=PersonaRegistry.from_personas(personas or [_milo()]),
        responder=responder,
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


def _post(app, envelope: object) -> tuple[str, bytes]:
    return _call(app, "POST", CHAT_EVENTS_PATH, json.dumps(envelope).encode("utf-8"))


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


def test_owner_dm_is_acked_and_reply_posted():
    transport = FakeChatTransport()
    app = _make_app(transport)
    status, out = _post(app, fake_dm_envelope("reconcile the bank?"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]


def test_non_operator_dm_is_acked_but_draws_no_reply():
    transport = FakeChatTransport()
    app = _make_app(transport)
    status, out = _post(app, fake_dm_envelope("pay everyone now", email="evil@x.com"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == []


def test_room_message_routes_by_self_selection():
    transport = FakeChatTransport()
    app = _make_app(transport, personas=[_milo(), _quill()])
    status, out = _post(app, fake_dm_envelope("what is payroll status?", space_type="ROOM"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]


@pytest.mark.parametrize(
    ("payload_key", "kind"),
    [
        ("addedToSpacePayload", ADDED_TO_SPACE),
        ("removedFromSpacePayload", REMOVED_FROM_SPACE),
        ("buttonClickedPayload", CARD_CLICKED),
    ],
)
def test_event_kind_matrix(payload_key, kind):
    calls: list[str] = []

    def responder(persona: Persona, message) -> str:
        calls.append(persona.handle)
        return f"{persona.name}: no"

    transport = FakeChatTransport()
    app = _make_app(transport, responder=responder)
    status, out = _post(
        app,
        {"chat": {payload_key: {"space": {"name": "spaces/LOCAL", "type": "DM"}}}},
    )
    assert normalize_event({"chat": {payload_key: {}}}).kind == kind
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == []
    assert calls == []


@pytest.mark.parametrize("envelope", [{}, {"chat": {}}, {"chat": "nope"}, [1, 2]])
def test_unknown_envelope_is_acked_not_5xx(envelope):
    transport = FakeChatTransport()
    app = _make_app(transport)
    status, out = _post(app, envelope)
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == []


def test_redelivery_is_deduped_through_the_edge():
    seen: set[str] = set()
    transport = FakeChatTransport()
    app = _make_app(transport, already_handled=seen.__contains__, mark_handled=seen.add)
    envelope = fake_dm_envelope("reconcile the bank?")
    assert _post(app, envelope)[0] == "200 OK"
    assert _post(app, envelope)[0] == "200 OK"
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]
    assert seen == {"spaces/LOCAL/messages/local-1"}


def test_background_failure_leaves_event_unmarked():
    seen: set[str] = set()

    def raising_responder(persona: Persona, message) -> str:
        raise RuntimeError("boom")

    def swallow(fn):
        try:
            fn()
        except RuntimeError:
            pass

    app = _make_app(
        FakeChatTransport(),
        background=swallow,
        responder=raising_responder,
        already_handled=seen.__contains__,
        mark_handled=seen.add,
    )
    status, out = _post(app, fake_dm_envelope("reconcile"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert seen == set()


def test_fast_ack_returns_before_responder_completes():
    started = threading.Event()
    release = threading.Event()
    transport = FakeChatTransport()

    def blocking_responder(persona: Persona, message) -> str:
        started.set()
        release.wait(timeout=5)
        return f"{persona.name}: released"

    app = _make_app(transport, background=spawn_daemon_thread, responder=blocking_responder)
    status, out = _post(app, fake_dm_envelope("reconcile"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert started.wait(timeout=1)
    assert transport.posted == []
    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not transport.posted:
        time.sleep(0.01)
    assert transport.posted == [("spaces/LOCAL", "Milo: released")]


def test_no_auth_header_required_iam_model():
    transport = FakeChatTransport()
    app = _make_app(transport)
    status, out = _post(app, fake_dm_envelope("reconcile"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]


def test_edge_logging_is_content_free(capsys):
    def raising_responder(persona: Persona, message) -> str:
        raise RuntimeError("provider unavailable")

    app = _make_app(FakeChatTransport(), responder=raising_responder)
    status, out = _post(app, fake_dm_envelope("reconcile", email="owner@clonway.example"))
    assert status == "200 OK"
    assert json.loads(out) == {}
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "reconcile" not in output
    assert "owner@clonway.example" not in output
    assert "spaces/" not in output


def test_seen_store_survives_restart(tmp_path):
    seen_path = tmp_path / "seen.txt"
    store = FileSeenStore(seen_path)
    transport = FakeChatTransport()
    app = _make_app(
        transport,
        already_handled=store.__contains__,
        mark_handled=store.add,
    )
    envelope = fake_dm_envelope("reconcile the bank?")
    assert _post(app, envelope)[0] == "200 OK"
    assert transport.posted == [("spaces/LOCAL", "Milo: on it.")]

    restarted = FileSeenStore(seen_path)
    restarted_transport = FakeChatTransport()
    restarted_app = _make_app(
        restarted_transport,
        already_handled=restarted.__contains__,
        mark_handled=restarted.add,
    )
    assert _post(restarted_app, envelope)[0] == "200 OK"
    assert restarted_transport.posted == []


def test_seen_store_tolerates_missing_file(tmp_path):
    store = FileSeenStore(tmp_path / "missing" / "seen.txt")
    assert "spaces/LOCAL/messages/local-1" not in store


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


def test_rest_transport_posts_message_create():
    requests = []

    def fake_opener(request, timeout):
        requests.append((request, timeout))
        return _FakeResponse(status=200)

    transport = RestChatTransport(token_supplier=lambda: "tok", opener=fake_opener)
    transport.post("spaces/AAA", "hi")

    request, timeout = requests[0]
    assert request.full_url == "https://chat.googleapis.com/v1/spaces/AAA/messages"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tok"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {"text": "hi"}
    assert timeout == 10.0


@pytest.mark.parametrize(
    "opener",
    [
        lambda request, timeout: _FakeResponse(status=500),
        lambda request, timeout: (_ for _ in ()).throw(URLError("down")),
    ],
)
def test_rest_transport_error_propagates(opener):
    transport = RestChatTransport(token_supplier=lambda: "tok", opener=opener)
    with pytest.raises(Exception):
        transport.post("spaces/AAA", "hi")


def test_rest_transport_iter_messages_is_empty():
    transport = RestChatTransport(token_supplier=lambda: "tok")
    assert list(transport.iter_messages("spaces/AAA")) == []


def test_metadata_token_supplier_shape():
    requests = []

    def fake_opener(request, timeout):
        requests.append((request, timeout))
        return _FakeResponse(status=200, body=b'{"access_token": "ya29.token"}')

    assert metadata_token_supplier(opener=fake_opener) == "ya29.token"
    request, timeout = requests[0]
    assert (
        request.full_url
        == "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    )
    assert request.get_header("Metadata-flavor") == "Google"
    assert timeout == 10.0


def test_build_serve_app_wires_env_to_app(tmp_path, monkeypatch):
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "roles": {
                    "chat": {
                        "provider": "openai_compatible",
                        "model": "m",
                        "base_url": "http://localhost:1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLONWAY_CHAT_PERSONAS_DIR", "examples/personas")
    monkeypatch.setenv("CLONWAY_CHAT_SOULS_DIR", "examples/souls")
    monkeypatch.setenv("CLONWAY_CHAT_GATEWAY_CONFIG", str(config))
    monkeypatch.setenv("CLONWAY_CHAT_OPERATORS", "owner@clonway.example")
    monkeypatch.setenv("CLONWAY_CHAT_SEEN_FILE", str(tmp_path / "seen.txt"))

    app = build_serve_app(dict(os.environ))
    assert _call(app, "GET", "/healthz")[0] == "200 OK"
    status, out = _post(app, fake_dm_envelope("pay everyone now", email="evil@x.com"))
    assert status == "200 OK"
    assert json.loads(out) == {}


def test_build_serve_app_fail_closed_on_gateway_problems(tmp_path, monkeypatch):
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "roles": {
                    "chat": {
                        "provider": "openai_compatible",
                        "model": "m",
                        "base_url": "http://localhost:1",
                        "api_key_env": "MISSING_CHAT_KEY",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLONWAY_CHAT_PERSONAS_DIR", "examples/personas")
    monkeypatch.setenv("CLONWAY_CHAT_SOULS_DIR", "examples/souls")
    monkeypatch.setenv("CLONWAY_CHAT_GATEWAY_CONFIG", str(config))
    monkeypatch.delenv("MISSING_CHAT_KEY", raising=False)
    with pytest.raises(ChatAddonConfigError, match="MISSING_CHAT_KEY"):
        build_serve_app(dict(os.environ))


def test_run_fake_repl_round_trip():
    replies = run_fake(["hi demo"])
    assert replies == ["spaces/LOCAL: Demo: hi demo"]
