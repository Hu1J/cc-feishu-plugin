# 飞书多用户 + 群聊支持 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持多用户 P2P 和群聊场景，session 按 chat_id/P2P 隔离，并发按 chat_id 调度，配置支持按 chat_id/user_open_id 分层覆盖。

**Architecture:**
- Session key 改为 `(user_open_id, chat_id)` 的语义：P2P 用 `user_open_id`，群聊用 `chat_id`
- `ChatLockManager` 按 session_key 锁粒度调度，同 chat 串行，跨 chat 并发
- `ClaudeIntegrationPool` 按 session_key 复用 Integration 实例
- 配置层新增 `chat_modes`/`chat_overrides`/`user_overrides`，支持分层覆盖

**Tech Stack:** Python asyncio, lark-oapi, SQLite, claude-agent-sdk

---

## 文件结构变更

```
cc_feishu_bridge/
  claude/
    session_manager.py     # 修改：session key 变更为 session_key (p2p=user_open_id, group=chat_id)
    integration.py        # 修改：新增 ClaudeIntegrationPool
    integration_pool.py   # 新增：ClaudeIntegrationPool + ChatLockManager
  feishu/
    ws_client.py          # 修改：确认 chat_type 字段传递
    message_handler.py    # 修改：should_respond + @判断 + ChatLockManager 集成
    client.py             # 修改：send_text_by_open_id (open_id 类型 receive_id)
  config.py              # 修改：新增 ChatModesConfig / chat_overrides / user_overrides
  main.py                # 修改：wire ClaudeIntegrationPool
tests/
  test_session_manager.py # 修改：适配新 session key API
  test_chat_lock.py      # 新增：ChatLockManager 单元测试
  test_integration_pool.py # 新增：ClaudeIntegrationPool 单元测试
  test_config.py         # 新增：分层配置读取测试
  test_should_respond.py # 新增：should_respond 逻辑测试
```

---

## Task 1: Session Manager — session key 改造

**Files:**
- Modify: `cc_feishu_bridge/claude/session_manager.py`
- Modify: `tests/test_session_manager.py`

### 背景

当前 Session 按 `user_open_id` 查找。改为：
- P2P：`session_key = user_open_id`
- 群聊：`session_key = chat_id`

Session dataclass 新增 `chat_type` 字段（`"p2p"` 或 `"group"`）。

### 实现

- [ ] **Step 1: 修改 Session dataclass**

在 `cc_feishu_bridge/claude/session_manager.py` 的 `Session` dataclass 中新增字段：

```python
@dataclass
class Session:
    session_id: str
    sdk_session_id: str | None
    user_id: str              # 发送者 open_id（保留，用于 @ 回复）
    project_path: str
    created_at: datetime
    last_used: datetime
    total_cost: float
    message_count: int
    chat_id: str | None = None
    last_message_at: datetime | None = None
    proactive_today_count: int = 0
    proactive_today_date: str | None = None
    last_proactive_at: datetime | None = None
    # 新增
    chat_type: str = "p2p"   # "p2p" 或 "group"
    session_key: str = ""      # p2p=user_open_id, group=chat_id
```

- [ ] **Step 2: 修改 create_session，增加 chat_type 和 session_key**

```python
def create_session(
    self,
    user_id: str,
    project_path: str,
    sdk_session_id: str | None = None,
    chat_type: str = "p2p",
    chat_id: str | None = None,
) -> Session:
    # session_key = chat_id if group else user_id
    if chat_type == "group" and chat_id:
        session_key = chat_id
    else:
        session_key = user_id
    # ... 插入 DB 时带上 chat_type 和 session_key
```

- [ ] **Step 3: 修改 get_active_session — 接受 session_key 参数**

```python
def get_active_session(self, session_key: str) -> Optional[Session]:
    """按 session_key 查找 session（session_key = user_open_id for p2p, = chat_id for group）."""
    with sqlite3.connect(self.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM sessions WHERE session_key = ? ORDER BY last_used DESC LIMIT 1""",
            (session_key,),
        ).fetchone()
        # ...
```

- [ ] **Step 4: 修改 update_session — 按 session_key 而非 session_id 定位**

SessionManager 内部仍然按 `session_id` 操作 DB（session_id 是主键），但对外暴露 `get_active_session(session_key)`。已有 `get_active_session(user_open_id)` 的调用方需要更新。

- [ ] **Step 5: 修改 DB schema — sessions 表新增 chat_type 列**

在 `_init_db()` 的 migration block 中添加：

