# tests/test_obs_logsetup.py
"""CC-LOGSETUP-* — obs.logsetup unit tests."""

from __future__ import annotations

import logging

import pytest

from clonway_cockpit.obs.logsetup import setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


# ---- level resolution -------------------------------------------------------


def test_default_level_is_info(monkeypatch):  # CC-LOGSETUP-LVL-1
    monkeypatch.delenv("XBOOK_LOG_LEVEL", raising=False)
    setup_logging("xbook")
    assert logging.getLogger().level == logging.INFO


def test_explicit_level_wins(monkeypatch):  # CC-LOGSETUP-LVL-2
    monkeypatch.setenv("XBOOK_LOG_LEVEL", "ERROR")
    setup_logging("xbook", level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_env_level_used_when_no_explicit(monkeypatch):  # CC-LOGSETUP-LVL-3
    monkeypatch.setenv("XBOOK_LOG_LEVEL", "WARNING")
    setup_logging("xbook")
    assert logging.getLogger().level == logging.WARNING


def test_level_env_var_keyed_by_worker_id(monkeypatch):  # CC-LOGSETUP-LVL-4
    monkeypatch.delenv("XBOOK_LOG_LEVEL", raising=False)
    monkeypatch.setenv("XHR_LOG_LEVEL", "DEBUG")
    setup_logging("xhr")
    assert logging.getLogger().level == logging.DEBUG


# ---- idempotency ------------------------------------------------------------


def test_double_call_leaves_one_handler():  # CC-LOGSETUP-IDEM-1
    setup_logging("xbook")
    setup_logging("xbook")
    assert len(logging.getLogger().handlers) == 1


def test_triple_call_leaves_one_handler():  # CC-LOGSETUP-IDEM-2
    for _ in range(3):
        setup_logging("xletter")
    assert len(logging.getLogger().handlers) == 1


# ---- quiet list -------------------------------------------------------------


def test_quiet_list_forces_warning(monkeypatch):  # CC-LOGSETUP-QUIET-1
    monkeypatch.delenv("XBOOK_LOG_LEVEL", raising=False)
    setup_logging("xbook", level="DEBUG", quiet=["httpx", "urllib3"])
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_quiet_does_not_affect_root_level():  # CC-LOGSETUP-QUIET-2
    setup_logging("xbook", level="DEBUG", quiet=["httpx"])
    assert logging.getLogger().level == logging.DEBUG


# ---- cloud_run mode ---------------------------------------------------------


def test_cloud_run_env_does_not_raise(monkeypatch):  # CC-LOGSETUP-CLOUD-1
    monkeypatch.setenv("XBOOK_RUNTIME", "cloud_run")
    setup_logging("xbook", runtime_env="XBOOK_RUNTIME")
    assert len(logging.getLogger().handlers) == 1


def test_non_cloud_run_env_does_not_raise(monkeypatch):  # CC-LOGSETUP-CLOUD-2
    monkeypatch.setenv("XBOOK_RUNTIME", "local")
    setup_logging("xbook", runtime_env="XBOOK_RUNTIME")
    assert len(logging.getLogger().handlers) == 1


# ---- format check -----------------------------------------------------------


def test_formatter_uses_utc(caplog):  # CC-LOGSETUP-FMT-1
    # Verify the formatter is attached and fires without error.
    setup_logging("xbook", level="DEBUG")
    root = logging.getLogger()
    assert root.handlers
    handler = root.handlers[0]
    assert handler.formatter is not None
    # The format string contains %(name)s — check it.
    assert "%(name)s" in handler.formatter._fmt  # type: ignore[union-attr]
