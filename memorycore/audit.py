"""删除审计的可验证输出格式（M4）。

用户可控层要能回答两个问题，且都不依赖对实现的信任：

  1. **内容确实删了吗** —— 审计记录里只有哈希，没有内容，所以"记录存在"不等于"内容留存"
  2. **审计记录本身被改过吗** —— 用哈希链：任一条被改动，其后所有 `this_hash` 都对不上

格式（每条事件）：

    {seq, ts, op, page_id, content_hash, reason, prev_hash, this_hash}
    this_hash = sha256(prev_hash | seq | op | page_id | content_hash | reason)

首条的 `prev_hash` 为创世值。**只记哈希不记内容**是刻意的取舍：
审计要能证明"删了哪一条"，但不能变相留存被删内容——否则删除只是名义上的。

纯确定性、零依赖。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

GENESIS = "0" * 16
HASH_LEN = 16

# 从记忆页文本中提取 purge 事件的格式（由 MemoryStore.purge 写出）
_PURGE_RE = re.compile(
    r"^\[PURGE\]\s+(?P<page_id>\S+)\s+content_hash=(?P<hash>\S+)\s+reason=(?P<reason>.*)$")


@dataclass
class AuditEvent:
    seq: int
    ts: float
    op: str                    # delete / purge / fold
    page_id: str
    content_hash: str
    reason: str = ""
    prev_hash: str = GENESIS
    this_hash: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def hash_content(content: str) -> str:
    """内容哈希（只留指纹，不留内容）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:HASH_LEN]


def _digest(prev_hash: str, seq: int, op: str, page_id: str,
            content_hash: str, reason: str) -> str:
    payload = f"{prev_hash}|{seq}|{op}|{page_id}|{content_hash}|{reason}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:HASH_LEN]


def append_event(events: list[AuditEvent], op: str, page_id: str,
                 content: str, reason: str = "", ts: float = 0.0) -> AuditEvent:
    """追加一条事件并把链接上（调用方只提供内容，哈希由本模块算）。"""
    prev = events[-1].this_hash if events else GENESIS
    seq = len(events)
    ch = hash_content(content)
    ev = AuditEvent(seq=seq, ts=ts, op=op, page_id=page_id,
                    content_hash=ch, reason=reason, prev_hash=prev)
    ev.this_hash = _digest(prev, seq, op, page_id, ch, reason)
    events.append(ev)
    return ev


def verify_chain(events: list[AuditEvent]) -> tuple[bool, str]:
    """逐条校验：序号连续、prev 衔接、自身哈希可复算。"""
    prev = GENESIS
    for i, e in enumerate(events):
        if e.seq != i:
            return False, f"序号断裂：第 {i} 条 seq={e.seq}"
        if e.prev_hash != prev:
            return False, f"第 {i} 条 prev_hash 与上一条不衔接"
        expect = _digest(prev, e.seq, e.op, e.page_id, e.content_hash, e.reason)
        if e.this_hash != expect:
            return False, f"第 {i} 条自身哈希不匹配（记录被改动）"
        prev = e.this_hash
    return True, ""


def collect_purge_events(pages) -> list[AuditEvent]:
    """从记忆页中收集 purge 事件（文本格式解析）。

    记忆层的 `purge` 会写出一条 `[PURGE] <page_id> content_hash=… reason=…` 的
    决策页。本函数按该格式解析并按写入顺序建链。

    说明：这是对既有文本格式的**兼容性解析**；若调用方能在删除时直接调用
    `append_event`，就不需要这一步（结构化路径更可靠）。
    """
    events: list[AuditEvent] = []
    for p in pages:
        m = _PURGE_RE.match((p.content or "").strip())
        if not m:
            continue
        prev = events[-1].this_hash if events else GENESIS
        seq = len(events)
        ev = AuditEvent(seq=seq, ts=getattr(p, "created_at", 0.0) or 0.0,
                        op="purge", page_id=m.group("page_id"),
                        content_hash=m.group("hash"), reason=m.group("reason"),
                        prev_hash=prev)
        ev.this_hash = _digest(prev, seq, ev.op, ev.page_id, ev.content_hash,
                               ev.reason)
        events.append(ev)
    return events


def audit_report(events: list[AuditEvent]) -> dict:
    """可验证的审计输出：链状态 + 链头 + 事件明细。"""
    ok, why = verify_chain(events)
    return {
        "n_events": len(events),
        "chain_ok": ok,
        "chain_error": why,
        "head_hash": events[-1].this_hash if events else GENESIS,
        "content_retained": False,     # 本格式只存哈希，不存内容
        "events": [e.to_dict() for e in events],
    }
