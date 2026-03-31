"""Configuration loading and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class FeishuConfig:
    app_id: str
    app_secret: str
    bot_name: str = "Claude"
    domain: str = "feishu"


@dataclass
class AuthConfig:
    allowed_users: List[str] = field(default_factory=list)


@dataclass
class ClaudeConfig:
    cli_path: str = "claude"
    max_turns: int = 50
    approved_directory: str = str(Path.home())


@dataclass
class StorageConfig:
    db_path: str = "./data/sessions.db"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    webhook_path: str = "/feishu/webhook"


@dataclass
class Config:
    feishu: FeishuConfig
    auth: AuthConfig
    claude: ClaudeConfig
    storage: StorageConfig
    server: ServerConfig


def load_config(path: str) -> Config:
    """Load and validate configuration from YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    return Config(
        feishu=FeishuConfig(**raw.get("feishu", {})),
        auth=AuthConfig(**raw.get("auth", {})),
        claude=ClaudeConfig(**raw.get("claude", {})),
        storage=StorageConfig(**raw.get("storage", {})),
        server=ServerConfig(**raw.get("server", {})),
    )


def save_config(path: str, feishu_app_id: str, feishu_app_secret: str,
                domain: str, bot_name: str,
                allowed_users: list[str],
                claude_cli_path: str, claude_max_turns: int,
                claude_approved_directory: str,
                storage_db_path: str,
                server_host: str, server_port: int, server_webhook_path: str) -> None:
    """Save a complete config to a YAML file."""
    config = {
        "feishu": {
            "app_id": feishu_app_id,
            "app_secret": feishu_app_secret,
            "bot_name": bot_name,
            "domain": domain,
        },
        "auth": {
            "allowed_users": allowed_users,
        },
        "claude": {
            "cli_path": claude_cli_path,
            "max_turns": claude_max_turns,
            "approved_directory": claude_approved_directory,
        },
        "storage": {
            "db_path": storage_db_path,
        },
        "server": {
            "host": server_host,
            "port": server_port,
            "webhook_path": server_webhook_path,
        },
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
