from __future__ import annotations

import fcntl
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from clonway_cockpit.google_auth import CredentialsUnavailable, RefreshLockTimeout
from clonway_cockpit.google_auth.refresh import refresh_if_needed
from clonway_cockpit.google_auth.store import MemoryTokenStore


class FakeCredentials:
    def __init__(
        self,
        token: str,
        *,
        scopes: tuple[str, ...] = ("scope-a",),
        valid: bool = False,
        expired: bool = True,
        refresh_token: str | None = "fake-refresh",
        refresh_error: Exception | None = None,
        refresh_count: list[int] | None = None,
    ) -> None:
        self.token = token
        self.scopes = scopes
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.refresh_error = refresh_error
        self.refresh_count = refresh_count

    def refresh(self, _request: Any) -> None:
        if self.refresh_error is not None:
            raise self.refresh_error
        time.sleep(0.05)
        if self.refresh_count is not None:
            self.refresh_count[0] += 1
        self.token = "fake-fresh"
        self.valid = True
        self.expired = False

    def to_json(self) -> str:
        return json.dumps({"token": self.token, "scopes": list(self.scopes)})


def fake_factory(info: dict[str, Any], scopes: tuple[str, ...]) -> FakeCredentials:
    return FakeCredentials(
        str(info["token"]),
        scopes=scopes,
        valid=info["token"] == "fake-fresh",
        expired=info["token"] != "fake-fresh",
    )


def test_refresh_if_needed_performs_exactly_one_refresh_under_concurrency(tmp_path: Path) -> None:
    store = MemoryTokenStore({"gmail": {"token": "fake-expired", "scopes": ["scope-a"]}})
    refresh_count = [0]
    barrier = threading.Barrier(2)
    results: list[FakeCredentials] = []

    def worker() -> None:
        creds = FakeCredentials("fake-expired", refresh_count=refresh_count)
        barrier.wait()
        results.append(
            refresh_if_needed(
                creds,
                store=store,
                key="gmail",
                scopes=("scope-a",),
                lock_dir=tmp_path,
                credential_factory=fake_factory,
                request_factory=lambda: object(),
            )
        )

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert refresh_count == [1]
    assert [result.token for result in results] == ["fake-fresh", "fake-fresh"]
    assert store.load("gmail") == {"token": "fake-fresh", "scopes": ["scope-a"]}


def test_refresh_if_needed_times_out_when_lock_is_held(tmp_path: Path) -> None:
    store = MemoryTokenStore({"gmail": {"token": "fake-expired", "scopes": ["scope-a"]}})
    lock_path = tmp_path / "gmail.lock"
    lock_path.touch()
    with lock_path.open("w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        with pytest.raises(RefreshLockTimeout):
            refresh_if_needed(
                FakeCredentials("fake-expired"),
                store=store,
                key="gmail",
                scopes=("scope-a",),
                lock_dir=tmp_path,
                timeout_seconds=0.01,
                credential_factory=fake_factory,
                request_factory=lambda: object(),
            )
        fcntl.flock(lock_fh, fcntl.LOCK_UN)


def test_refresh_failure_keeps_stored_token_and_raises_remedy(tmp_path: Path) -> None:
    store = MemoryTokenStore({"gmail": {"token": "fake-expired", "scopes": ["scope-a"]}})

    with pytest.raises(CredentialsUnavailable) as excinfo:
        refresh_if_needed(
            FakeCredentials("fake-expired", refresh_error=RuntimeError("fake invalid_grant")),
            store=store,
            key="gmail",
            scopes=("scope-a",),
            lock_dir=tmp_path,
            credential_factory=fake_factory,
            request_factory=lambda: object(),
        )

    assert store.load("gmail") == {"token": "fake-expired", "scopes": ["scope-a"]}
    assert "Re-auth" in excinfo.value.remedy
    assert "fake-expired" not in str(excinfo.value)
