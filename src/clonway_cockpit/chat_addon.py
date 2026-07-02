"""Google Chat Workspace add-on edge for the persona chat transport.

This module is the stdlib-only deployable HTTP edge. It stays downstream of
``chat_transport``: request parsing and fast ack live here; normalization,
operator gating, routing, and mark-after-delivery semantics stay in the core.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TextIO
from urllib import request as urlrequest
from wsgiref.simple_server import make_server
from wsgiref.types import StartResponse, WSGIApplication

from .chat_memory import remembering_responder
from .chat_transport import ChatRouter, ack_response, load_allowlist
from .colleague import Colleague, ColleagueRegistry, Completer, gateway_responder, load_colleagues
from .gateway import Gateway, GatewayConfig
from .gateway.types import Message
from .group_chat import FakeChatTransport
from .persona import Persona, PersonaRegistry

CHAT_EVENTS_PATH = "/chat-events"
MAX_BODY_BYTES = 1_048_576
CLONWAY_CHAT_MEMORY_DIR = "CLONWAY_CHAT_MEMORY_DIR"

WsgiApp = WSGIApplication
Opener = Callable[..., Any]


class ChatAddonConfigError(RuntimeError):
    pass


class EchoCompleter:
    def complete(self, messages: list[Message], *, role: str) -> str:
        return f"[{len(messages)} msgs] {messages[-1]['content']}"


class FileSeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._seen = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
        except FileNotFoundError:
            self._seen = set()

    def __contains__(self, item: str) -> bool:
        return item in self._seen

    def add(self, item: str) -> None:
        if item in self._seen:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"{item}\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._seen.add(item)


class RestChatTransport:
    def __init__(
        self,
        token_supplier: Callable[[], str],
        base_url: str = "https://chat.googleapis.com/v1",
        timeout: float = 10.0,
        opener: Opener = urlrequest.urlopen,
    ) -> None:
        self._token_supplier = token_supplier
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = opener

    def post(self, space: str, text: str) -> None:
        body = json.dumps({"text": text}).encode("utf-8")
        req = urlrequest.Request(
            f"{self._base_url}/{space}/messages",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token_supplier()}",
                "Content-Type": "application/json",
            },
        )
        with self._opener(req, timeout=self._timeout) as response:
            status = int(response.getcode())
            if status < 200 or status >= 300:
                raise RuntimeError(f"Google Chat post failed with HTTP {status}")

    def iter_messages(self, space: str) -> Iterable[Any]:
        return iter(())


def metadata_token_supplier(
    *,
    opener: Opener = urlrequest.urlopen,
    timeout: float = 10.0,
) -> str:
    req = urlrequest.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with opener(req, timeout=timeout) as response:
        status = int(response.getcode())
        if status < 200 or status >= 300:
            raise RuntimeError(f"metadata token request failed with HTTP {status}")
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("metadata token response missing access_token")
    return token


def run_inline(fn: Callable[[], None]) -> None:
    fn()


def spawn_daemon_thread(fn: Callable[[], None]) -> None:
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()


def _run_content_free(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - background edge must keep ack path alive.
        print(f"chat_addon background handler failed: {type(exc).__name__}", file=sys.stderr)


def _response(
    start_response: StartResponse,
    status: str,
    body: bytes,
    *,
    content_type: str = "text/plain",
) -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def build_addon_app(
    router: ChatRouter,
    *,
    background: Callable[[Callable[[], None]], None],
    max_body: int = MAX_BODY_BYTES,
) -> WsgiApp:
    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", ""))
        path = str(environ.get("PATH_INFO", ""))
        if path == "/healthz" and method == "GET":
            return _response(start_response, "200 OK", b"ok")
        if path != CHAT_EVENTS_PATH:
            return _response(start_response, "404 Not Found", b"not found")
        if method != "POST":
            return _response(start_response, "405 Method Not Allowed", b"method not allowed")

        try:
            length = int(str(environ.get("CONTENT_LENGTH", "")))
        except ValueError:
            return _response(start_response, "400 Bad Request", b"bad request")
        if length < 0:
            return _response(start_response, "400 Bad Request", b"bad request")
        if length > max_body:
            return _response(start_response, "413 Payload Too Large", b"payload too large")

        try:
            payload = environ["wsgi.input"].read(length)
            event = json.loads(payload.decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            return _response(start_response, "400 Bad Request", b"bad request")

        def handle() -> None:
            router.handle_event(event)

        background(lambda: _run_content_free(handle))
        body = json.dumps(ack_response()).encode("utf-8")
        return _response(start_response, "200 OK", body, content_type="application/json")

    return app


def build_responder(
    colleagues: ColleagueRegistry,
    completer: Completer,
    *,
    role: str,
    memory_dir: Path | None,
) -> Callable[[Persona, Any], str | None]:
    if memory_dir is None:
        return gateway_responder(colleagues, completer, role=role)
    return remembering_responder(colleagues, completer, role=role, memory_base=memory_dir)


def build_serve_app(environ: dict[str, str]) -> WsgiApp:
    try:
        personas_dir = Path(environ["CLONWAY_CHAT_PERSONAS_DIR"])
        souls_dir = Path(environ["CLONWAY_CHAT_SOULS_DIR"])
        gateway_config_path = Path(environ["CLONWAY_CHAT_GATEWAY_CONFIG"])
    except KeyError as exc:
        raise ChatAddonConfigError(f"missing required env var: {exc.args[0]}") from exc

    colleagues = load_colleagues(personas_dir, souls_dir)
    gateway_config = GatewayConfig.from_dict(
        json.loads(gateway_config_path.read_text(encoding="utf-8"))
    )
    gateway = Gateway(gateway_config)
    role = environ.get("CLONWAY_CHAT_ROLE", "chat")
    problems = gateway.validate(roles=[role])
    if problems:
        raise ChatAddonConfigError("; ".join(problems))
    memory_dir = (
        Path(environ[CLONWAY_CHAT_MEMORY_DIR]) if environ.get(CLONWAY_CHAT_MEMORY_DIR) else None
    )
    seen = FileSeenStore(Path(environ.get("CLONWAY_CHAT_SEEN_FILE", ".cockpit/chat-seen.txt")))
    router = ChatRouter(
        registry=colleagues.registry,
        responder=build_responder(colleagues, gateway, role=role, memory_dir=memory_dir),
        transport=RestChatTransport(token_supplier=metadata_token_supplier),
        allowlist=load_allowlist(),
        already_handled=seen.__contains__,
        mark_handled=seen.add,
    )
    return build_addon_app(router, background=spawn_daemon_thread)


def run_fake(
    lines: Iterable[str], *, output: TextIO | None = None, memory_dir: Path | None = None
) -> list[str]:
    persona = Persona.from_dict({"handle": "demo", "name": "Demo", "domain": "local dev"})
    transport = FakeChatTransport()

    def echo(persona: Persona, message) -> str:
        return f"{persona.name}: {message.text}"

    responder: Callable[[Persona, Any], str | None]
    if memory_dir is None:
        registry = PersonaRegistry.from_personas([persona])
        responder = echo
    else:
        colleagues = ColleagueRegistry(
            colleagues={"demo": Colleague(persona=persona, soul="You are Demo.")}
        )
        registry = colleagues.registry
        responder = remembering_responder(
            colleagues, EchoCompleter(), role="chat", memory_base=memory_dir
        )

    router = ChatRouter(
        registry=registry,
        responder=responder,
        transport=transport,
        allowlist=frozenset({"owner@clonway.example"}),
    )
    app = build_addon_app(router, background=run_inline)
    replies: list[str] = []

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: object = None,
    ) -> Callable[[bytes], object]:
        return lambda data: None

    for line in lines:
        text = line.strip()
        if not text:
            continue
        before = len(transport.posted)
        body = json.dumps(fake_dm_envelope(text)).encode("utf-8")
        env = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": CHAT_EVENTS_PATH,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": _BytesInput(body),
        }
        app(env, start_response)
        for space, reply in transport.posted[before:]:
            rendered = f"{space}: {reply}"
            replies.append(rendered)
            if output is not None:
                print(rendered, file=output)
    return replies


class _BytesInput:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body)
        out = self._body[:size]
        self._body = self._body[size:]
        return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--fake", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--memory-dir", type=Path)
    args = parser.parse_args(argv)

    if args.fake:
        run_fake(sys.stdin, output=sys.stdout, memory_dir=args.memory_dir)
        return 0

    app = build_serve_app(dict(os.environ))
    port = args.port or int(os.environ.get("PORT", "8080"))
    with make_server("", port, app) as httpd:
        httpd.serve_forever()
    return 0


def fake_dm_envelope(
    text: str,
    *,
    email: str = "owner@clonway.example",
    space_id: str = "spaces/LOCAL",
    space_type: str = "DM",
    msg_id: str = "spaces/LOCAL/messages/local-1",
) -> dict[str, object]:
    return {
        "chat": {
            "messagePayload": {
                "message": {
                    "name": msg_id,
                    "text": text,
                    "sender": {"name": "users/local", "email": email, "displayName": "Owner"},
                },
                "space": {"name": space_id, "type": space_type},
                "user": {"name": "users/local", "email": email, "displayName": "Owner"},
            }
        },
        "commonEventObject": {},
    }


if __name__ == "__main__":
    raise SystemExit(main())
