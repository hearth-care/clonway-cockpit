from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from .resolve import CredentialsUnavailable


def sa_credentials(
    info: dict[str, Any],
    scopes: tuple[str, ...] | list[str],
    *,
    subject: str | None = None,
    credentials_class: Any | None = None,
) -> Any:
    credentials = credentials_class or _service_account_credentials_class()
    return credentials.from_service_account_info(
        info,
        scopes=list(scopes),
        subject=subject,
    )


def build_service(
    api: str,
    version: str,
    creds: Any,
    *,
    builder: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> Any:
    service_builder = builder or _discovery_builder()
    kwargs.setdefault("cache_discovery", False)
    return service_builder(api, version, credentials=creds, **kwargs)


def _service_account_credentials_class() -> Any:
    try:
        service_account = importlib.import_module("google.oauth2.service_account")
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-auth is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return service_account.Credentials


def _discovery_builder() -> Callable[..., Any]:
    try:
        discovery = importlib.import_module("googleapiclient.discovery")
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-api-python-client is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return discovery.build