```python
try:
    conn.execute("ALTER TABLE sessions ADD COLUMN chat_type TEXT DEFAULT 'p2p'")
except sqlite3.OperationalError:
    pass
try:
    conn.execute("ALTER TABLE sessions ADD COLUMN session_key TEXT DEFAULT ''")
except sqlite3.OperationalError:
    pass
```

- [ ] **Step 6: 修改 tests/test_session_manager.py**

所有调用 `get_active_session(user_open_id)` 的测试改为传入正确的 session_key（P2P 场景下 user_open_id 就是 session_key）。

```python
def test_create_and_get_session(manager):
    session = manager.create_session("ou_123", "/Users/test/projects")
    assert session.user_id == "ou_123"
    assert session.project_path == "/Users/test/projects"
    assert session.message_count == 0
    assert session.chat_type == "p2p"
    assert session.session_key == "ou_123"

    active = manager.get_active_session("ou_123")  # session_key = user_open_id in p2p
    assert active is not None
    assert active.session_id == session.session_id


def test_create_and_get_group_session(manager):
    session = manager.create_session(
        "ou_123",
        "/Users/test/projects",
        chat_type="group",
        chat_id="och_group456",
    )
    assert session.chat_type == "group"
    assert session.session_key == "och_group456"

    active = manager.get_active_session("och_group456")
    assert active is not None
    assert active.session_id == session.session_id


def test_group_and_p2p_sessions_independent(manager):
    """同一 user_open_id 在 group 和 p2p 下有不同的 session."""
    p2p_session = manager.create_session("ou_123", "/tmp", chat_type="p2p")
    group_session = manager.create_session(
        "ou_123", "/tmp", chat_type="group", chat_id="och_group456"
    )
    assert p2p_session.session_key == "ou_123"
    assert group_session.session_key == "och_group456"
    assert manager.get_active_session("ou_123").session_id == p2p_session.session_id
    assert manager.get_active_session("och_group456").session_id == group_session.session_id
```

- [ ] **Step 7: 运行测试**

```bash
cd /Users/x/.openclaw/workspace/cc-feishu-bridge
pytest tests/test_session_manager.py -v
```

- [ ] **Step 8: Commit**

```bash
git add cc_feishu_bridge/claude/session_manager.py tests/test_session_manager.py
git commit -m "feat(session): change session key to session_key (user_open_id for p2p, chat_id for group)"
```

---

## Task 2: 分层配置读取

**Files:**
- Modify: `cc_feishu_bridge/config.py`
- Create: `tests/test_chat_config.py`

### 实现

- [ ] **Step 1: 新增 ChatOverrideConfig dataclass**

在 `config.py` 中添加：

```python
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
    data_dir: str = ""
    bypass_accepted: bool = False
    # 新增
    chat_modes: ChatModesConfig = field(default_factory=ChatModesConfig)
    chat_overrides: dict[str, ChatOverrideConfig] = field(default_factory=dict)
    user_overrides: dict[str, ChatOverrideConfig] = field(default_factory=dict)
```

- [ ] **Step 2: 修改 load_config — 解析新增字段**

在 `load_config()` 中：

```python
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
    # ... existing fields ...
    chat_modes=chat_modes,
    chat_overrides=chat_overrides,
    user_overrides=user_overrides,
)
```

- [ ] **Step 3: 新增 Config.get_chat_mode(chat_id) 方法**

```python
def get_chat_mode(self, chat_id: str) -> str:
    """查询指定 chat_id 的 chat_mode，优先级: chat_overrides > 全局 default."""
    if chat_id in self.chat_overrides:
        return self.chat_overrides[chat_id].chat_mode
    return self.chat_modes.default


def resolve_project_path(self, chat_id: str, user_open_id: str) -> str:
    """查询指定会话的 project_path，优先级: chat_overrides > user_overrides > 全局 claude.approved_directory."""
    if chat_id in self.chat_overrides:
        override = self.chat_overrides[chat_id]
        if override.project_path:
            return override.project_path
    if user_open_id in self.user_overrides:
        override = self.user_overrides[user_open_id]
        if override.project_path:
            return override.project_path
    return self.claude.approved_directory
```

- [ ] **Step 4: 写测试**

