from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
