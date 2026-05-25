"""Settings loader tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from cap_backend.config import Settings, load_settings, resolve_config_path


def test_load_valid_config(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
server:
  host: "127.0.0.1"
  port: 9999
database:
  path: "/tmp/cap.sqlite3"
pubsub:
  enabled: false
  base_url: "https://example.invalid"
""".strip()
    )
    settings = load_settings(cfg)
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 9999
    assert settings.database.path == "/tmp/cap.sqlite3"
    assert settings.pubsub.enabled is False


def test_unknown_keys_rejected(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
database:
  path: "/tmp/cap.sqlite3"
unknown_section:
  foo: 1
""".strip()
    )
    with pytest.raises(ValidationError):
        load_settings(cfg)


def test_pubsub_password_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
database:
  path: "/tmp/cap.sqlite3"
pubsub:
  basic_auth:
    username: "cap-publisher"
""".strip()
    )
    monkeypatch.setenv("CAP_PUBSUB_PASSWORD", "s3cret")
    settings = load_settings(cfg)
    assert settings.pubsub.basic_auth.password == "s3cret"


def test_resolve_config_path_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "from-env.yaml"
    cfg.write_text("database:\n  path: '/x'\n")
    monkeypatch.setenv("CAP_CONFIG", str(cfg))
    # CLI argument wins over env.
    other = tmp_path / "explicit.yaml"
    other.write_text("database:\n  path: '/y'\n")
    assert resolve_config_path(str(other)) == other
    assert resolve_config_path(None) == cfg


def test_missing_config_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CAP_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    # /etc/cap/config.yaml should not exist in the test environment.
    if Path("/etc/cap/config.yaml").exists():
        pytest.skip("/etc/cap/config.yaml exists on this host")
    with pytest.raises(FileNotFoundError):
        resolve_config_path(None)


def test_settings_defaults_when_only_database_set():
    settings = Settings(database={"path": "/tmp/x.sqlite3"})  # type: ignore[arg-type]
    assert settings.server.port == 8085
    assert settings.logging.level == "INFO"
    assert settings.pubsub.enabled is True
    assert os.path.basename(settings.database.path) == "x.sqlite3"
