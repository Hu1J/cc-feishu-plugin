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
class ProactiveConfig:
    enabled: bool = True
    time_window_start: str = "08:00"   # HH:MM 格式
    time_window_end: str = "22:00"      # HH:MM 格式
    silence_threshold_minutes: int = 90
    check_interval_minutes: int = 5
    max_per_day: int = 3              # 0 表示不限次数
    cooldown_minutes: int = 60        # 发完一条后，同会话冷却分钟数


@dataclass
class Config:
    feishu: FeishuConfig
    auth: AuthConfig
    claude: ClaudeConfig
    storage: StorageConfig
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    data_dir: str = ""
    bypass_accepted: bool = False


def _upgrade_config(path: str) -> None:
    """Auto-upgrade config.yaml: add proactive section if missing, remove stale server section."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    changed = False

    # Add proactive section if missing
    if "proactive" not in raw:
        raw["proactive"] = {
            "enabled": True,
            "time_window_start": "08:00",
            "time_window_end": "22:00",
            "silence_threshold_minutes": 90,
            "check_interval_minutes": 5,
            "max_per_day": 3,
            "cooldown_minutes": 60,
        }
        changed = True

    # Remove stale server section (deprecated in v0.2.3)
    if "server" in raw:
        del raw["server"]
        changed = True

    if changed:
        with open(path, "w") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_config(path: str, data_dir: str = "") -> Config:
    """Load and validate configuration from YAML file."""
    _upgrade_config(path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    proactive = ProactiveConfig(**raw.get("proactive", {}))
    return Config(
        feishu=FeishuConfig(**raw.get("feishu", {})),
        auth=AuthConfig(**raw.get("auth", {})),
        claude=ClaudeConfig(**raw.get("claude", {})),
        storage=StorageConfig(**raw.get("storage", {})),
        proactive=proactive,
        data_dir=data_dir,
        bypass_accepted=raw.get("bypass_accepted", False),
    )


def save_config(path: str, feishu_app_id: str, feishu_app_secret: str,
                domain: str, bot_name: str,
                allowed_users: list[str],
                claude_cli_path: str, claude_max_turns: int,
                claude_approved_directory: str,
                storage_db_path: str,
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
        "proactive": {
            "enabled": True,
            "time_window_start": "08:00",
            "time_window_end": "22:00",
            "silence_threshold_minutes": 90,
            "check_interval_minutes": 5,
            "max_per_day": 3,
            "cooldown_minutes": 60,
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
