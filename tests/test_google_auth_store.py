from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from clonway_cockpit.google_auth import CredentialSpec, CredentialsUnavailable
from clonway_cockpit.google_auth.store import (
    FileTokenStore,
    KeyringTokenStore,
    MemoryTokenStore,
    default_store,
)


def test_memory_token_store_round_trips_verbatim_token_dict() -> None:
    store = MemoryTokenStore()
    token = {"token": "fake-access", "scopes": ["scope-a"], "nested": {"ok": True}}

    store.save("gmail", token)

    assert store.load("gmail") == token
    store.delete("gmail")
    assert store.load("gmail") is None


def test_file_token_store_writes_one_0600_json_file_per_key(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path)
    token = {"token": "fake-access", "refresh_token": "fake-refresh"}

    store.save("gmail", token)

    path = tmp_path / "gmail.json"
    assert json.loads(path.read_text()) == token
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert store.load("gmail") == token
    store.delete("gmail")
    assert store.load("gmail") is None


def test_file_token_store_never_leaves_partial_target_on_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileTokenStore(tmp_path)

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated crash"):
        store.save("gmail", {"token": "fake-new"})

    assert not (tmp_path / "gmail.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.values.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.values[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        try:
            del self.values[(service, key)]
        except KeyError as exc:
            raise self.errors.PasswordDeleteError from exc


def test_keyring_token_store_uses_worker_scoped_service_name() -> None:
    fake = FakeKeyring()
    store = KeyringTokenStore("xletter", keyring_module=fake)

    store.save("gmail", {"token": "fake-access"})

    assert fake.values == {("clonway-xletter", "gmail"): '{"token":"fake-access"}'}
    assert store.load("gmail") == {"token": "fake-access"}
    store.delete("gmail")
    assert store.load("gmail") is None


class BrokenKeyring(FakeKeyring):
    def set_password(self, service: str, key: str, value: str) -> None:
        raise RuntimeError("keyring unavailable")


def test_default_store_falls_back_to_file_when_keyring_probe_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XLETTER_STATE_ROOT", str(tmp_path))

    store = default_store("xletter", base_dir_env="XLETTER_STATE_ROOT", keyring_module=BrokenKeyring())

    assert isinstance(store, FileTokenStore)
    store.save("gmail", {"token": "fake-access"})
    assert (tmp_path / "gmail.json").exists()


def test_credential_spec_requires_declared_scopes() -> None:
    with pytest.raises(CredentialsUnavailable, match="scopes"):
        CredentialSpec(worker_id="xletter", key="gmail", scopes=())
