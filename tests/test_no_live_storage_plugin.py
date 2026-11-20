"""The ``clonway_cockpit.testing.no_live_storage`` pytest plugin, run in a child pytest.

A fake ``google.cloud.storage`` package is planted in the child's directory so the test
does not depend on google-cloud-storage being installed (the framework does not require it).
"""

from __future__ import annotations

import pytest

_FAKE_GOOGLE = {
    "google/__init__.py": "",
    "google/cloud/__init__.py": "",
    "google/cloud/storage/__init__.py": (
        "from google.cloud.storage import client\nfrom google.cloud.storage.client import Client\n"
    ),
    "google/cloud/storage/client.py": "class Client:\n    def __init__(self, *a, **k):\n        pass\n",
}


@pytest.fixture
def child(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    for name, body in _FAKE_GOOGLE.items():
        path = pytester.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    pytester.makeconftest('pytest_plugins = ["clonway_cockpit.testing.no_live_storage"]\n')
    pytester.makeini(
        "[pytest]\naddopts = --strict-markers\nno_live_storage_env_vars =\n    DEMO_FLEET_BUCKET\n"
    )
    return pytester


def test_constructing_a_storage_client_fails_the_test_with_its_name(child):
    child.makepyfile(
        test_blocked="""
        def test_builds_a_client():
            from google.cloud import storage
            storage.Client()

        def test_builds_a_client_through_the_submodule():
            from google.cloud.storage.client import Client
            Client(project="p")
        """
    )
    result = child.runpytest_subprocess()
    result.assert_outcomes(failed=2)
    result.stdout.fnmatch_lines(
        [
            "*test_blocked.py::test_builds_a_client tried to build a real Google Cloud "
            "Storage client.*",
            "*mark the test @pytest.mark.live_storage*",
        ]
    )


def test_swallowing_exceptions_cannot_hide_the_attempt(child):
    child.makepyfile(
        test_swallow="""
        def test_best_effort_writer():
            from google.cloud import storage
            try:
                storage.Client()
            except Exception:
                pass
        """
    )
    child.runpytest_subprocess().assert_outcomes(failed=1)


def test_live_storage_marker_allows_the_client(child):
    child.makepyfile(
        test_live="""
        import pytest

        @pytest.mark.live_storage
        def test_reaches_storage():
            from google.cloud import storage
            assert storage.Client() is not None
        """
    )
    child.runpytest_subprocess().assert_outcomes(passed=1)


def test_environment_is_isolated(child, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/real/creds.json")
    monkeypatch.setenv("CLONWAY_FLEET_BUCKET", "example-fleet-bucket")
    monkeypatch.setenv("DEMO_FLEET_BUCKET", "example-worker-bucket")
    monkeypatch.setenv("UNRELATED_SETTING", "kept")
    monkeypatch.setenv("REAL_HOME", "/Users/someone")
    child.makepyfile(
        test_env="""
        import os
        from pathlib import Path

        def test_isolated():
            for name in ("GOOGLE_APPLICATION_CREDENTIALS", "CLONWAY_FLEET_BUCKET",
                         "DEMO_FLEET_BUCKET"):
                assert name not in os.environ, name
            assert os.environ["UNRELATED_SETTING"] == "kept"
            home = Path(os.environ["HOME"])
            assert str(home) != os.environ["REAL_HOME"]
            assert Path("~").expanduser() == home
            assert Path(os.environ["CLOUDSDK_CONFIG"]).is_relative_to(home)
            assert Path(os.environ["CLOUDSDK_CONFIG"]).is_dir()
        """
    )
    child.runpytest_subprocess().assert_outcomes(passed=1)


def test_environment_is_restored_after_each_test(child, monkeypatch):
    monkeypatch.setenv("CLONWAY_FLEET_BUCKET", "example-fleet-bucket")
    child.makepyfile(
        test_restore="""
        import os

        def test_sets_it():
            os.environ["CLONWAY_FLEET_BUCKET"] = "set-inside-test"

        def test_still_clear():
            assert "CLONWAY_FLEET_BUCKET" not in os.environ
        """
    )
    child.runpytest_subprocess().assert_outcomes(passed=2)
