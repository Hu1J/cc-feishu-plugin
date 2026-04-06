"""Memory MCP tools — 10 tools, one per /memory command."""
from __future__ import annotations

import threading

from cc_feishu_bridge.claude.memory_manager import MemoryManager


def _fmt_pref(p) -> str:
    return "\n".join([
        f"[用户偏好] **{p.title}**",
        f"  {p.content}",
        f"  关键词: {p.keywords}",
        f"  ID: `{p.id}`",
    ])


def _fmt_proj(m) -> str:
    proj = m.project_path or "(未知项目)"
    return "\n".join([
        f"[项目记忆] **{m.title}**",
        f"  {m.content}",
        f"  关键词: {m.keywords}",
        f"  项目: {proj}",
        f"  ID: `{m.id}`",
    ])


def _build_memory_mcp_server():
    from claude_agent_sdk import tool, create_sdk_mcp_server

    # ── user ──────────────────────────────────────────────────────────────────

    @tool(
        "MemoryAddUser",
        "新增一条用户偏好（按飞书用户隔离，user_open_id 来自当前会话）。title + content + keywords 三样必填，关键词用逗号分隔。",
        {"title": str, "content": str, "keywords": str, "user_open_id": str},
    )
    async def memory_add_user(args: dict) -> dict:
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        keywords = args.get("keywords", "").strip()
        user_open_id = args.get("user_open_id", "").strip()
        if not title or not content or not keywords:
            return {"content": [{"type": "text", "text": "title、content、keywords 三样必填"}], "is_error": True}
        mm = MemoryManager()
        try:
            p = mm.add_preference(user_open_id, title, content, keywords)
        except ValueError as e:
            return {"content": [{"type": "text", "text": f"输入过长：{e}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"✅ 用户偏好已保存\n\n{_fmt_pref(p)}"}]}

    @tool(
        "MemoryDeleteUser",
        "删除指定 ID 的用户偏好。",
        {"id": str},
    )
    async def memory_delete_user(args: dict) -> dict:
        mm = MemoryManager()
        ok = mm.delete_preference(args["id"])
        if ok:
            return {"content": [{"type": "text", "text": f"🗑️ 用户偏好 {args['id']} 已删除。"}]}
        return {"content": [{"type": "text", "text": f"未找到 id={args['id']} 的用户偏好"}], "is_error": True}

    @tool(
        "MemoryUpdateUser",
        "更新指定 ID 的用户偏好。title + content + keywords 三样必填，关键词用逗号分隔。",
        {"id": str, "title": str, "content": str, "keywords": str},
    )
    async def memory_update_user(args: dict) -> dict:
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        keywords = args.get("keywords", "").strip()
        if not title or not content or not keywords:
            return {"content": [{"type": "text", "text": "title、content、keywords 三样必填"}], "is_error": True}
        mm = MemoryManager()
        ok = mm.update_preference(args["id"], title, content, keywords)
        if ok:
            return {"content": [{"type": "text", "text": f"✅ 用户偏好 {args['id']} 已更新。"}]}
        return {"content": [{"type": "text", "text": f"未找到 id={args['id']} 的用户偏好"}], "is_error": True}

    @tool(
        "MemoryListUser",
        "列出当前用户的所有偏好（按飞书 user_open_id 隔离）。",
        {"user_open_id": str},
    )
    async def memory_list_user(args: dict) -> dict:
        user_open_id = args.get("user_open_id", "").strip()
        mm = MemoryManager()
        prefs = mm.get_preferences_by_user(user_open_id) if user_open_id else mm.get_all_preferences()
        if not prefs:
            return {"content": [{"type": "text", "text": "📭 暂无用户偏好记录。"}]}
        lines = [f"👤 用户偏好（共 {len(prefs)} 条）\n"]
        for p in prefs:
            lines.append(_fmt_pref(p))
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "MemorySearchUser",
        "搜索用户偏好（全文检索）。按飞书 user_open_id 隔离。",
        {"query": str, "user_open_id": str},
    )
    async def memory_search_user(args: dict) -> dict:
        query = args.get("query", "").strip()
        user_open_id = args.get("user_open_id", "").strip()
        if not query:
            return {"content": [{"type": "text", "text": "查询词不能为空"}], "is_error": True}
        mm = MemoryManager()
        results = mm.search_preferences(query, user_open_id=user_open_id, limit=5)
        if not results:
            return {"content": [{"type": "text", "text": f"未找到与「{query}」相关的用户偏好。"}]}
        lines = [f"🔍 用户偏好搜索结果（共 {len(results)} 条）\n"]
        for p in results:
            lines.append(_fmt_pref(p))
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ── proj ─────────────────────────────────────────────────────────────────

    @tool(
        "MemoryAddProj",
        "新增一条项目记忆（语义搜索，按项目隔离）。title + content + keywords 三样必填，关键词用逗号分隔。",
        {"project_path": str, "title": str, "content": str, "keywords": str},
    )
    async def memory_add_proj(args: dict) -> dict:
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        keywords = args.get("keywords", "").strip()
        project_path = args.get("project_path", "").strip()
        if not title or not content or not keywords:
            return {"content": [{"type": "text", "text": "title、content、keywords 三样必填"}], "is_error": True}
        if not project_path:
            return {"content": [{"type": "text", "text": "project_path 不能为空"}], "is_error": True}
        mm = MemoryManager()
        try:
            m = mm.add_project_memory(project_path, title, content, keywords)
        except ValueError as e:
            return {"content": [{"type": "text", "text": f"输入过长：{e}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"✅ 项目记忆已保存\n\n{_fmt_proj(m)}"}]}

    @tool(
        "MemoryDeleteProj",
        "删除指定 ID 的项目记忆（SQLite + qmd 同步删除）。",
        {"id": str},
    )
    async def memory_delete_proj(args: dict) -> dict:
        mm = MemoryManager()
        ok = mm.delete_project_memory(args["id"])
        if ok:
            return {"content": [{"type": "text", "text": f"🗑️ 项目记忆 {args['id']} 已删除。"}]}
        return {"content": [{"type": "text", "text": f"未找到 id={args['id']} 的项目记忆"}], "is_error": True}

    @tool(
        "MemoryUpdateProj",
        "更新指定 ID 的项目记忆（语义搜索，按项目隔离）。title + content + keywords 三样必填，关键词用逗号分隔。",
        {"id": str, "title": str, "content": str, "keywords": str},
    )
    async def memory_update_proj(args: dict) -> dict:
        title = args.get("title", "").strip()
        content = args.get("content", "").strip()
        keywords = args.get("keywords", "").strip()
        if not title or not content or not keywords:
            return {"content": [{"type": "text", "text": "title、content、keywords 三样必填"}], "is_error": True}
        mm = MemoryManager()
        ok = mm.update_project_memory(args["id"], title, content, keywords)
        if ok:
            return {"content": [{"type": "text", "text": f"✅ 项目记忆 {args['id']} 已更新。"}]}
        return {"content": [{"type": "text", "text": f"未找到 id={args['id']} 的项目记忆"}], "is_error": True}

    @tool(
        "MemoryListProj",
        "列出指定项目下所有项目记忆（语义搜索，按项目隔离）。",
        {"project_path": str},
    )
    async def memory_list_proj(args: dict) -> dict:
        from cc_feishu_bridge.claude.qmd_adapter import get_qmd_adapter

        project_path = args.get("project_path", "").strip()
        if not project_path:
            return {"content": [{"type": "text", "text": "project_path 不能为空"}], "is_error": True}

        adapter = get_qmd_adapter()
        if adapter.is_available():
            docs = adapter.list_memories(project_path)
            if not docs:
                return {"content": [{"type": "text", "text": "📭 暂无项目记忆记录。"}]}
            lines = [f"📁 项目记忆（共 {len(docs)} 条）\n"]
            for doc in docs:
                preview = doc.content[:100].replace("\n", " ")
                lines.append(f"\n**{doc.title}**")
                lines.append(f"  {preview}...")
                lines.append(f"  ID: `{doc.memory_id}`")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        # Fallback to SQLite
        mm = MemoryManager()
        mems = mm.get_project_memories(project_path)
        if not mems:
            return {"content": [{"type": "text", "text": "📭 暂无项目记忆记录（qmd 不可用，降级模式）。"}]}
        lines = [f"📁 项目记忆（共 {len(mems)} 条，降级模式）\n"]
        for m in mems:
            lines.append(_fmt_proj(m))
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "MemorySearchProj",
        "搜索项目记忆（语义+关键词混合搜索）。按项目隔离，只搜当前项目。",
        {"query": str, "project_path": str},
    )
    async def memory_search_proj(args: dict) -> dict:
        from cc_feishu_bridge.claude.qmd_adapter import get_qmd_adapter

        query = args.get("query", "").strip()
        project_path = args.get("project_path", "").strip()
        if not query or not project_path:
            return {"content": [{"type": "text", "text": "query 和 project_path 不能为空"}], "is_error": True}

        adapter = get_qmd_adapter()
        if adapter.is_available():
            docs = adapter.search(query, project_path, limit=5)
            if not docs:
                return {"content": [{"type": "text", "text": f"未找到与「{query}」相关的项目记忆。"}]}
            result_text = adapter.format_results(docs)
            return {"content": [{"type": "text", "text": f"🔍 项目记忆搜索结果\n\n{result_text}"}]}

        # Fallback to SQLite FTS5
        mm = MemoryManager()
        results = mm.search_project_memories(query, project_path, limit=5)
        if not results:
            return {"content": [{"type": "text", "text": f"未找到与「{query}」相关的项目记忆（qmd 不可用，降级关键词搜索也未命中）。"}]}
        lines = [f"🔍 项目记忆搜索结果（共 {len(results)} 条，降级模式）\n"]
        for r in results:
            lines.append(_fmt_proj(r.memory))
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    # ── register ─────────────────────────────────────────────────────────────
    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[
            memory_add_user,
            memory_delete_user,
            memory_update_user,
            memory_list_user,
            memory_search_user,
            memory_add_proj,
            memory_delete_proj,
            memory_update_proj,
            memory_list_proj,
            memory_search_proj,
        ],
    )


_mcp_server = None
_mcp_server_lock = threading.Lock()


def get_memory_mcp_server():
    global _mcp_server
    if _mcp_server is None:
        with _mcp_server_lock:
            if _mcp_server is None:  # 双重检查
                _mcp_server = _build_memory_mcp_server()
    return _mcp_server
