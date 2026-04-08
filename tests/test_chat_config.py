import pytest
from cc_feishu_bridge.config import (
    Config, FeishuConfig, AuthConfig, ClaudeConfig, StorageConfig,
    ChatModesConfig, ChatOverrideConfig,
)


def test_get_chat_mode_default():
    config = Config(
        feishu=FeishuConfig(app_id="a", app_secret="s"),
        auth=AuthConfig(),
        claude=ClaudeConfig(approved_directory="/tmp"),
        storage=StorageConfig(),
        chat_modes=ChatModesConfig(default="mention"),
    )
    assert config.get_chat_mode("och_anything") == "mention"


def test_get_chat_mode_override():
    config = Config(
        feishu=FeishuConfig(app_id="a", app_secret="s"),
        auth=AuthConfig(),
        claude=ClaudeConfig(approved_directory="/tmp"),
        storage=StorageConfig(),
        chat_modes=ChatModesConfig(default="mention"),
        chat_overrides={"och_groupA": ChatOverrideConfig(chat_mode="open")},
    )
    assert config.get_chat_mode("och_groupA") == "open"
    assert config.get_chat_mode("och_groupB") == "mention"


def test_resolve_project_path_chat_override():
    config = Config(
        feishu=FeishuConfig(app_id="a", app_secret="s"),
        auth=AuthConfig(),
        claude=ClaudeConfig(approved_directory="/global"),
        storage=StorageConfig(),
        chat_overrides={"och_groupA": ChatOverrideConfig(project_path="/frontend")},
    )
    assert config.resolve_project_path("och_groupA", "ou_anyone") == "/frontend"
    assert config.resolve_project_path("och_groupB", "ou_anyone") == "/global"


def test_resolve_project_path_user_override():
    config = Config(
        feishu=FeishuConfig(app_id="a", app_secret="s"),
        auth=AuthConfig(),
        claude=ClaudeConfig(approved_directory="/global"),
        storage=StorageConfig(),
        user_overrides={"ou_userC": ChatOverrideConfig(project_path="/backend")},
    )
    assert config.resolve_project_path("och_any", "ou_userC") == "/backend"
    assert config.resolve_project_path("och_any", "ou_other") == "/global"


def test_resolve_project_path_priority_chat_over_user():
    """chat_overrides takes precedence over user_overrides when both are set."""
    config = Config(
        feishu=FeishuConfig(app_id="a", app_secret="s"),
        auth=AuthConfig(),
        claude=ClaudeConfig(approved_directory="/global"),
        storage=StorageConfig(),
        chat_overrides={"och_groupA": ChatOverrideConfig(project_path="/from_chat")},
        user_overrides={"ou_userC": ChatOverrideConfig(project_path="/from_user")},
    )
    # Same user in the group chat — chat_overrides should win
    assert config.resolve_project_path("och_groupA", "ou_userC") == "/from_chat"
    # Different chat, user has override — user_overrides used
    assert config.resolve_project_path("och_other", "ou_userC") == "/from_user"