"""PPBExt-Memory 的 MCP server（stdio 传输，零依赖）。

把记忆外挂包装为 MCP（Model Context Protocol）工具——任何支持 MCP 的 agent
客户端可直接调用。暴露三个工具：
  memory_ingest  —— 写入/更新记忆（ADD/UPDATE/NOOP 自动决策）
  memory_recall  —— 组装当前有效记忆（确定性顺序 + 前缀稳定性）
  memory_fold    —— 折叠失效（append-only 的 staleness 解）

协议：JSON-RPC 2.0 over stdio（initialize / tools/list / tools/call）。
运行：python mcp_server.py（stdin/stdout 与客户端通信）
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from memorycore import (MemoryController, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, PromptComposer)

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
