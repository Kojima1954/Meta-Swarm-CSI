"""Configuration loader — reads TOML config and env var overrides."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, model_validator

_DEFAULT_CONFIG_PATH = "/etc/orchestrator/config.toml"


class NodeConfig(BaseModel):
    id: str
    name: str = ""
    domain: str


class MatrixConfig(BaseModel):
    homeserver_url: str = "http://conduit:6167"
    server_name: str = ""
    room_alias: str = ""
    user_id: str = ""
    password: str = ""

    @model_validator(mode="after")
    def _apply_defaults(self) -> "MatrixConfig":
        if not self.user_id:
            self.user_id = os.environ.get(
                "MATRIX_ORCHESTRATOR_USER", f"@orchestrator:{self.server_name}"
            )
        if not self.password:
            self.password = os.environ.get("MATRIX_ORCHESTRATOR_PASSWORD", "")
        return self


class AIConfig(BaseModel):
    llm_model: str = "llama3.1:8b"
    embedding_model: str = "nomic-embed-text"
    ollama_url: str = "http://ollama:11434"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "swarm_memory"
    temperature: float = 0.3
    max_tokens: int = 2048


class FederationConfig(BaseModel):
    gotosocial_url: str = "http://gotosocial:8080"
    protocol: str = "https"
    access_token: str = ""

    @model_validator(mode="after")
    def _apply_env(self) -> "FederationConfig":
        if not self.access_token:
            self.access_token = os.environ.get("GOTOSOCIAL_ACCESS_TOKEN", "")
        return self


class RoundsConfig(BaseModel):
    mode: str = "timer"
    interval_seconds: int = 300
    message_threshold: int = 50


class SecurityConfig(BaseModel):
    key_path: str = "/data/keys/node.key"
    public_key_path: str = "/data/keys/node.pub"
    # Users authorized to trigger !summarize (empty = allow all room members)
    allowed_trigger_users: list[str] = []


class LoggingConfig(BaseModel):
    level: str = "info"


class Settings(BaseModel):
    node: NodeConfig
    matrix: MatrixConfig = MatrixConfig()
    ai: AIConfig = AIConfig()
    federation: FederationConfig = FederationConfig()
    rounds: RoundsConfig = RoundsConfig()
    security: SecurityConfig = SecurityConfig()
    logging: LoggingConfig = LoggingConfig()


def load_settings(path: str | None = None) -> Settings:
    """Load settings from a TOML file with env var overrides."""
    config_path = Path(path or os.environ.get("ORCHESTRATOR_CONFIG", _DEFAULT_CONFIG_PATH))

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return Settings(**data)
