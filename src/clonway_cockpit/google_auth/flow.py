from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from typing import Any

from .resolve import CredentialSpec, CredentialsUnavailable


def run_interactive_flow(
    spec: CredentialSpec,
    *,
    env: Mapping[str, str] | None = None,
    flow_class: Any | None = None,
) -> Any:
    if not spec.client_config_env:
        raise CredentialsUnavailable(
            f"No installed-app client config env is configured for {spec.worker_id}/{spec.key}.",
            remedy="Set client_config_env on the CredentialSpec.",
        )
    runtime_env = env if env is not None else os.environ
    raw = runtime_env.get(spec.client_config_env, "").strip()
    if not raw:
        raise CredentialsUnavailable(
            f"${spec.client_config_env} is not set for {spec.worker_id}/{spec.key}.",
            remedy=f"Set ${spec.client_config_env} to installed-app client JSON.",
        )
    try:
        client_config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialsUnavailable(
            f"${spec.client_config_env} does not contain valid JSON"
        ) from exc
    flow_type = flow_class or _installed_app_flow_class()
    flow = flow_type.from_client_config(client_config, list(spec.scopes))
    return flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )


def _installed_app_flow_class() -> Any:
    try:
        flow_module = importlib.import_module("google_auth_oauthlib.flow")
    except ImportError as exc:
        raise CredentialsUnavailable(
            "google-auth-oauthlib is not installed.",
            remedy="Install with the clonway-cockpit[google] optional extra.",
        ) from exc
    return flow_module.InstalledAppFlow
