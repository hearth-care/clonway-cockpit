from __future__ import annotations

import importlib
from typing import Any

import pytest

from clonway_cockpit.google_auth import CredentialsUnavailable
from clonway_cockpit.google_auth.service import build_service, sa_credentials


class FakeServiceAccountCredentials:
    calls: list[tuple[dict[str, Any], list[str], str | None]] = []

    @classmethod
    def from_service_account_info(
        cls, info: dict[str, Any], *, scopes: list[str], subject: str | None = None
    ) -> str:
        cls.calls.append((info, scopes, subject))
        return "fake-creds"


def test_sa_credentials_builds_service_account_and_dwd_with_declared_scopes() -> None:
    FakeServiceAccountCredentials.calls.clear()

    result = sa_credentials(
        {"client_email": "worker@example.invalid"},
        ("scope-a", "scope-b"),
        subject="operator@example.invalid",
        credentials_class=FakeServiceAccountCredentials,
    )

    assert result == "fake-creds"
    assert FakeServiceAccountCredentials.calls == [
        (
            {"client_email": "worker@example.invalid"},
            ["scope-a", "scope-b"],
            "operator@example.invalid",
        )
    ]


def test_build_service_uses_cache_discovery_false_by_default() -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def builder(api: str, version: str, **kwargs: Any) -> str:
        calls.append((api, version, kwargs))
        return "fake-service"

    result = build_service("gmail", "v1", "fake-creds", builder=builder)

    assert result == "fake-service"
    assert calls == [
        ("gmail", "v1", {"credentials": "fake-creds", "cache_discovery": False})
    ]


def test_google_auth_import_does_not_require_google_extra() -> None:
    module = importlib.import_module("clonway_cockpit.google_auth")

    assert module.CredentialSpec(worker_id="xletter", key="gmail", scopes=("scope-a",))


def test_google_touching_call_has_clear_missing_extra_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_import(_name: str) -> Any:
        raise ImportError("no google")

    monkeypatch.setattr(importlib, "import_module", missing_import)

    with pytest.raises(CredentialsUnavailable) as excinfo:
        sa_credentials({"client_email": "worker@example.invalid"}, ("scope-a",))

    assert "clonway-cockpit[google]" in excinfo.value.remedy
