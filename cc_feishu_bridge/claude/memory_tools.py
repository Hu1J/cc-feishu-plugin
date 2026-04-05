"""Memory MCP tools for Claude SDK."""
from __future__ import annotations

from cc_feishu_bridge.claude.memory_manager import MemoryManager, MemoryEntry


_TYPE_LABELS = {
    "problem_solution": "问题解决",
    "project_context": "项目上下文",
    "user_preference": "用户偏好",
}


def _format_entry_text(entry: MemoryEntry) -> str:
    """Format a single entry as plain text (for MemoryAdd confirmation)."""
    label = _TYPE_LABELS.get(entry.type, entry.type)
    lines = [f"[{label}] **{entry.title}**"]
    if entry.problem:
        lines.append(f"  问题: {entry.problem}")
    if entry.root_cause:
        lines.append(f"  根因: {entry.root_cause}")
    lines.append(f"  解决: {entry.solution}")
    if entry.tags:
        lines.append(f"  标签: {entry.tags}")
    lines.append(f"  ID: `{entry.id}`  使用次数: {entry.use_count}")
    return "\n".join(lines)


def _entries_to_md_table(entries: list[MemoryEntry]) -> str:
    """Format memory entries as a markdown table."""
    if not entries:
        return ""
    header = "| # | 类型 | 标题 | 问题 | 解决 | ID | 使用次数 |"
    separator = "|---|---|---|---|---|---|---|"
    rows = []
    for i, e in enumerate(entries, 1):
        label = _TYPE_LABELS.get(e.type, e.type)
        # Truncate long fields for table cells
        problem = (e.problem or "")[:40].replace("|", "\\|").replace("\n", " ")
        solution = (e.solution or "")[:60].replace("|", "\\|").replace("\n", " ")
        rows.append(
            f"| {i} | {label} | **{e.title}** | {problem} | {solution} | `{e.id}` | {e.use_count} |"
        )
    return "\n".join([header, separator] + rows)


def _build_memory_mcp_server():
    """Build the memory MCP server with all memory management tools."""
    from claude_agent_sdk import tool, create_sdk_mcp_server

    # ── MemorySearch ───────────────────────────────────────────────────────────

    @tool(
        "MemorySearch",
        (
            "搜索本地记忆库，查找之前遇到过的问题和解决方案。"
            "当你遇到报错、失败或不熟悉的问题时，优先使用此工具查询本地记忆库。"
            "返回结果包含问题描述、根因和已知解决方案。"
        ),
        {"query": str, "project_path": str | None},
    )
    async def memory_search(args: dict) -> dict:
        query = args.get("query", "")
        project_path = args.get("project_path")

        if not query.strip():
            return {
                "content": [{"type": "text", "text": "查询词不能为空。"}],
                "is_error": True,
            }

        manager = MemoryManager()
        results = manager.search(query, project_path=project_path, limit=5)

        if not results:
            return {
                "content": [{"type": "text", "text": f"未找到与「{query}」相关的记忆。"}],
            }

        table = _entries_to_md_table([r.entry for r in results])
        return {
            "content": [{"type": "text", "text": f"**记忆搜索结果（{len(results)} 条）**\n\n{table}"}],
        }

    # ── MemoryList ────────────────────────────────────────────────────────────

    @tool(
        "MemoryList",
        (
            "列出当前项目相关的记忆条目（项目上下文和用户偏好）。"
            "返回记忆的 ID、标题、类型、使用次数等信息。"
        ),
        {"project_path": str | None},
    )
    async def memory_list(args: dict) -> dict:
        project_path = args.get("project_path")

        manager = MemoryManager()
        entries = manager.get_by_project(project_path=project_path)

        if not entries:
            return {
                "content": [{"type": "text", "text": "暂无记忆记录。"}],
            }

        table = _entries_to_md_table(entries)
        return {
            "content": [{"type": "text", "text": f"**记忆列表（{len(entries)} 条）**\n\n{table}"}],
        }

    # ── MemoryAdd ─────────────────────────────────────────────────────────────

    @tool(
        "MemoryAdd",
        (
            "向本地记忆库添加一条新的记忆条目。"
            "适用于记录用户偏好、项目配置、已知问题和解决方案等。"
        ),
        {
            "type": str,  # problem_solution | project_context | user_preference
            "title": str,
            "solution": str,
            "problem": str | None,
            "root_cause": str | None,
            "tags": str | None,
            "project_path": str | None,
        },
    )
    async def memory_add(args: dict) -> dict:
        entry_type = args.get("type", "project_context")
        if entry_type not in ("problem_solution", "project_context", "user_preference"):
            return {
                "content": [{"type": "text", "text": f"无效的 type：{entry_type}，必须是 problem_solution / project_context / user_preference"}],
                "is_error": True,
            }

        entry = MemoryEntry(
            type=entry_type,
            title=args.get("title", "")[:60],
            solution=args.get("solution", ""),
            problem=args.get("problem"),
            root_cause=args.get("root_cause"),
            tags=args.get("tags"),
            project_path=args.get("project_path"),
        )
        manager = MemoryManager()
        manager.add(entry)

        return {
            "content": [{"type": "text", "text": f"✅ 记忆已保存（ID: {entry.id}）\n\n{_format_entry_text(entry)}"}],
        }

    # ── MemoryDelete ──────────────────────────────────────────────────────────

    @tool(
        "MemoryDelete",
        "删除指定 ID 的记忆条目（软删除）。",
        {"memory_id": str},
    )
    async def memory_delete(args: dict) -> dict:
        memory_id = args.get("memory_id", "")

        manager = MemoryManager()
        ok = manager.delete(memory_id)

        if ok:
            return {
                "content": [{"type": "text", "text": f"🗑️ 记忆 {memory_id} 已删除。"}],
            }
        return {
            "content": [{"type": "text", "text": f"未找到 ID 为 {memory_id} 的记忆。"}],
            "is_error": True,
        }

    # ── MemoryClear ───────────────────────────────────────────────────────────

    @tool(
        "MemoryClear",
        "删除当前项目的所有项目上下文记忆（仅删除 project_context 类型，不删除 user_preference 和 problem_solution）。",
        {"project_path": str | None},
    )
    async def memory_clear(args: dict) -> dict:
        project_path = args.get("project_path")

        manager = MemoryManager()
        entries = manager.get_by_project(project_path=project_path, type_filter=["project_context"])
        count = sum(1 for e in entries if manager.delete(e.id))

        return {
            "content": [{"type": "text", "text": f"🧹 已清除 {count} 条项目上下文记忆。"}],
        }

    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[memory_search, memory_list, memory_add, memory_delete, memory_clear],
    )


# Lazily-created server instance (shared across queries)
_mcp_server = None


def get_memory_mcp_server():
    """Get the singleton memory MCP server."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = _build_memory_mcp_server()
    return _mcp_server


MEMORY_SYSTEM_GUIDANCE = """
当你遇到以下情况时，请优先使用 MemorySearch 工具查询本地记忆库：
- 遇到报错（error）、构建失败（build failed）、测试失败（test failed）
- 遇到之前似乎见过的问题
- 用户提到"之前也是这样"、"以前解决过"

MemorySearch 会返回本地记忆库中相关的记录，格式为【问题 + 解决方案】。
请优先参考返回的解决方案，如果不能直接解决，再自行研究。

也可以使用 MemoryList、MemoryAdd、MemoryDelete、MemoryClear 工具来管理记忆。
"""
