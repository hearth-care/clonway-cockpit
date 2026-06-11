from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .store import TokenStore, default_store


class GoogleAuthError(Exception):
    """Base class for Google auth failures."""


class CredentialsUnavailable(GoogleAuthError):
    """Raised when credentials cannot be resolved without operator action."""

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.remedy = remedy or message


class ScopeMismatch(CredentialsUnavailable):
    """Raised when a stored token does not grant the declared scope set."""


class RefreshLockTimeout(CredentialsUnavailable):
    """Raised when a refresh lock cannot be acquired in time."""


@dataclass(frozen=True)
class CredentialSpec:
    worker_id: str
    key: str
    scopes: tuple[str, ...]
    sa_info_env: str | None = None
    subject: str | None = None
    client_config_env: str | None = None
    injected_credentials: Any | None = None
    allow_interactive: bool = False

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise CredentialsUnavailable("worker_id is required")
        if not self.key.strip():
            raise CredentialsUnavailable("credential key is required")
        if not self.scopes:
            raise CredentialsUnavailable("declared scopes are required")


def resolve_credentials(
    spec: CredentialSpec,
    *,
    store: TokenStore | None = None,
    env: Mapping[str, str] | None = None,
    user_credentials_factory: Callable[[dict[str, Any], tuple[str, ...]], Any] | None = None,
    service_account_factory: (
        Callable[[dict[str, Any], tuple[str, ...], str | None], Any] | None
    ) = None,
    interactive_flow: Callable[[CredentialSpec], Any] | None = None,
    refresh_func: Callable[..., Any] | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    """Resolve Google credentials in the fleet-wide order:

    1. Injected credentials object.
    2. Service-account info from the configured environment variable, with optional DWD subject.
    3. Stored user token, refreshed by the refresh layer if needed.
    4. Interactive installed-app flow when explicitly allowed, else a remedy-bearing error.
    """
    runtime_env = env if env is not None else os.environ
    if spec.injected_credentials is not None:
        _emit(on_event, "credentials.injected", spec)
        return spec.injected_credentials

    if spec.sa_info_env:
        raw = runtime_env.get(spec.sa_info_env, "").strip()
        if raw:
            info = _load_json_object(raw, source=f"${spec.sa_info_env}")
            factory = service_account_factory or _default_service_account_factory
            creds = factory(info, spec.scopes, spec.subject)
            _emit(on_event, "credentials.service_account", spec)
            return creds

    token_store = store or default_store(
        spec.worker_id,
        base_dir_env=f"{spec.worker_id.upper()}_STATE_ROOT",
    )
    token = token_store.load(spec.key)
    if token is not None:
        missing_scopes = _missing_scopes(token, spec.scopes)
        if not missing_scopes:
            factory = user_credentials_factory or _default_user_credentials_factory
            creds = factory(token, spec.scopes)
            if getattr(creds, "expired", False) or not getattr(creds, "valid", True):
                refresher = refresh_func or _default_refresh_if_needed
                creds = refresher(creds, store=token_store, key=spec.key, scopes=spec.scopes)
            _emit(on_event, "credentials.stored", spec)
            return creds
        if not spec.allow_interactive:
            missing = ", ".join(sorted(missing_scopes))
            raise ScopeMismatch(
                f"Stored Google token for {spec.worker_id}/{spec.key} is missing scope(s): "
                f"{missing}",
                remedy=(
                    "Run an interactive Google OAuth consent flow for "
                    f"{spec.worker_id}/{spec.key} with the declared scopes."
                ),
            )

    if spec.allow_interactive:
        if not spec.client_config_env:
            raise CredentialsUnavailable(
                f"No client_config_env is configured for {spec.worker_id}/{spec.key}.",
                remedy="Set a client_config_env or provide service-account credentials.",
            )
        if not runtime_env.get(spec.client_config_env, "").strip():
            raise CredentialsUnavailable(
                f"${spec.client_config_env} is not set for {spec.worker_id}/{spec.key}.",
                remedy=(
                    f"Set ${spec.client_config_env} to installed-app client JSON, "
                    "or provide service-account credentials."
                ),
            )
        flow = interactive_flow or _default_interactive_flow
        creds = flow(spec)
        _emit(on_event, "flow.completed", spec)
        return creds

    raise CredentialsUnavailable(
        f"Google credentials unavailable for {spec.worker_id}/{spec.key}.",
        remedy=(
            "Run an interactive Google OAuth consent flow for "
            f"{spec.worker_id}/{spec.key}, set a service-account env var, "
            "or inject credentials in tests."
        ),
    )


def _missing_scopes(token: Mapping[str, Any], required: tuple[str, ...]) -> set[str]:
    granted_raw = token.get("scopes", [])
    if isinstance(granted_raw, str):
        granted = set(granted_raw.split())
    else:
        granted = {str(scope) for scope in granted_raw}
    return set(required) - granted


def _load_json_object(raw: str, *, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialsUnavailable(f"{source} does not contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise CredentialsUnavailable(f"{source} must contain a JSON object")
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


def _default_service_account_factory(
    info: dict[str, Any], scopes: tuple[str, ...], subject: str | None
) -> Any:
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-auth is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=list(scopes),
        subject=subject,
    )


def _default_interactive_flow(spec: CredentialSpec) -> Any:
    from .flow import run_interactive_flow

    return run_interactive_flow(spec)


def _default_refresh_if_needed(creds: Any, **kwargs: Any) -> Any:
    from .refresh import refresh_if_needed

    return refresh_if_needed(creds, **kwargs)


def _emit(
    on_event: Callable[[str, dict[str, Any]], None] | None,
    event: str,
    spec: CredentialSpec,
) -> None:
    if on_event is None:
        return
    on_event(event, {"worker_id": spec.worker_id, "key": spec.key, "scopes": list(spec.scopes)})
