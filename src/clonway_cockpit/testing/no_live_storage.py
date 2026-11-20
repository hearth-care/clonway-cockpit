"""Pytest guard that keeps a worker's test suite away from live fleet storage.

A developer machine usually holds working Google Cloud credentials and real settings.
Without a guard, an ordinary test run can write test data into the live fleet bucket
(this happened once: reminders were uploaded and a live file replaced with an empty one,
and the failed-upload handling hid it). Switch the guard on with one line in the worker's
``tests/conftest.py``::

    pytest_plugins = ["clonway_cockpit.testing.no_live_storage"]

It adds an autouse fixture that, for every test:

* points ``HOME`` and the gcloud configuration at a temporary directory, so no saved
  credentials or settings are found;
* removes ``GOOGLE_APPLICATION_CREDENTIALS`` and ``CLONWAY_FLEET_BUCKET``, plus any
  worker-specific variables named in the ``no_live_storage_env_vars`` ini option;
* replaces the Google Cloud Storage client's constructor with one that fails the test
  with a plain message naming the test. The failure is raised as a pytest outcome, which
  is not an ``Exception``, so best-effort writers that catch ``Exception`` cannot hide it.

A test that is meant to reach real storage opts out of the constructor block with
``@pytest.mark.live_storage``; the environment isolation still applies, so such a test
supplies its own credentials and bucket explicitly.

Worker-specific variables go in ``pyproject.toml``::

    [tool.pytest.ini_options]
    no_live_storage_env_vars = ["XBOOK_FLEET_BUCKET", "XBOOK_STATE_BUCKET"]
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any

import pytest

MARKER = "live_storage"
INI_ENV_VARS = "no_live_storage_env_vars"
_ALWAYS_CLEARED = ("GOOGLE_APPLICATION_CREDENTIALS", "CLONWAY_FLEET_BUCKET")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        INI_ENV_VARS,
        type="linelist",
        default=[],
        help="Extra environment variables (worker bucket settings) the no_live_storage "
        "guard removes before every test.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}: the test is meant to reach real Google Cloud Storage; the "
        "no_live_storage guard stops blocking the client constructor for it.",
    )


def _storage_modules() -> list[Any]:
    """``google.cloud.storage`` and its ``client`` submodule, when installed.

    Imported here rather than at module load so the plugin works in a worker that does
    not depend on google-cloud-storage (then no real client can be built anyway).
    """
    modules: list[Any] = []
    for name in ("google.cloud.storage", "google.cloud.storage.client"):
        try:
            modules.append(importlib.import_module(name))
        except ImportError:
            continue
    return modules


@pytest.fixture(autouse=True)
def no_live_storage(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    home = tmp_path_factory.mktemp("no-live-storage-home")
    gcloud_dir = home / ".config" / "gcloud"
    gcloud_dir.mkdir(parents=True)
    for var, value in (
        ("HOME", home),
        ("USERPROFILE", home),
        ("XDG_CONFIG_HOME", home / ".config"),
        ("CLOUDSDK_CONFIG", gcloud_dir),
    ):
        monkeypatch.setenv(var, str(value))
    extra = [v.strip() for v in request.config.getini(INI_ENV_VARS) if v.strip()]
    for var in (*_ALWAYS_CLEARED, *extra):
        monkeypatch.delenv(var, raising=False)

    if request.node.get_closest_marker(MARKER) is None:
        test_id = request.node.nodeid

        class _BlockedClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pytest.fail(
                    f"{test_id} tried to build a real Google Cloud Storage client. "
                    "Use a fake client, or mark the test @pytest.mark.live_storage if it "
                    "is meant to reach real storage.",
                    pytrace=False,
                )

        for module in _storage_modules():
            if hasattr(module, "Client"):
                monkeypatch.setattr(module, "Client", _BlockedClient)
    yield