```python
# tests/test_chat_config.py
from cc_feishu_bridge.config import ChatModesConfig, ChatOverrideConfig, Config, FeishuConfig, AuthConfig, ClaudeConfig, StorageConfig

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
    assert config.get_chat_mode("och_groupB") == "mention"  # 回落全局


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
```

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_chat_config.py -v
```

- [ ] **Step 6: Commit**

```bash
git add cc_feishu_bridge/config.py tests/test_chat_config.py
git commit -m "feat(config): add chat_modes and layered chat/user overrides"
```

---

## Task 3: ChatLockManager

**Files:**
- Create: `cc_feishu_bridge/claude/chat_lock.py`
- Create: `tests/test_chat_lock.py`

### 实现

- [ ] **Step 1: 写 ChatLockManager**

```python
# cc_feishu_bridge/claude/chat_lock.py
"""Chat-level lock manager for serializing messages per chat."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LockResult:
    acquired: bool
    lock: asyncio.Lock | None


class ChatLockManager:
    """Per-chat async lock with global concurrency limit.

    Usage:
        result = await lock_manager.acquire("och_xxx")
        if not result.acquired:
            return "当前会话繁忙，请稍后再试 🛑"
        try:
            await do_work()
        finally:
            await lock_manager.release("och_xxx")
    """

    def __init__(self, max_concurrent: int = 10):
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_count: int = 0
        self._max_concurrent = max_concurrent
        self._count_lock = asyncio.Lock()

    async def acquire(self, chat_id: str) -> LockResult:
        """Attempt to acquire a lock for chat_id.

        Returns LockResult(acquired=True, lock=lock) if successful.
        Returns LockResult(acquired=False, lock=None) if:
          - max concurrent limit reached
          - chat is already locked (another task is running in this chat)
        """
        async with self._count_lock:
            if self._max_concurrent > 0 and self._active_count >= self._max_concurrent:
                logger.warning(f"Max concurrent limit ({self._max_concurrent}) reached")
                return LockResult(acquired=False, lock=None)

        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        if lock.locked():
            logger.info(f"Chat {chat_id} is already locked")
            return LockResult(acquired=False, lock=None)

        await lock.acquire()
        self._active_count += 1
        logger.info(f"Acquired lock for chat {chat_id} ({self._active_count}/{self._max_concurrent})")
        return LockResult(acquired=True, lock=lock)

    async def release(self, chat_id: str) -> None:
        """Release the lock for chat_id."""
        if chat_id not in self._locks:
            return
        lock = self._locks[chat_id]
        if lock.locked():
            lock.release()
            async with self._count_lock:
                self._active_count -= 1
            logger.info(f"Released lock for chat {chat_id} ({self._active_count}/{self._max_concurrent})")

    @property
    def active_count(self) -> int:
        return self._active_count
```

- [ ] **Step 2: 写测试**

```python
# tests/test_chat_lock.py
import asyncio
import pytest
from cc_feishu_bridge.claude.chat_lock import ChatLockManager


@pytest.fixture
def lock_mgr():
    return ChatLockManager(max_concurrent=2)


@pytest.mark.asyncio
async def test_acquire_release(lock_mgr):
    result = await lock_mgr.acquire("och_test")
    assert result.acquired is True
    assert result.lock is not None

    await lock_mgr.release("och_test")
    assert lock_mgr.active_count == 0


@pytest.mark.asyncio
async def test_same_chat_blocked(lock_mgr):
    r1 = await lock_mgr.acquire("och_test")
    assert r1.acquired is True

    r2 = await lock_mgr.acquire("och_test")
    assert r2.acquired is False  # already locked

    await lock_mgr.release("och_test")
    r3 = await lock_mgr.acquire("och_test")
    assert r3.acquired is True  # now available again


@pytest.mark.asyncio
async def test_different_chats_independent(lock_mgr):
    r1 = await lock_mgr.acquire("och_chatA")
    r2 = await lock_mgr.acquire("och_chatB")
    assert r1.acquired is True
    assert r2.acquired is True
    assert lock_mgr.active_count == 2


@pytest.mark.asyncio
async def test_max_concurrent_limit(lock_mgr):
    # max_concurrent=2
    r1 = await lock_mgr.acquire("och_A")
    r2 = await lock_mgr.acquire("och_B")
    assert r1.acquired is True
    assert r2.acquired is True

    r3 = await lock_mgr.acquire("och_C")
    assert r3.acquired is False  # limit reached

    await lock_mgr.release("och_A")
    r4 = await lock_mgr.acquire("och_C")
    assert r4.acquired is True  # now available
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_chat_lock.py -v
```

- [ ] **Step 4: Commit**

```bash
git add cc_feishu_bridge/claude/chat_lock.py tests/test_chat_lock.py
git commit -m "feat(chat_lock): add ChatLockManager for per-chat concurrency control"
```

---

## Task 4: ws_client — 确认群聊消息解析 + chat_type 传递

**Files:**
- Modify: `cc_feishu_bridge/feishu/ws_client.py`
- Modify: `tests/test_ws_client.py`

### 背景

`ws_client.py` 的 `wrapped_handler` 解析飞书事件时，需要把 `chat_type` 传递给 `IncomingMessage`。目前 `IncomingMessage` dataclass 没有 `chat_type` 字段。

### 实现

- [ ] **Step 1: IncomingMessage 新增 chat_type 字段**

在 `cc_feishu_bridge/feishu/client.py` 的 `IncomingMessage` dataclass 中添加：

```python
@dataclass
class IncomingMessage:
    message_id: str
    chat_id: str
    user_open_id: str
    content: str
    message_type: str
    create_time: str
    parent_id: str = ""
    thread_id: str = ""
    raw_content: str = ""
    # 新增
    chat_type: str = "p2p"  # "p2p" 或 "group"
```

- [ ] **Step 2: ws_client 解析 chat_type**

在 `ws_client.py` 的 `wrapped_handler` 中，解析消息时添加：

```python
# 解析 chat_type（p2p 或 group）
chat_type = getattr(event_data, "chat_type", "p2p") or "p2p"

incoming = IncomingMessage(
    message_id=getattr(message, "message_id", ""),
    chat_id=getattr(message, "chat_id", ""),
    user_open_id=user_open_id,
    content=content,
    message_type=msg_type,
    create_time=getattr(message, "create_time", ""),
    parent_id=getattr(message, "parent_id", ""),
    thread_id=getattr(message, "thread_id", ""),
    raw_content=content_str,
    chat_type=chat_type,
)
```

- [ ] **Step 3: 写测试验证群聊消息解析**

在 `tests/test_ws_client.py` 中新增测试：

```python
def test_p2p_message_has_chat_type(mock_client):
    """P2P messages should have chat_type='p2p'."""
    import json
    from unittest.mock import MagicMock

    event = MagicMock()
    event.event = MagicMock()
    event.event.message = MagicMock()
    event.event.message.message_id = "msg_p2p"
    event.event.message.chat_id = "och_p2p_chat"
    event.event.message.msg_type = "text"
    event.event.message.content = json.dumps({"text": "hello"})
    event.event.message.create_time = "1234567890"
    event.event.message.parent_id = ""
    event.event.message.thread_id = ""
    event.event.sender = MagicMock()
    event.event.sender.sender_id = MagicMock()
    event.event.sender.sender_id.open_id = "ou_user1"
    event.event.chat_type = "p2p"

    client = FeishuWSClient("app_id", "app_secret", on_message=lambda m: None)
    result = []
    async def capture(msg):
        result.append(msg)

    client._on_message = capture
    handler = client._build_event_handler()
    # 找到 p2p handler 并调用
    p2p_handler = handler._processorMap.get("p2.im.message.receive_v1")
    p2p_handler.f(event)

    assert result[0].chat_type == "p2p"


def test_group_message_has_chat_type(mock_client):
    """Group messages should have chat_type='group'."""
    import json
    from unittest.mock import MagicMock

    event = MagicMock()
    event.event = MagicMock()
    event.event.message = MagicMock()
    event.event.message.message_id = "msg_group"
    event.event.message.chat_id = "och_group_chat"
    event.event.message.msg_type = "text"
    event.event.message.content = json.dumps({"text": "hello group"})
    event.event.message.create_time = "1234567890"
    event.event.message.parent_id = ""
    event.event.message.thread_id = ""
    event.event.sender = MagicMock()
    event.event.sender.sender_id = MagicMock()
    event.event.sender.sender_id.open_id = "ou_user2"
    event.event.chat_type = "group"

    result = []
    async def capture(msg):
        result.append(msg)

    client = FeishuWSClient("app_id", "app_secret", on_message=capture)
    handler = client._build_event_handler()
    p2p_handler = handler._processorMap.get("p2.im.message.receive_v1")
    p2p_handler.f(event)

    assert result[0].chat_type == "group"
    assert result[0].user_open_id == "ou_user2"
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_ws_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add cc_feishu_bridge/feishu/ws_client.py cc_feishu_bridge/feishu/client.py tests/test_ws_client.py
git commit -m "feat(ws): parse and pass chat_type in IncomingMessage"
```

---

## Task 5: should_respond + @判断

**Files:**
- Create: `cc_feishu_bridge/feishu/should_respond.py`
- Create: `tests/test_should_respond.py`

### 实现

- [ ] **Step 1: should_respond 函数**

```python
# cc_feishu_bridge/feishu/should_respond.py
"""Determines whether the bot should respond to an incoming message."""
from __future__ import annotations

import json
import logging
from cc_feishu_bridge.feishu.client import IncomingMessage
from cc_feishu_bridge.config import Config

logger = logging.getLogger(__name__)


def should_respond(message: IncomingMessage, config: Config, bot_open_id: str) -> bool:
    """Return True if the bot should respond to this message.

    Logic:
      - P2P: always respond (user explicitly started a conversation with the bot)
      - Group, chat_mode=open: always respond (bot sees all messages)
      - Group, chat_mode=mention: respond only if bot was @mentioned
      - Group, chat_mode=mention + not @mentioned: ignore silently
    """
    if message.chat_type == "p2p":
        return True

    # Group chat — check chat_mode from config
    chat_mode = config.get_chat_mode(message.chat_id)
    if chat_mode == "open":
        return True

    # mention mode: check if bot was @mentioned
    return _is_bot_mentioned(message.raw_content, bot_open_id)


def _is_bot_mentioned(raw_content: str, bot_open_id: str) -> bool:
    """Parse raw_content JSON and check if bot_open_id appears in mentions."""
    if not raw_content:
        return False
    try:
        content = json.loads(raw_content)
    except Exception:
        return False

    mentions = content.get("mentions", [])
    if not isinstance(mentions, list):
        return False

    for mention in mentions:
        if isinstance(mention, dict) and mention.get("open_id") == bot_open_id:
            return True
    return False
```

- [ ] **Step 2: 写测试**

```python
# tests/test_should_respond.py
import pytest
from cc_feishu_bridge.feishu.should_respond import should_respond, _is_bot_mentioned
from cc_feishu_bridge.feishu.client import IncomingMessage
from cc_feishu_bridge.config import Config, ChatModesConfig, ChatOverrideConfig

@pytest.fixture
def mention_mode_config():
    return Config(
        feishu=__import__("cc_feishu_bridge.config", fromlist=["FeishuConfig"]).FeishuConfig(app_id="a", app_secret="s"),
        auth=__import__("cc_feishu_bridge.config", fromlist=["AuthConfig"]).AuthConfig(),
        claude=__import__("cc_feishu_bridge.config", fromlist=["ClaudeConfig"]).ClaudeConfig(),
        storage=__import__("cc_feishu_bridge.config", fromlist=["StorageConfig"]).StorageConfig(),
        chat_modes=ChatModesConfig(default="mention"),
    )

@pytest.fixture
def open_mode_config():
    from cc_feishu_bridge.config import Config, ChatModesConfig
    return Config(
        feishu=__import__("cc_feishu_bridge.config", fromlist=["FeishuConfig"]).FeishuConfig(app_id="a", app_secret="s"),
        auth=__import__("cc_feishu_bridge.config", fromlist=["AuthConfig"]).AuthConfig(),
        claude=__import__("cc_feishu_bridge.config", fromlist=["ClaudeConfig"]).ClaudeConfig(),
        storage=__import__("cc_feishu_bridge.config", fromlist=["StorageConfig"]).StorageConfig(),
        chat_modes=ChatModesConfig(default="open"),
    )

def make_group_message(chat_id, raw_content):
    return IncomingMessage(
        message_id="msg1",
        chat_id=chat_id,
        user_open_id="ou_member1",
        content="hello",
        message_type="text",
        create_time="123456",
        raw_content=raw_content,
        chat_type="group",
    )

def make_p2p_message():
    return IncomingMessage(
        message_id="msg2",
        chat_id="och_p2p",
        user_open_id="ou_user1",
        content="hello",
        message_type="text",
        create_time="123456",
        raw_content='{"text":"hi"}',
        chat_type="p2p",
    )

def test_p2p_always_responds(mention_mode_config):
    msg = make_p2p_message()
    assert should_respond(msg, mention_mode_config, "ou_bot") is True

def test_group_mention_mode_not_mentioned(mention_mode_config):
    raw = '{"text":"hello world"}'
    msg = make_group_message("och_group1", raw)
    assert should_respond(msg, mention_mode_config, "ou_bot") is False

def test_group_mention_mode_mentioned(mention_mode_config):
    raw = '{"text":"@Claude hello","mentions":[{"open_id":"ou_bot","name":"Claude"}]}'
    msg = make_group_message("och_group1", raw)
    assert should_respond(msg, mention_mode_config, "ou_bot") is True

def test_group_open_mode_always_responds(open_mode_config):
    raw = '{"text":"any message"}'
    msg = make_group_message("och_group2", raw)
    assert should_respond(msg, open_mode_config, "ou_bot") is True

def test_group_mention_mode_chat_override():
    from cc_feishu_bridge.config import Config, ChatModesConfig, ChatOverrideConfig
    cfg = Config(
        feishu=__import__("cc_feishu_bridge.config", fromlist=["FeishuConfig"]).FeishuConfig(app_id="a", app_secret="s"),
        auth=__import__("cc_feishu_bridge.config", fromlist=["AuthConfig"]).AuthConfig(),
        claude=__import__("cc_feishu_bridge.config", fromlist=["ClaudeConfig"]).ClaudeConfig(),
        storage=__import__("cc_feishu_bridge.config", fromlist=["StorageConfig"]).StorageConfig(),
        chat_modes=ChatModesConfig(default="mention"),
        chat_overrides={"och_groupA": ChatOverrideConfig(chat_mode="open")},
    )
    msg = make_group_message("och_groupA", '{"text":"hello"}')
    assert should_respond(msg, cfg, "ou_bot") is True  # groupA uses open mode
    msg2 = make_group_message("och_groupB", '{"text":"hello"}')
    assert should_respond(msg2, cfg, "ou_bot") is False  # groupB uses default=mention, not @

def test_is_bot_mentioned():
    raw = '{"text":"@Claude hi","mentions":[{"open_id":"ou_bot123","name":"Claude"}]}'
    assert _is_bot_mentioned(raw, "ou_bot123") is True
    assert _is_bot_mentioned(raw, "ou_other") is False
    assert _is_bot_mentioned('{"text":"hello"}', "ou_bot123") is False
    assert _is_bot_mentioned("", "ou_bot123") is False
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_should_respond.py -v
```

- [ ] **Step 4: Commit**

```bash
git add cc_feishu_bridge/feishu/should_respond.py tests/test_should_respond.py
git commit -m "feat(should_respond): add should_respond with mention/open mode support"
```

---

## Task 6: ClaudeIntegrationPool

**Files:**
- Create: `cc_feishu_bridge/claude/integration_pool.py`
- Create: `tests/test_integration_pool.py`

### 实现

- [ ] **Step 1: ClaudeIntegrationPool**

```python
# cc_feishu_bridge/claude/integration_pool.py
"""ClaudeIntegration instance pool — one Integration per session_key."""
from __future__ import annotations

import logging
import time
from typing import Optional

from cc_feishu_bridge.claude.integration import ClaudeIntegration

logger = logging.getLogger(__name__)


class ClaudeIntegrationPool:
    """Pool of ClaudeIntegration instances, one per session_key.

    Uses LRU eviction when max_size is reached.
    """

    def __init__(self, max_size: int = 10, **integration_kwargs):
        self._pool: dict[str, ClaudeIntegration] = {}
        self._last_used: dict[str, float] = {}  # session_key -> last access timestamp
        self._max_size = max_size
        self._integration_kwargs = integration_kwargs

    def get(self, session_key: str) -> ClaudeIntegration:
        """Get or create an Integration for session_key."""
        if session_key not in self._pool:
            self._ensure_capacity()
            integration = ClaudeIntegration(**self._integration_kwargs)
            self._pool[session_key] = integration
            logger.info(f"Created new Integration for session_key={session_key}")
        self._last_used[session_key] = time.monotonic()
        return self._pool[session_key]

    def _ensure_capacity(self) -> None:
        """Evict oldest Integration if at capacity."""
        if self._max_size <= 0:
            return  # unlimited
        if len(self._pool) < self._max_size:
            return
        oldest_key = min(self._last_used, key=self._last_used.get)
        del self._pool[oldest_key]
        del self._last_used[oldest_key]
        logger.info(f"Pool full — evicted session_key={oldest_key}")

    @property
    def size(self) -> int:
        return len(self._pool)

    @property
    def active_keys(self) -> list[str]:
        return list(self._pool.keys())
```

- [ ] **Step 2: 写测试**

```python
# tests/test_integration_pool.py
import pytest
from unittest.mock import patch
from cc_feishu_bridge.claude.integration_pool import ClaudeIntegrationPool


def test_pool_creates_integration():
    pool = ClaudeIntegrationPool(max_size=3, cli_path="claude")
    assert pool.size == 0

    int1 = pool.get("session_A")
    assert pool.size == 1
    assert int1 is not None

    int2 = pool.get("session_B")
    assert pool.size == 2


def test_pool_reuses_same_integration():
    pool = ClaudeIntegrationPool(cli_path="claude")
    int1 = pool.get("session_A")
    int2 = pool.get("session_A")
    assert int1 is int2
    assert pool.size == 1


def test_pool_lru_eviction():
    pool = ClaudeIntegrationPool(max_size=2, cli_path="claude")
    pool.get("session_A")
    pool.get("session_B")
    assert pool.size == 2

    # session_C triggers eviction of oldest (session_A)
    pool.get("session_C")
    assert pool.size == 2
    assert "session_A" not in pool.active_keys
    assert "session_B" in pool.active_keys
    assert "session_C" in pool.active_keys


def test_unlimited_pool():
    pool = ClaudeIntegrationPool(max_size=0, cli_path="claude")
    for i in range(20):
        pool.get(f"session_{i}")
    assert pool.size == 20
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_integration_pool.py -v
```

- [ ] **Step 4: Commit**

```bash
git add cc_feishu_bridge/claude/integration_pool.py tests/test_integration_pool.py
git commit -m "feat(pool): add ClaudeIntegrationPool with LRU eviction"
```

---

## Task 7: 回复 @ 机制 — send_message_by_open_id

**Files:**
- Modify: `cc_feishu_bridge/feishu/client.py`

### 实现

- [ ] **Step 1: 新增 send_text_by_open_id 方法**

在 `FeishuClient` 中添加：

```python
async def send_text_by_open_id(
    self,
    user_open_id: str,
    text: str,
    reply_to_message_id: str | None = None,
) -> str:
    """Send a text message to a specific user by open_id (for group @mention replies).

    In group chats, replying to a user mention requires sending to their open_id
    rather than the group chat_id.
    """
    import json
    import lark_oapi as lark
    client = self._get_client()

    if reply_to_message_id:
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .receive_id(user_open_id)
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
    else:
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(user_open_id)
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.create, request)

    if not response.success():
        raise RuntimeError(f"Failed to send message to open_id: {response.msg}")
    return response.data.message_id
```

**注意：** `send_text_reply` 方法目前用 `ReplyMessageRequest`（按 message_id 回复），需要同样支持 `receive_id_type="open_id"`。飞书的 `reply` 接口实际上也支持 `request_body.receive_id` 字段来指定接收者。

- [ ] **Step 2: Commit**

```bash
git add cc_feishu_bridge/feishu/client.py
git commit -m "feat(feishu): add send_text_by_open_id for group @mention replies"
```

---

## Task 8: MessageHandler — 集成 ChatLock + should_respond + Session 改造

**Files:**
- Modify: `cc_feishu_bridge/feishu/message_handler.py`
- Modify: `cc_feishu_bridge/main.py`

### 背景

这是整合性任务，把前面所有组件接入 message_handler 的消息处理流程。

### 实现

- [ ] **Step 1: MessageHandler 新增 ChatLockManager 和 should_respond**

在 `MessageHandler.__init__` 中新增：

```python
from cc_feishu_bridge.claude.chat_lock import ChatLockManager
from cc_feishu_bridge.feishu.should_respond import should_respond

class MessageHandler:
    def __init__(
        self,
        feishu_client: FeishuClient,
        authenticator: Authenticator,
        claude: ClaudeIntegration | ClaudeIntegrationPool,
        session_manager: SessionManager,
        memory_manager,
        validator: SecurityValidator,
        config: Config,
        approved_directory: str,
    ):
        # ... existing fields ...
        self.chat_lock = ChatLockManager(
            max_concurrent=getattr(config, "max_concurrent_chats", 10)
        )
        self.config = config
        self._bot_open_id = ""  # 从 feishu_client 获取
```

- [ ] **Step 2: 修改 _handle_message — 按 chat_type 决定 session_key**

```python
async def _handle_message(self, message: IncomingMessage) -> None:
    # Auth check（已有）
    if not self.authenticator.is_allowed(message.user_open_id):
        logger.info(f"Ignoring message from unauthorized user: {message.user_open_id}")
        return

    # 新增: should_respond 检查
    if not should_respond(message, self.config, self._bot_open_id):
        logger.debug(f"Ignoring message (not @mentioned in group, chat_mode=mention)")
        return

    # 新增: ChatLock 获取
    session_key = message.user_open_id if message.chat_type == "p2p" else message.chat_id
    lock_result = await self.chat_lock.acquire(session_key)
    if not lock_result.acquired:
        await self._safe_send(
            message.chat_id,
            message.message_id,
            "当前会话繁忙，请稍后再试 🛑",
        )
        return

    try:
        await self._process_message_with_session(message)
    finally:
        await self.chat_lock.release(session_key)
```

- [ ] **Step 3: 修改 _process_message_with_session — 用 session_key 查 session**

将原来 `get_active_session(message.user_open_id)` 改为：

```python
async def _process_message_with_session(self, message: IncomingMessage) -> None:
    session_key = message.user_open_id if message.chat_type == "p2p" else message.chat_id

    # 查找或创建 session
    session = self.sessions.get_active_session(session_key)
    if not session:
        project_path = self.config.resolve_project_path(
            message.chat_id, message.user_open_id
        )
        session = self.sessions.create_session(
            user_id=message.user_open_id,
            project_path=project_path,
            chat_type=message.chat_type,
            chat_id=message.chat_id if message.chat_type == "group" else None,
        )

    sdk_session_id = session.sdk_session_id if session else None
    # ... 后续 query 逻辑不变 ...
```

- [ ] **Step 4: 修改 _safe_send — 群聊时 @提问者**

在群聊场景（`message.chat_type == "group"`），`_safe_send` 需要用 `open_id` 类型发送，让飞书展示 @username：

```python
async def _safe_send(
    self,
    chat_id: str,
    reply_to_message_id: str,
    text: str,
    log_reply: bool = True,
    message: IncomingMessage | None = None,
) -> None:
    # 群聊时，使用 open_id 类型回复（@提问者）
    if message and message.chat_type == "group":
        try:
            await self.feishu.send_text_by_open_id(
                user_open_id=message.user_open_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
            return
        except Exception as e:
            logger.warning(f"send_text_by_open_id failed, falling back: {e}")
            # 降级到普通 reply
    # P2P 或降级路径：原有 reply 逻辑
    await self._do_safe_send(chat_id, reply_to_message_id, text, log_reply)
```

- [ ] **Step 5: 修改 main.py — 传入 ClaudeIntegrationPool**

在 `create_handler` 中：

```python
from cc_feishu_bridge.claude.integration_pool import ClaudeIntegrationPool

def create_handler(config, data_dir: str) -> MessageHandler:
    # ...
    claude_pool = ClaudeIntegrationPool(
        max_size=getattr(config, "max_concurrent_chats", 10),
        cli_path=config.claude.cli_path,
        max_turns=config.claude.max_turns,
        approved_directory=config.claude.approved_directory,
    )
    handler = MessageHandler(
        feishu_client=feishu,
        authenticator=auth,
        claude=claude_pool,  # 替换原来的单个 ClaudeIntegration
        session_manager=session_manager,
        memory_manager=memory_manager,
        validator=validator,
        config=config,
        approved_directory=config.claude.approved_directory,
    )
    return handler
```

- [ ] **Step 6: Commit**

```bash
git add cc_feishu_bridge/feishu/message_handler.py cc_feishu_bridge/main.py
git commit -m "feat(message_handler): integrate ChatLock, should_respond, and session_key routing"
```

---

## Task 9: 端到端联调

**Files:**
- Modify: `tests/` 下相关测试

### 验证场景

1. **P2P 场景** — 用户私聊 bot，bot 响应，session_key = user_open_id
2. **群聊 mention 模式** — 群里 @bot，bot 响应并 @提问者；未 @bot 则忽略
3. **群聊 open 模式** — 群里任意消息都触发 bot 响应

### 测试

- [ ] **Step 1: 验证 tests/test_session_manager.py 全部通过**

```bash
pytest tests/test_session_manager.py -v
```

- [ ] **Step 2: 验证 tests/test_chat_lock.py 全部通过**

```bash
pytest tests/test_chat_lock.py -v
```

- [ ] **Step 3: 验证 tests/test_integration_pool.py 全部通过**

```bash
pytest tests/test_integration_pool.py -v
```

- [ ] **Step 4: 验证 tests/test_should_respond.py 全部通过**

```bash
pytest tests/test_should_respond.py -v
```

- [ ] **Step 5: 验证 tests/test_ws_client.py 全部通过**

```bash
pytest tests/test_ws_client.py -v
```

- [ ] **Step 6: 端到端手动测试（根据实际飞书群验证）**

```
测试步骤：
1. 在配置中添加一个测试群 chat_id，chat_mode=mention
2. 在群里发一条不带 @ 的消息 → bot 不响应
3. 在群里发一条带 @ 的消息 → bot 响应并 @ 回复
4. 另开一个群 chat_id，chat_mode=open
5. 在 open 群里发任意消息 → bot 都响应
6. P2P 私聊 → bot 正常响应
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test: add end-to-end tests for multi-user and group chat support"
```

---

## 依赖关系总结

```
Task 1 (Session Manager) ──┐
                          ├── Task 8 (MessageHandler)
Task 2 (Config) ────────┤
                          │
Task 3 (ChatLock) ───────┤
                          │
Task 4 (ws_client) ──────┤
                          │
Task 5 (should_respond) ──┤
                          │
Task 6 (IntegrationPool) ─┘
                          │
Task 7 (send by open_id) ─┘
```

Task 7 独立，可并行。Task 1-6 完成后才能集成到 Task 8。
