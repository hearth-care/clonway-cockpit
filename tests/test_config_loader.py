from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from clonway_cockpit.config import ConfigError, SecretEnvName, load_config


class SyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: int = 7
    enabled: bool = False


class ExampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "worker"
    retries: int = 1
    sync: SyncConfig = SyncConfig()
    api_key_env: SecretEnvName | None = None


def write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_file_only_config(tmp_path: Path):
    cfg_path = write_yaml(
        tmp_path / "worker.yaml",
        """
name: file-worker
retries: 3
sync:
  window_days: 14
  enabled: true
""",
    )

    cfg = load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert cfg.name == "file-worker"
    assert cfg.retries == 3
    assert cfg.sync.window_days == 14
    assert cfg.sync.enabled is True


def test_loads_env_only_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XBOOK__NAME", "env-worker")
    monkeypatch.setenv("XBOOK__RETRIES", "5")
    monkeypatch.setenv("XBOOK__SYNC__ENABLED", "true")

    cfg = load_config(ExampleConfig, worker_id="xbook", paths=[])

    assert cfg.name == "env-worker"
    assert cfg.retries == 5
    assert cfg.sync.enabled is True


def test_env_wins_over_file_and_supports_nested_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg_path = write_yaml(
        tmp_path / "worker.yaml",
        """
name: file-worker
retries: 2
sync:
  window_days: 3
  enabled: false
""",
    )
    monkeypatch.setenv("XBOOK__RETRIES", "9")
    monkeypatch.setenv("XBOOK__SYNC__WINDOW_DAYS", "30")

    cfg = load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert cfg.name == "file-worker"
    assert cfg.retries == 9
    assert cfg.sync.window_days == 30
    assert cfg.sync.enabled is False


def test_validation_errors_include_env_and_file_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg_path = write_yaml(
        tmp_path / "worker.yaml",
        """
name: file-worker
retries: not-an-int
sync:
  window_days: 3
""",
    )
    monkeypatch.setenv("XBOOK__SYNC__WINDOW_DAYS", "many")

    with pytest.raises(ConfigError) as exc_info:
        load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert exc_info.value.problems == [
        f"file {cfg_path}: retries: Input should be a valid integer, unable to parse string as an integer",
        "env XBOOK__SYNC__WINDOW_DAYS: sync.window_days: Input should be a valid integer, unable to parse string as an integer",
    ]


def test_aggregates_validation_errors_and_unset_secret_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg_path = write_yaml(
        tmp_path / "worker.yaml",
        """
name: 123
retries: not-an-int
api_key_env: MISSING_API_KEY
""",
    )
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert exc_info.value.problems == [
        f"file {cfg_path}: name: Input should be a valid string",
        f"file {cfg_path}: retries: Input should be a valid integer, unable to parse string as an integer",
        "env MISSING_API_KEY: api_key_env references an unset secret env var",
    ]


def test_missing_file_allowed_by_default(tmp_path: Path):
    cfg = load_config(ExampleConfig, worker_id="xbook", paths=[tmp_path / "missing.yaml"])

    assert cfg == ExampleConfig()


def test_missing_file_can_be_required(tmp_path: Path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ConfigError) as exc_info:
        load_config(ExampleConfig, worker_id="xbook", paths=[missing], require_file=True)

    assert exc_info.value.problems == [f"file {missing}: not found"]


def test_unset_secret_env_warns_without_failing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_path = write_yaml(tmp_path / "worker.yaml", "api_key_env: MISSING_API_KEY\n")
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    with pytest.warns(UserWarning, match="MISSING_API_KEY"):
        cfg = load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert cfg.api_key_env == "MISSING_API_KEY"


def test_non_mapping_yaml_is_rejected(tmp_path: Path):
    cfg_path = write_yaml(tmp_path / "worker.yaml", "- not\n- a\n- mapping\n")

    with pytest.raises(ConfigError) as exc_info:
        load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert exc_info.value.problems == [f"file {cfg_path}: config must be a mapping"]


def test_secret_env_warning_uses_standard_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_path = write_yaml(tmp_path / "worker.yaml", "api_key_env: MISSING_API_KEY\n")
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_config(ExampleConfig, worker_id="xbook", paths=[cfg_path])

    assert [str(item.message) for item in caught] == [
        "api_key_env references unset secret env var MISSING_API_KEY"
    ]
