# 群聊场景下用户偏好注入规则 设计方案

## 背景

当前用户偏好注入逻辑是：无论 P2P 还是群聊，都会根据 `message.user_open_id` 注入对应用户的偏好。然而在群聊 `open` 模式（不艾特也回答）下，CC 回复的对象不一定是提问者本人，此时注入提问者偏好会导致响应内容不符合实际交互对象的预期。

本次改动明确群聊场景下用户偏好注入的判断规则。

---

## 一、注入判断原则

**核心原则：只有当用户明确在和 CC 互动时，才注入该用户的偏好。**

| 场景 | 是否注入偏好 | 说明 |
|------|-------------|------|
| P2P 私聊 | ✅ 注入 | 1:1 明确交互，用户就是在和 CC 对话 |
| 群聊 `mention` 模式，被艾特 | ✅ 注入 | 用户明确在和 CC 私聊 |
| 群聊 `open` 模式，被艾特 | ✅ 注入 | 用户明确在和 CC 私聊 |
| 群聊 `open` 模式，没艾特但 CC 仍响应 | ❌ 不注入 | 回复可能面向所有人，目标不明确 |

**判断依据：`should_respond()` 返回 `True` 且 `message.chat_type == "group"` 且 bot 被 @mentioned 时，注入偏好。**

---

## 二、关键判断流程

```
消息到达
  → should_respond() 返回 True？
      ├── False → 不响应（不注入偏好）
      └── True
           → chat_type == "group" 且未被 @mentioned？
                ├── 是（群聊 open 模式，未艾特）→ 不注入偏好
                └── 否（被艾特或 P2P）→ 注入偏好
```

---

## 三、代码修改点

### 3.1 修改位置

**文件：** `cc_feishu_bridge/feishu/message_handler.py`

**方法：** `_process_message_with_session()` 或 `_process_message()`

### 3.2 注入条件

当前代码（约 line 278-283）：

```python
system_prompt_append = (
    MEMORY_SYSTEM_GUIDE
    + FEISHU_FILE_GUIDE
    + self.memory_manager.inject_context(user_open_id=message.user_open_id)
)
```

修改为：

```python
# 判断是否应该注入用户偏好
should_inject = (
    message.chat_type == "p2p"
    or _is_bot_mentioned(message.raw_content, bot_open_id)
)

user_pref_context = (
    self.memory_manager.inject_context(user_open_id=message.user_open_id)
    if should_inject else ""
)

system_prompt_append = (
    MEMORY_SYSTEM_GUIDE
    + FEISHU_FILE_GUIDE
    + user_pref_context
)
```

其中 `_is_bot_mentioned()` 逻辑与 `should_respond.py` 中的一致，可复用或抽取为共享函数。

### 3.3 依赖修改

`should_respond()` 的判断结果需要在消息处理流程中向下传递，或者在构建 `system_prompt_append` 时重新计算 `_is_bot_mentioned()`。

推荐方案：在 `_process_message()` 中计算 `bot_was_mentioned` 并传递给 `_process_message_with_session()`。

---

## 四、测试场景

| # | 场景 | 预期行为 |
|---|------|---------|
| 1 | P2P 私聊 | 注入用户偏好 |
| 2 | 群聊 `mention` 模式，被艾特 | 注入用户偏好 |
| 3 | 群聊 `mention` 模式，未被艾特 | 不响应，不注入 |
| 4 | 群聊 `open` 模式，被艾特 | 注入用户偏好 |
| 5 | 群聊 `open` 模式，未被艾特但 CC 响应 | 不注入偏好 |

---

## 五、影响范围

- 仅影响 `message_handler.py` 中偏好注入的条件判断
- 不影响 `should_respond()` 的现有逻辑
- 不影响 Session Manager、ChatLock 等其他组件
