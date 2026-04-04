"""彩色 diff 渲染 — Edit/Write 工具专用。"""
from __future__ import annotations
import json

# 飞书 plain_text 支持的颜色
COLOR_RED = "red"
COLOR_GREEN = "green"    # 注：浅色主题下偏淡，可调整
COLOR_GREY = "grey"
COLOR_BLUE = "blue"
COLOR_DEFAULT = "default"

MAX_DIFF_LINES = 50       # 超过此行数截断
CONTEXT_LINES = 3        # 截断时保留首尾上下文行数
MAX_CARD_LINES = 30      # 单次卡片最大行数


class DiffLine:
    """一行 diff 结果。"""
    __slots__ = ("type", "content")   # type: "deletion" | "insertion" | "context"

    def __init__(self, type: str, content: str):
        self.type = type
        self.content = content

    def color(self) -> str:
        if self.type == "deletion":
            return COLOR_RED
        elif self.type == "insertion":
            return COLOR_GREEN
        return COLOR_GREY

    def prefix(self) -> str:
        if self.type == "deletion":
            return "- "
        elif self.type == "insertion":
            return "+ "
        return "  "


def colorize_diff(old_string: str, new_string: str) -> list[DiffLine]:
    """对 old_string 和 new_string 做行级 LCS，返回带类型的行列表。"""
    if not old_string and not new_string:
        return []
    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()
    diff = _lcs_diff(old_lines, new_lines)

    # 截断：超过 MAX_DIFF_LINES 时，首尾各保留 CONTEXT_LINES 行上下文
    if len(diff) > MAX_DIFF_LINES:
        diff = _truncate_diff(diff)

    return diff


def _lcs_diff(old_lines: list[str], new_lines: list[str]) -> list[DiffLine]:
    """计算 LCS 并返回行级 diff。"""
    m, n = len(old_lines), len(new_lines)
    # LCS 长度矩阵
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if old_lines[i - 1] == new_lines[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # 回溯找 diff
    result = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and old_lines[i - 1] == new_lines[j - 1]:
            result.append(DiffLine("context", old_lines[i - 1]))
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            result.append(DiffLine("insertion", new_lines[j - 1]))
            j -= 1
        else:
            result.append(DiffLine("deletion", old_lines[i - 1]))
            i -= 1

    result.reverse()
    return result


def _truncate_diff(diff: list[DiffLine]) -> list[DiffLine]:
    """截断过长的 diff，保留首尾上下文。"""
    if len(diff) <= MAX_DIFF_LINES:
        return diff
    # 找第一个和最后一个变化行（不是 context 的行）
    first_change = next((i for i, d in enumerate(diff) if d.type != "context"), 0)
    last_change = next((len(diff) - 1 - i for i, d in enumerate(reversed(diff)) if d.type != "context"), len(diff) - 1)

    # 保留前 CONTEXT_LINES 行上下文
    keep_head = diff[:CONTEXT_LINES]
    keep_tail = diff[-CONTEXT_LINES:] if len(diff) >= CONTEXT_LINES else diff

    return keep_head + [DiffLine("context", "...")] + keep_tail


def format_edit_card(file_path: str, diff_lines: list[DiffLine]) -> dict:
    """构建 Edit 工具的飞书彩色 diff 卡片。"""
    header_title = f"Edit — `{file_path}`"
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": header_title,
                "text_color": COLOR_BLUE,
            }
        },
        {
            "tag": "div",
            "fields": [
                {
                    "text": {
                        "tag": "plain_text",
                        "content": _render_diff_lines(diff_lines),
                        "text_color": COLOR_DEFAULT,
                    }
                }
            ],
            "background_color": "#1e1e1e",
        }
    ]
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {"elements": elements},
    }


def format_write_card(file_path: str, content_lines: list[str]) -> dict:
    """构建 Write 工具的飞书全量绿色卡片。"""
    header_title = f"Write — `{file_path}`"
    diff_lines = [DiffLine("insertion", line) for line in content_lines]
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": header_title,
                "text_color": COLOR_BLUE,
            }
        },
        {
            "tag": "div",
            "fields": [
                {
                    "text": {
                        "tag": "plain_text",
                        "content": _render_diff_lines(diff_lines),
                        "text_color": COLOR_DEFAULT,
                    }
                }
            ],
            "background_color": "#1e1e1e",
        }
    ]
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {"elements": elements},
    }


def _render_diff_lines(diff_lines: list[DiffLine]) -> str:
    """将 DiffLine 列表渲染为带前缀的文本（用于 plain_text）。"""
    parts = []
    for d in diff_lines:
        parts.append(f"{d.prefix()}{d.content}")
    return "\n".join(parts)


# ----------------------------------------------------------------------
# 供 reply_formatter 使用的 marker
# ----------------------------------------------------------------------
class _DiffMarker:
    """通知 message_handler 此工具调用需要渲染彩色 diff 卡片。"""
    __slots__ = ("tool_name", "tool_input", "card")

    def __init__(self, tool_name: str, tool_input: str, card: dict):
        self.tool_name = tool_name
        self.tool_input = tool_input  # 原始 JSON 字符串
        self.card = card              # 预构建的飞书卡片 JSON


def build_edit_marker(tool_input_json: str) -> _DiffMarker:
    """从 Edit 工具的 tool_input JSON 构建 marker。"""
    data = json.loads(tool_input_json)
    file_path = data.get("file_path", "unknown")
    old_str = data.get("old_string", "")
    new_str = data.get("new_string", "")
    diff = colorize_diff(old_str, new_str)
    card = format_edit_card(file_path, diff)
    return _DiffMarker("Edit", tool_input_json, card)


def build_write_marker(tool_input_json: str) -> _DiffMarker:
    """从 Write 工具的 tool_input JSON 构建 marker。"""
    data = json.loads(tool_input_json)
    file_path = data.get("file_path", "unknown")
    content = data.get("content", "")
    lines = content.splitlines()
    # Write 过长时分块：每块 MAX_CARD_LINES 行
    if len(lines) <= MAX_CARD_LINES:
        return _DiffMarker("Write", tool_input_json, format_write_card(file_path, lines))
    # 多块：返回多个 marker
    chunks = [lines[i:i + MAX_CARD_LINES] for i in range(0, len(lines), MAX_CARD_LINES)]
    return [_DiffMarker("Write", tool_input_json, format_write_card(file_path, chunk)) for chunk in chunks]
