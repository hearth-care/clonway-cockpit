from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .resolve import CredentialsUnavailable, RefreshLockTimeout
from .store import TokenStore


def refresh_if_needed(
    creds: Any,
    *,
    store: TokenStore,
    key: str,
    scopes: tuple[str, ...],
    lock_dir: Path | None = None,
    timeout_seconds: float = 30.0,
    credential_factory: Callable[[dict[str, Any], tuple[str, ...]], Any] | None = None,
    request_factory: Callable[[], Any] | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    if getattr(creds, "valid", False) and not getattr(creds, "expired", False):
        return creds
    if not getattr(creds, "refresh_token", None):
        raise CredentialsUnavailable(
            f"Google credentials for {key} cannot be refreshed.",
            remedy=f"Re-auth {key} with an interactive Google OAuth consent flow.",
        )

    lock_root = lock_dir or Path(tempfile.gettempdir()) / "clonway-google-auth-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"{_safe_lock_name(key)}.lock"
    with _locked(lock_path, timeout_seconds=timeout_seconds):
        latest = store.load(key)
        if latest is not None:
            factory = credential_factory or _default_user_credentials_factory
            latest_creds = factory(latest, scopes)
            if getattr(latest_creds, "valid", False) and not getattr(
                latest_creds, "expired", False
            ):
                return latest_creds

        try:
            creds.refresh((request_factory or _default_request_factory)())
        except Exception as exc:
            raise CredentialsUnavailable(
                f"Google credentials for {key} could not be refreshed.",
                remedy=f"Re-auth {key} with an interactive Google OAuth consent flow.",
            ) from exc
        token = _token_dict(creds)
        store.save(key, token)
        if on_event is not None:
            on_event("token.refreshed", {"key": key, "scopes": list(scopes)})
        return creds


@contextlib.contextmanager
def _locked(lock_path: Path, *, timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("w") as lock_fh:
        while True:
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RefreshLockTimeout(
                        f"Timed out waiting for Google token refresh lock {lock_path.name}",
                        remedy="Retry after the in-flight token refresh completes.",
                    ) from exc
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _token_dict(creds: Any) -> dict[str, Any]:
    raw = creds.to_json()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise CredentialsUnavailable("Refreshed Google credentials did not serialize as JSON")
    return parsed


def _default_user_credentials_factory(info: dict[str, Any], scopes: tuple[str, ...]) -> Any:
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-auth is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return Credentials.from_authorized_user_info(info, scopes=list(scopes))


def _default_request_factory() -> Any:
    try:
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-auth is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return Request()


def _safe_lock_name(key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in key)
