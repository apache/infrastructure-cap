"""Settings loaded from ``config.yaml`` at startup. See SPEC section 5.1."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_CONFIG_SEARCH_PATH = (
    "./config.yaml",
    "/etc/cap/config.yaml",
)


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8085
    permalink_base: str = ""
    # ``GET /api/publist`` (SPEC §9.13) is the only endpoint that serves
    # the same body to every caller, so it is cached in process memory.
    # This value is the maximum age, in seconds, the cache is allowed to
    # hold a body for before the next request triggers a refresh. A value
    # of ``0`` disables the cache entirely (every request recomputes).
    publist_cache_seconds: int = Field(default=30, ge=0)


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class OAuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None


class PubsubBasicAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = None
    password: str | None = None


class PubsubSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    base_url: str = "https://pubsub.apache.org:2069"
    basic_auth: PubsubBasicAuth = Field(default_factory=PubsubBasicAuth)
    timeout_seconds: int = 5


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"


class NotificationsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # When set to a non-empty address, every notification email is redirected
    # there instead of the project list. Leave empty (or omit) in production.
    debug_recipient: str | None = None


class Settings(BaseModel):
    """Top-level configuration. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings
    oauth: OAuthSettings = Field(default_factory=OAuthSettings)
    pubsub: PubsubSettings = Field(default_factory=PubsubSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    notifications: NotificationsSettings = Field(default_factory=NotificationsSettings)


def resolve_config_path(cli_path: str | None = None) -> Path:
    """Resolve the config-file path per SPEC section 5.1."""
    if cli_path:
        return Path(cli_path)

    env = os.environ.get("CAP_CONFIG")
    if env:
        return Path(env)

    for candidate in _DEFAULT_CONFIG_SEARCH_PATH:
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return candidate_path

    raise FileNotFoundError(
        "No config.yaml found. Set --config, CAP_CONFIG, or place a config.yaml "
        "in the working directory or /etc/cap/config.yaml."
    )


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    """Load and validate a Settings object from a YAML file."""
    resolved = resolve_config_path(str(path) if path else None)
    with open(resolved, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file {resolved} must contain a top-level mapping.")

    pwd_env = os.environ.get("CAP_PUBSUB_PASSWORD")
    if pwd_env:
        raw.setdefault("pubsub", {}).setdefault("basic_auth", {})["password"] = pwd_env

    return Settings.model_validate(raw)
