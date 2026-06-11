from __future__ import annotations

import contextlib
import importlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol


class TokenStore(Protocol):
    def load(self, key: str) -> dict[str, Any] | None: ...
    def save(self, key: str, token: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> None: ...


class MemoryTokenStore:
    def __init__(self, initial: dict[str, dict[str, Any]] | None = None) -> None:
        self._tokens = dict(initial or {})

    def load(self, key: str) -> dict[str, Any] | None:
        token = self._tokens.get(key)
        return dict(token) if token is not None else None

    def save(self, key: str, token: dict[str, Any]) -> None:
        self._tokens[key] = dict(token)

    def delete(self, key: str) -> None:
        self._tokens.pop(key, None)


class FileTokenStore:
    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)

    def _path(self, key: str) -> Path:
        _validate_key(key)
        return self._base_dir / f"{key}.json"

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save(self, key: str, token: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                json.dump(token, tmp, separators=(",", ":"), sort_keys=True)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
            os.chmod(path, 0o600)
        except Exception:
            if tmp_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    tmp_path.unlink()
            raise

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()


class KeyringTokenStore:
    def __init__(self, worker_id: str, *, keyring_module: Any | None = None) -> None:
        self._service = f"clonway-{worker_id}"
        self._keyring = keyring_module

    def _backend(self) -> Any:
        if self._keyring is None:
            self._keyring = importlib.import_module("keyring")
        return self._keyring

    def load(self, key: str) -> dict[str, Any] | None:
        raw = self._backend().get_password(self._service, key)
        return json.loads(raw) if raw else None

    def save(self, key: str, token: dict[str, Any]) -> None:
        self._backend().set_password(
            self._service,
            key,
            json.dumps(token, separators=(",", ":"), sort_keys=True),
        )

    def delete(self, key: str) -> None:
        backend = self._backend()
        with contextlib.suppress(Exception):
            backend.delete_password(self._service, key)


def default_store(
    worker_id: str,
    *,
    base_dir_env: str,
    keyring_module: Any | None = None,
) -> TokenStore:
    keyring_store = KeyringTokenStore(worker_id, keyring_module=keyring_module)
    probe_key = "__clonway_google_auth_probe__"
    try:
        keyring_store.save(probe_key, {"token": "fake-probe"})
        if keyring_store.load(probe_key) == {"token": "fake-probe"}:
            keyring_store.delete(probe_key)
            return keyring_store
    except Exception:
        with contextlib.suppress(Exception):
            keyring_store.delete(probe_key)

    base_dir = os.environ.get(base_dir_env)
    if not base_dir:
        raise RuntimeError(f"{base_dir_env} must be set when keyring is unavailable")
    return FileTokenStore(Path(base_dir))


def _validate_key(key: str) -> None:
    if not key or "/" in key or "\\" in key or key in {".", ".."}:
        raise ValueError(f"invalid token store key: {key!r}")
