from __future__ import annotations

import importlib
from typing import Any

import pytest

from clonway_cockpit.google_auth import CredentialSpec, CredentialsUnavailable
from clonway_cockpit.google_auth.flow import run_interactive_flow


class FakeInstalledAppFlow:
    calls: list[tuple[dict[str, Any], list[str]]] = []

    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []

    @classmethod
    def from_client_config(cls, config: dict[str, Any], scopes: list[str]) -> "FakeInstalledAppFlow":
        cls.calls.append((config, scopes))
        return cls()

    def run_local_server(self, **kwargs: Any) -> str:
        self.run_calls.append(kwargs)
        return "fake-creds"


def test_run_interactive_flow_uses_installed_app_client_config_from_env() -> None:
    FakeInstalledAppFlow.calls.clear()
    spec = CredentialSpec(
        worker_id="xletter",
        key="gmail",
        scopes=("scope-a", "scope-b"),
        client_config_env="CLIENT_JSON",
        allow_interactive=True,
    )

    result = run_interactive_flow(
        spec,
        env={"CLIENT_JSON": '{"installed":{"client_id":"fake-client"}}'},
        flow_class=FakeInstalledAppFlow,
    )

    assert result == "fake-creds"
    assert FakeInstalledAppFlow.calls == [
        ({"installed": {"client_id": "fake-client"}}, ["scope-a", "scope-b"])
    ]


def test_run_interactive_flow_has_clear_missing_extra_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_import(_name: str) -> Any:
        raise ImportError("no google auth oauthlib")

    monkeypatch.setattr(importlib, "import_module", missing_import)

    with pytest.raises(CredentialsUnavailable) as excinfo:
        run_interactive_flow(
            CredentialSpec(
                worker_id="xletter",
                key="gmail",
                scopes=("scope-a",),
                client_config_env="CLIENT_JSON",
                allow_interactive=True,
            ),
            env={"CLIENT_JSON": '{"installed":{"client_id":"fake-client"}}'},
        )

    assert "clonway-cockpit[google]" in excinfo.value.remedy
