# 飞书多用户 + 群聊支持 设计方案

## 背景

cc-feishu-bridge 目前仅支持飞书单用户 P2P 会话。本次迭代目标：支持多用户接入和群聊场景，参考飞书官方 OpenClaw 插件的交互模式，实现消息隔离、并发调度和分层配置。

---

## 一、架构概览

### Session 隔离设计

| 场景 | session key | 说明 |
|------|------------|------|
| P2P 私聊 | `user_open_id` | 一对一隔离 |
| 群聊 | `chat_id` | 整群共享一个 SDK session，所有成员消息顺序进入同一对话 |

**关键原则：** 同一群内多个用户协作，消息上下文必须共享；不同群/P2P 之间完全隔离。

### Chat ID 锁调度器

```
消息到达 → 解析 session_key (chat_id 或 user_open_id)
         → ChatLockManager.acquire(session_key)
           ├── 无锁 → 获取锁 → 执行业务逻辑 → 释放锁
           ├── 有锁 → 回复"忙碌，稍后再试"
         → 执行完释放锁
```

- 同 chat 串行，避免同一会话内消息乱序
- 跨 chat 并发，不同群/P2P 互不阻塞
- 可配置 `max_concurrent_chats` 限制全局并发上限

---

## 二、消息接收层

### 群聊消息接收

当前 `ws_client.py` 仅注册 `p2_im_message_receive_v1`（P2P）。群聊消息复用同一事件类型，飞书事件结构中 `chat_type` 字段区分 P2P/群聊。

### @bot 触发判断

```python
def should_respond(message: IncomingMessage, config: ChatConfig) -> bool:
    if message.chat_type == "p2p":
        return True

    # 群聊：检查 chat_mode
    mode = config.get_chat_mode(message.chat_id)  # mention 或 open
    if mode == "open":
        return True

    # mention 模式：检查是否 @bot
    content = json.loads(message.raw_content)
    mentions = content.get("mentions", [])
    bot_open_id = get_bot_open_id()
    return any(m.get("open_id") == bot_open_id for m in mentions)
```

### 配置化触发模式

```yaml
chat_modes:
  default: mention              # 全局默认：需要 @ 才响应；open = 开放互动
  # 可按 chat_id 覆盖
```

---

## 三、分层配置设计

### 配置结构

```yaml
feishu: ...
claude: ...
auth: ...
proactive: ...
storage: ...

# 群聊/用户配置
chat_modes:
  default: mention

chat_overrides:                # 按 chat_id（群）单独配置
  "och_群Aid":
    chat_mode: open
    project_path: ~/projects/frontend
  "och_群Bid":
    chat_mode: mention
    project_path: ~/projects/backend

user_overrides:                # 按 user_open_id（P2P）单独配置
  "ou_用户C":
    project_path: ~/projects/backend
    max_turns: 100
```

### 配置查询优先级

```
具体 chat_id 覆盖 > 具体 user_open_id 覆盖 > 全局默认
```

完全向后兼容——不填新增字段时，使用现有全局行为。

---

## 四、Session Manager 改造

### Session Key 变更

```python
# 变更前
get_active_session(user_open_id)

# 变更后
get_active_session(session_key)           # session_key = user_open_id (p2p) 或 chat_id (group)
```

### Session 创建/查找

```python
def get_or_create_session(message: IncomingMessage, config: ChatConfig) -> Session:
    if message.chat_type == "p2p":
        session_key = message.user_open_id
    else:
        session_key = message.chat_id

    session = get_active_session(session_key)
    if not session:
        session = create_session(
            session_id=session_key,
            user_id=message.user_open_id,
            project_path=config.resolve_project_path(message.chat_id),
        )
    return session
```

### DB Schema

```sql
-- sessions 表增加 chat_type 列
ALTER TABLE sessions ADD COLUMN chat_type TEXT;
```

---

## 五、Claude 实例池

### Integration Pool

```python
class ClaudeIntegrationPool:
    def __init__(self, max_size: int = 10):
        self._pool: dict[str, ClaudeIntegration] = {}
        self._max_size = max_size

    def get(self, session_key: str) -> ClaudeIntegration:
        if session_key not in self._pool:
            if len(self._pool) >= self._max_size:
                oldest = min(self._pool, key=lambda k: self._pool[k]._last_used)
                del self._pool[oldest]
            self._pool[session_key] = ClaudeIntegration(...)
        return self._pool[session_key]
```

### 完整消息流程

```
消息到达
  → should_respond() 判断是否响应（根据 chat_mode 配置）
  → ChatLockManager.acquire(chat_id)
       ├── False → 回复"忙碌，稍后再试"
       └── True
            → get_or_create_session(message) 获取 Session
            → ClaudeIntegrationPool.get(session_key).query(...)
            → ChatLockManager.release(chat_id)
```

---

## 六、消息回复 @ 机制

### 群聊回复 @ 提问者

每条消息携带 `user_open_id`，通过 `receive_id_type="open_id"` 精准 @：

```python
async def send_reply(chat_id: str, user_open_id: str, text: str, reply_to: str):
    await feishu.send_message(
        receive_id_type="open_id",
        receive_id=user_open_id,
        msg_type="text",
        content=json.dumps({"text": text}),
    )
```

- 群聊：bot 回复 @提问者，其他成员不被刷屏
- P2P：直接发送到 chat_id，无需 @

---

## 七、错误处理与降级

| 场景 | 处理方式 |
|------|---------|
| ChatLock 获取失败（并发满载） | 回复"当前会话繁忙，请稍后再试 🛑" |
| SDK query 异常 | 记录日志，回复"Claude 响应失败，请稍后再试"，确保 release 不漏 |
| mention 模式下未被 @ | 静默忽略，不回复 |
| `max_concurrent_chats: 0` | 无限制（资源充足时） |

---

## 八、实现顺序

1. **Session Manager 改造** — 核心数据结构变更，其他模块都依赖它
2. **分层配置读取** — config 解析层，支持 chat_mode 按 chat_id 查询
3. **ChatLockManager** — 并发调度基础组件
4. **ws_client 消息接收** — 确认群聊消息能正常解析
5. **should_respond + @ 判断** — 消息过滤
6. **ClaudeIntegrationPool** — 实例池
7. **回复 @ 机制** — send_message 支持 open_id 类型
8. **端到端联调** — P2P、群聊 mention、群聊 open 三场景验证
