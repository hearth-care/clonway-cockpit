from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from clonway_cockpit.google_auth import CredentialSpec, CredentialsUnavailable, ScopeMismatch
from clonway_cockpit.google_auth.resolve import resolve_credentials
from clonway_cockpit.google_auth.store import MemoryTokenStore


@dataclass
class FakeCredentials:
    source: str
    scopes: tuple[str, ...]
    valid: bool = True
    expired: bool = False
    refresh_token: str | None = "fake-refresh"

    def to_json(self) -> str:
        return json.dumps({"token": f"fake-{self.source}", "scopes": list(self.scopes)})


def spec(**overrides: object) -> CredentialSpec:
    values = {
        "worker_id": "xletter",
        "key": "gmail",
        "scopes": ("scope-a", "scope-b"),
    }
    values.update(overrides)
    return CredentialSpec(**values)


def test_resolve_credentials_returns_injected_credentials_first() -> None:
    injected = FakeCredentials("injected", ("scope-a", "scope-b"))
    store = MemoryTokenStore({"gmail": {"token": "fake-stored", "scopes": ["scope-a", "scope-b"]}})

    result = resolve_credentials(
        spec(injected_credentials=injected, sa_info_env="SA_JSON"),
        store=store,
        env={"SA_JSON": '{"client_email":"fake@example.invalid"}'},
        user_credentials_factory=lambda *_args, **_kwargs: FakeCredentials("stored", ()),
        service_account_factory=lambda *_args, **_kwargs: FakeCredentials("sa", ()),
    )

    assert result is injected


def test_resolve_credentials_prefers_service_account_env_over_stored_token() -> None:
    calls: list[tuple[dict, tuple[str, ...], str | None]] = []

    def service_account_factory(
        info: dict, scopes: tuple[str, ...], subject: str | None = None
    ) -> FakeCredentials:
        calls.append((info, scopes, subject))
        return FakeCredentials("sa", scopes)

    result = resolve_credentials(
        spec(sa_info_env="SA_JSON", subject="operator@example.invalid"),
        store=MemoryTokenStore(
            {"gmail": {"token": "fake-stored", "scopes": ["scope-a", "scope-b"]}}
        ),
        env={"SA_JSON": '{"client_email":"fake@example.invalid"}'},
        user_credentials_factory=lambda *_args, **_kwargs: FakeCredentials("stored", ()),
        service_account_factory=service_account_factory,
    )

    assert result == FakeCredentials("sa", ("scope-a", "scope-b"))
    assert calls == [
        (
            {"client_email": "fake@example.invalid"},
            ("scope-a", "scope-b"),
            "operator@example.invalid",
        )
    ]


def test_resolve_credentials_loads_stored_token_when_scopes_cover_spec() -> None:
    store = MemoryTokenStore({"gmail": {"token": "fake-stored", "scopes": ["scope-a", "scope-b"]}})

    result = resolve_credentials(
        spec(),
        store=store,
        env={},
        user_credentials_factory=lambda info, scopes: FakeCredentials(
            str(info["token"]), tuple(scopes)
        ),
    )

    assert result == FakeCredentials("fake-stored", ("scope-a", "scope-b"))


def test_resolve_credentials_refreshes_expired_stored_token() -> None:
    store = MemoryTokenStore({"gmail": {"token": "fake-expired", "scopes": ["scope-a", "scope-b"]}})

    def refresh_if_needed(creds: FakeCredentials, **kwargs: object) -> FakeCredentials:
        assert kwargs["store"] is store
        assert kwargs["key"] == "gmail"
        assert kwargs["scopes"] == ("scope-a", "scope-b")
        return FakeCredentials("refreshed", ("scope-a", "scope-b"))

    result = resolve_credentials(
        spec(),
        store=store,
        env={},
        user_credentials_factory=lambda _info, scopes: FakeCredentials(
            "expired", tuple(scopes), valid=False, expired=True
        ),
        refresh_func=refresh_if_needed,
    )

    assert result == FakeCredentials("refreshed", ("scope-a", "scope-b"))


def test_resolve_credentials_treats_narrower_stored_token_as_absent() -> None:
    interactive_calls: list[CredentialSpec] = []

    def interactive_flow(flow_spec: CredentialSpec) -> FakeCredentials:
        interactive_calls.append(flow_spec)
        return FakeCredentials("interactive", flow_spec.scopes)

    result = resolve_credentials(
        spec(client_config_env="CLIENT_JSON", allow_interactive=True),
        store=MemoryTokenStore({"gmail": {"token": "fake-stored", "scopes": ["scope-a"]}}),
        env={"CLIENT_JSON": '{"installed":{"client_id":"fake-client"}}'},
        user_credentials_factory=lambda *_args, **_kwargs: FakeCredentials("stored", ()),
        interactive_flow=interactive_flow,
    )

    assert result == FakeCredentials("interactive", ("scope-a", "scope-b"))
    assert len(interactive_calls) == 1


def test_resolve_credentials_raises_with_remedy_when_no_interactive_path() -> None:
    with pytest.raises(CredentialsUnavailable) as excinfo:
        resolve_credentials(spec(), store=MemoryTokenStore(), env={})

    assert "Run an interactive Google OAuth consent flow" in excinfo.value.remedy


def test_scope_mismatch_message_never_contains_token_material() -> None:
    with pytest.raises(ScopeMismatch) as excinfo:
        resolve_credentials(
            spec(),
            store=MemoryTokenStore(
                {"gmail": {"token": "fake-secret-token", "scopes": ["scope-a"]}}
            ),
            env={},
        )

    assert "fake-secret-token" not in str(excinfo.value)
    assert "scope-b" in str(excinfo.value)
