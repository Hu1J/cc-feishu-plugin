"""Memory MCP tools for Claude SDK."""
from __future__ import annotations

from cc_feishu_bridge.claude.memory_manager import MemoryManager


def _format_preference_text(pref) -> str:
    lines = [f"[用户偏好] **{pref.title}**"]
    lines.append(f"  {pref.content}")
    lines.append(f"  关键词: {pref.keywords}")
    lines.append(f"  ID: `{pref.id}`")
    return "\n".join(lines)


def _format_memory_text(mem) -> str:
    lines = [f"[项目记忆] **{mem.title}**"]
    lines.append(f"  {mem.content}")
    lines.append(f"  关键词: {mem.keywords}")
    lines.append(f"  项目: {mem.project_path}")
    lines.append(f"  ID: `{mem.id}`")
    return "\n".join(lines)


def _build_memory_mcp_server():
    """Build the memory MCP server with all memory management tools."""
    from claude_agent_sdk import tool, create_sdk_mcp_server

    @tool(
        "MemorySearch",
        (
            "搜索项目记忆库，查找之前遇到过的问题和解决方案。"
            "只搜当前项目（project_path）下的记忆，不搜用户偏好。"
            "返回结果包含标题、内容和关键词。"
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
        results = manager.search_project_memories(query, project_path=project_path or "", limit=5)

        if not results:
            return {
                "content": [{"type": "text", "text": f"未找到与「{query}」相关的记忆。"}],
            }

        lines = [f"**项目记忆搜索结果（{len(results)} 条）**", ""]
        for r in results:
            m = r.memory
            lines.append(f"[项目记忆] **{m.title}**")
            lines.append(f"  {m.content}")
            lines.append(f"  关键词: {m.keywords}")
            lines.append(f"  ID: `{m.id}`")
            lines.append("")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "MemoryAdd",
        (
            "向记忆库添加新条目。"
            "用户偏好存入 user_preferences（全局），项目记忆存入 project_memories（按项目隔离）。"
            "title、content、keywords 三样必填，缺一不可。"
        ),
        {
            "type": str,  # "user_preference" | "project_memory"
            "title": str,
            "content": str,
            "keywords": str,
            "project_path": str | None,
        },
    )
    async def memory_add(args: dict) -> dict:
        entry_type = args.get("type")
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        keywords = args.get("keywords", "").strip()
        project_path = args.get("project_path")

        if not title:
            return {"content": [{"type": "text", "text": "标题不能为空"}], "is_error": True}
        if not content:
            return {"content": [{"type": "text", "text": "内容不能为空"}], "is_error": True}
        if not keywords:
            return {"content": [{"type": "text", "text": "关键词不能为空"}], "is_error": True}

        manager = MemoryManager()

        if entry_type == "user_preference":
            pref = manager.add_preference(title, content, keywords)
            return {"content": [{"type": "text", "text": f"✅ 用户偏好已保存（ID: {pref.id}）\n\n{_format_preference_text(pref)}"}]}
        elif entry_type == "project_memory":
            if not project_path:
                return {"content": [{"type": "text", "text": "project_memory 需要传入 project_path"}], "is_error": True}
            mem = manager.add_project_memory(project_path, title, content, keywords)
            return {"content": [{"type": "text", "text": f"✅ 项目记忆已保存（ID: {mem.id}）\n\n{_format_memory_text(mem)}"}]}
        else:
            return {"content": [{"type": "text", "text": f"无效的 type：{entry_type}，必须是 user_preference 或 project_memory"}], "is_error": True}

    @tool(
        "MemoryDelete",
        "删除指定 ID 的项目记忆。",
        {"memory_id": str},
    )
    async def memory_delete(args: dict) -> dict:
        memory_id = args.get("memory_id", "")
        manager = MemoryManager()
        ok = manager.delete_project_memory(memory_id)
        if ok:
            return {"content": [{"type": "text", "text": f"🗑️ 记忆 {memory_id} 已删除。"}]}
        return {"content": [{"type": "text", "text": f"未找到 ID 为 {memory_id} 的记忆。"}], "is_error": True}

    @tool(
        "MemoryClear",
        "清空指定项目下所有项目记忆。",
        {"project_path": str | None},
    )
    async def memory_clear(args: dict) -> dict:
        project_path = args.get("project_path")
        if not project_path:
            return {"content": [{"type": "text", "text": "需要传入 project_path"}], "is_error": True}
        manager = MemoryManager()
        count = manager.clear_project_memories(project_path)
        return {"content": [{"type": "text", "text": f"🧹 已清除 {count} 条项目记忆。"}]}

    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[memory_search, memory_add, memory_delete, memory_clear],
    )


_mcp_server = None


def get_memory_mcp_server():
    """Get the singleton memory MCP server."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = _build_memory_mcp_server()
    return _mcp_server


MEMORY_SYSTEM_GUIDANCE = """
当你遇到以下情况时，请优先使用 MemorySearch 搜索项目记忆：
- 遇到报错（error）、构建失败（build failed）、测试失败（test failed）
- 遇到之前似乎见过的问题

添加记忆时，使用 MemoryAdd（title + content + keywords 三样必填）。
也可以使用 MemoryDelete、MemoryClear 工具管理记忆。
"""
