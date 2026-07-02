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
from typing import Any
from urllib import request as urlrequest

from .chat_transport import ChatRouter, ack_response

CHAT_EVENTS_PATH = "/chat-events"
MAX_BODY_BYTES = 1_048_576

StartResponse = Callable[[str, list[tuple[str, str]]], None]
WsgiApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]
Opener = Callable[..., Any]


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

        background(lambda: _run_content_free(lambda: router.handle_event(event)))
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
