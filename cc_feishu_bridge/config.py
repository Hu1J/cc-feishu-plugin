"""Configuration loading and validation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

logger = logging.getLogger(__name__)


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
class ChatOverrideConfig:
    chat_mode: str = "mention"   # "mention" 或 "open"
    project_path: str = ""       # 空字符串表示使用全局 claude.approved_directory
    max_turns: int = 0           # 0 表示使用全局 claude.max_turns


@dataclass
class ChatModesConfig:
    default: str = "mention"     # 全局默认 chat_mode


@dataclass
class Config:
    feishu: FeishuConfig
    auth: AuthConfig
    claude: ClaudeConfig
    storage: StorageConfig
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    chat_modes: ChatModesConfig = field(default_factory=ChatModesConfig)
    chat_overrides: dict[str, ChatOverrideConfig] = field(default_factory=dict)
    user_overrides: dict[str, ChatOverrideConfig] = field(default_factory=dict)
    data_dir: str = ""
    bypass_accepted: bool = False

    def get_chat_mode(self, chat_id: str) -> str:
        """Query chat_mode for a given chat_id. Priority: chat_overrides > global default."""
        if chat_id in self.chat_overrides:
            return self.chat_overrides[chat_id].chat_mode
        return self.chat_modes.default

    def resolve_project_path(self, chat_id: str, user_open_id: str) -> str:
        """Query project_path for a given chat/user. Priority: chat_overrides > user_overrides > global claude.approved_directory."""
        if chat_id in self.chat_overrides:
            override = self.chat_overrides[chat_id]
            if override.project_path:
                return override.project_path
        if user_open_id in self.user_overrides:
            override = self.user_overrides[user_open_id]
            if override.project_path:
                return override.project_path
        return self.claude.approved_directory


def _upgrade_config(path: str) -> None:
    """Auto-upgrade config.yaml: add missing sections, remove stale sections."""
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

    # Add chat_modes section if missing (group chat mode config)
    if "chat_modes" not in raw:
        raw["chat_modes"] = {
            "default": "mention",
        }
        changed = True

    # Remove stale server section (deprecated in v0.2.3)
    if "server" in raw:
        del raw["server"]
        changed = True

    if changed:
        with open(path, "w") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def auto_register_group_chat(config_path: str, chat_id: str) -> bool:
    """Auto-register a group chat in chat_overrides if not already registered.

    Returns True if the chat was newly registered, False if it was already present.
    """
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    chat_overrides = raw.get("chat_overrides", {})
    if chat_id in chat_overrides:
        return False

    # New group — register it with default mention mode
    if "chat_overrides" not in raw:
        raw["chat_overrides"] = {}
    raw["chat_overrides"][chat_id] = {
        "chat_mode": "mention",
    }

    with open(config_path, "w") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"Auto-registered group chat {chat_id} in chat_overrides (mention mode).")
    return True


def load_config(path: str, data_dir: str = "") -> Config:
    """Load and validate configuration from YAML file."""
    _upgrade_config(path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    proactive = ProactiveConfig(**raw.get("proactive", {}))

    chat_modes_raw = raw.get("chat_modes", {})
    chat_modes = ChatModesConfig(default=chat_modes_raw.get("default", "mention"))

    chat_overrides = {}
    for chat_id, cfg in raw.get("chat_overrides", {}).items():
        chat_overrides[chat_id] = ChatOverrideConfig(
            chat_mode=cfg.get("chat_mode", "mention"),
            project_path=cfg.get("project_path", ""),
            max_turns=cfg.get("max_turns", 0),
        )

    user_overrides = {}
    for user_id, cfg in raw.get("user_overrides", {}).items():
        user_overrides[user_id] = ChatOverrideConfig(
            project_path=cfg.get("project_path", ""),
            max_turns=cfg.get("max_turns", 0),
        )

    return Config(
        feishu=FeishuConfig(**raw.get("feishu", {})),
        auth=AuthConfig(**raw.get("auth", {})),
        claude=ClaudeConfig(**raw.get("claude", {})),
        storage=StorageConfig(**raw.get("storage", {})),
        proactive=proactive,
        chat_modes=chat_modes,
        chat_overrides=chat_overrides,
        user_overrides=user_overrides,
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
