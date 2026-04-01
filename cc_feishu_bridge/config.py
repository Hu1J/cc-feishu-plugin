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
    data_dir: str = ""
    bypass_accepted: bool = False


def load_config(path: str, data_dir: str = "") -> Config:
    """Load and validate configuration from YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    return Config(
        feishu=FeishuConfig(**raw.get("feishu", {})),
        auth=AuthConfig(**raw.get("auth", {})),
        claude=ClaudeConfig(**raw.get("claude", {})),
        storage=StorageConfig(**raw.get("storage", {})),
        server=ServerConfig(**raw.get("server", {})),
        data_dir=data_dir,
        bypass_accepted=raw.get("bypass_accepted", False),
    )


def save_config(path: str, feishu_app_id: str, feishu_app_secret: str,
                domain: str, bot_name: str,
                allowed_users: list[str],
                claude_cli_path: str, claude_max_turns: int,
                claude_approved_directory: str,
                storage_db_path: str,
                server_host: str, server_port: int, server_webhook_path: str,
                bypass_accepted: bool = False) -> None:
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
        "bypass_accepted": bypass_accepted,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def accept_bypass_warning(config_path: str) -> None:
    """Record that the bypass permissions risk warning has been accepted."""
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    raw["bypass_accepted"] = True
    with open(config_path, "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)


README_CONTENT = """# .cc-feishu-bridge

This directory is created automatically by `cc-feishu-bridge` and contains all runtime data for this instance.

## Contents

- `config.yaml` — Bot credentials and configuration
- `sessions.db` — SQLite database of user sessions and conversation history
- `cc-feishu-bridge.log` — Runtime log file
- `cc-feishu-bridge.pid` — PID file (process management)

## Multi-instance Isolation

Running `cc-feishu-bridge` in different working directories creates independent bot instances,
each with its own config, sessions, and logs. This is the intended design.

## Git Ignore

This directory is gitignored. It should never be committed.

"""


def resolve_config_path() -> tuple[str, str]:
    """Resolve config and data directories relative to cwd.

    Uses .cc-feishu-bridge/ subdirectory in the current working directory
    for natural multi-instance isolation:
      - Config: {cwd}/.cc-feishu-bridge/config.yaml
      - Data:  {cwd}/.cc-feishu-bridge/ (sessions.db, logs, cc-feishu-bridge.pid)

    Auto-creates .cc-feishu-bridge/ if not found (runs install flow on first start).
    """
    import os
    cwd = os.getcwd()
    cc_dir = Path(cwd).resolve() / ".cc-feishu-bridge"
    cc_dir.mkdir(exist_ok=True)
    cfg_path = cc_dir / "config.yaml"
    cfg_path.touch(exist_ok=True)
    readme_path = cc_dir / "README.md"
    readme_path.write_text(README_CONTENT, errors="replace")
    return (str(cfg_path), str(cc_dir))
