"""PPBExt-Memory 的 MCP server（stdio 传输，零依赖）。

把PPBExt-Memory包装为 MCP（Model Context Protocol）工具——任何支持 MCP 的 agent
客户端可直接调用。暴露六个工具：
  memory_ingest  —— 写入/更新记忆（ADD/UPDATE/NOOP 自动决策）
  memory_recall  —— 组装当前有效记忆（确定性顺序 + 前缀稳定性）
  memory_fold    —— 折叠失效（append-only 的 staleness 解）
  memory_list    —— 用户可见视图（审阅与治理）
  memory_delete  —— 用户删除（内容物理删除，仅留不含内容的事件）
  memory_audit   —— 删除审计导出（哈希链，可验证记录未被改动）

协议：JSON-RPC 2.0 over stdio（initialize / tools/list / tools/call）。
运行：python mcp_server.py（stdin/stdout 与客户端通信）
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from memorycore import (MemoryController, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, PromptComposer, audit_report,
                        collect_purge_events)

STORE = MemoryStore()
CTL = MemoryController(STORE)
COMPOSER = PromptComposer()
try:
    from decisioncore import DecisionCore  # 可选：启用审计
    CTL.dc = DecisionCore()
    _AUDIT = True
except ImportError:
    _AUDIT = False

TOOLS = [
    {
        "name": "memory_ingest",
        "description": "写入或更新一条记忆（自动决策 ADD/UPDATE/NOOP；"
                       "相似则折叠旧页后追加新页，重复则跳过）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "enum": ["fact", "preference", "decision", "lesson"]},
                "content": {"type": "string"},
                "provenance": {"type": "string",
                               "description": "来源标记（会话 id / 生成者）"},
            },
            "required": ["kind", "content"],
        },
    },
    {
        "name": "memory_recall",
        "description": "组装当前有效记忆（确定性顺序，返回前缀稳定性指标）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_fold",
        "description": "折叠一条记忆（声明失效但不删除，审计链保留）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["page_id", "reason"],
        },
    },
    {
        "name": "memory_list",
        "description": "列出全部记忆（用户可见视图：kind/内容/lifecycle/时间/来源），"
                       "供用户审阅与治理",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_folded": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "memory_delete",
        "description": "用户删除一条记忆（隐私优先：内容物理删除，仅保留不含内容的"
                       "删除事件以供审计）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "reason": {"type": "string", "default": "user_requested"},
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "memory_audit",
        "description": "导出删除审计（可验证）：不含内容的删除事件 + 哈希链校验。"
                       "chain_ok 说明记录是否被改动过；content_retained=false "
                       "说明审计未变相留存被删内容。chain_ok 基于全量事件计算，"
                       "events 只列出末尾 limit 条",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
]


def _call_tool(name: str, args: dict) -> dict:
    if name == "memory_ingest":
        act = CTL.ingest(PageKind(args["kind"]), args["content"],
                         provenance=args.get("provenance", ""))
        return {"op": act.op, "page_id": act.page_id,
                "audited": bool(act.decision_id)}
    if name == "memory_recall":
        folded = [p for p in STORE.pages if p.lifecycle == "folded"]
        r = COMPOSER.compose(STORE.active_pages(), folded_pages=folded)
        return {"memory": r.text, "pages_used": len(r.used_pages),
                "prefix_overlap": r.prefix_overlap, "stable": r.stable}
    if name == "memory_fold":
        act = CTL.fold(args["page_id"], reason=args["reason"])
        return {"op": act.op, "page_id": act.page_id}
    if name == "memory_list":
        include_folded = bool(args.get("include_folded", False))
        rows = []
        for pg in STORE.pages:
            if pg.supersedes and not include_folded:
                continue
            if pg.lifecycle == "folded" and not include_folded:
                continue
            rows.append({"page_id": pg.page_id, "kind": pg.kind,
                         "content": pg.content[:120], "lifecycle": pg.lifecycle,
                         "provenance": pg.provenance,
                         "created_at": pg.created_at})
        return {"n": len(rows), "pages": rows}
    if name == "memory_delete":
        out = STORE.purge(args["page_id"], reason=args.get("reason", "user_requested"))
        return out
    if name == "memory_audit":
        events = collect_purge_events(STORE.pages)
        rep = audit_report(events)          # 链校验基于全量事件
        limit = int(args.get("limit", 50))
        if limit > 0:
            rep["events"] = rep["events"][-limit:]
            rep["events_shown"] = len(rep["events"])
        return rep
    raise ValueError(f"unknown tool: {name}")


def handle(req: dict) -> dict | None:
    """JSON-RPC 2.0 处理。通知（无 id）返回 None。"""
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2026-06-18",
            "serverInfo": {"name": "ppbext-memory", "version": "0.2.0"},
            "capabilities": {"tools": {}}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params", {})
        try:
            out = _call_tool(params.get("name", ""), params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, ensure_ascii=False)}]}}
        except Exception as e:                      # noqa: BLE001
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"error: {e}"}],
                "isError": True}}
    # 未知方法
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
