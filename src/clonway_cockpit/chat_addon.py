"""Google Chat Workspace add-on edge for the persona chat transport.

This module is the stdlib-only deployable HTTP edge. It stays downstream of
``chat_transport``: request parsing and fast ack live here; normalization,
operator gating, routing, and mark-after-delivery semantics stay in the core.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from .chat_transport import ChatRouter, ack_response

CHAT_EVENTS_PATH = "/chat-events"
MAX_BODY_BYTES = 1_048_576

StartResponse = Callable[[str, list[tuple[str, str]]], None]
WsgiApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]


def run_inline(fn: Callable[[], None]) -> None:
    fn()


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

        background(lambda: router.handle_event(event))
        body = json.dumps(ack_response()).encode("utf-8")
        return _response(start_response, "200 OK", body, content_type="application/json")

    return app


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
