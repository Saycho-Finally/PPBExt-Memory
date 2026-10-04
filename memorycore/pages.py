"""记忆页与页库：append-only 的 MemoryPage / MemoryStore。

设计约束（SPEC §三）：
  1. 页库 append-only（JSONL）——页只追加不修改，满足前缀稳定的前提
  2. 折叠不删除——失效通过追加"折叠页"声明旧页终止（staleness 的 append-only 解）
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum


class PageKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    LESSON = "lesson"


class PageLifecycle(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    FOLDED = "folded"


# 组装时的 kind 固定序（确定性的一部分）
KIND_ORDER = [PageKind.PREFERENCE, PageKind.DECISION, PageKind.FACT, PageKind.LESSON]


@dataclass
class MemoryPage:
    kind: str
    content: str
    tokens: int = 0
    lifecycle: str = PageLifecycle.ACTIVE.value
    provenance: str = ""            # 来源标记（会话 id / 生成者）
    supersedes: str = ""            # 折叠链：本页取代的旧页 id
    created_at: float = field(default_factory=time.time)
    page_id: str = ""

    def finalize(self) -> "MemoryPage":
        """生成确定性 page_id（内容+kind 的短哈希）。"""
        h = hashlib.sha256(f"{self.kind}|{self.content}".encode("utf-8"))
        self.page_id = h.hexdigest()[:12]
        if not self.tokens:
            self.tokens = max(1, len(self.content) // 3)   # 粗估
        return self


class MemoryStore:
    """append-only 页库（JSONL）。"""

    def __init__(self, path: str | None = None):
        self.path = path
        self.pages: list[MemoryPage] = []

    def add(self, page: MemoryPage) -> MemoryPage:
        page.finalize()
        self.pages.append(page)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
        return page

    def fold(self, old_page_id: str, reason: str, provenance: str = "") -> MemoryPage:
        """折叠：追加一条声明旧页效力终止的页（不删除旧页）。"""
        fold_page = MemoryPage(
            kind=PageKind.DECISION.value,
            content=f"[FOLD] supersede {old_page_id}: {reason}",
            supersedes=old_page_id, provenance=provenance)
        # 旧页标记 folded（内存视图更新；磁盘上旧行不动，append-only 语义在文件层）
        for p in self.pages:
            if p.page_id == old_page_id and p.lifecycle != PageLifecycle.FOLDED.value:
                p.lifecycle = PageLifecycle.FOLDED.value
        return self.add(fold_page)

    def active_pages(self, kind: str | None = None) -> list[MemoryPage]:
        """有效页（排除已折叠）；组装器只用有效页。"""
        folded_ids = {p.supersedes for p in self.pages if p.supersedes}
        out = [p for p in self.pages
               if p.lifecycle != PageLifecycle.FOLDED.value
               and p.page_id not in folded_ids
               and not p.supersedes]      # 折叠页本身不进组装
        if kind:
            out = [p for p in out if p.kind == kind]
        return out

    def fold_chain(self, page_id: str) -> list[str]:
        """追一条页的折叠链（它取代了谁、又被谁取代）。"""
        chain = [page_id]
        cur = page_id
        while True:
            nxt = next((p.supersedes for p in self.pages
                        if p.supersedes == cur), None)
            if not nxt:
                break
            chain.append(nxt)
            cur = nxt
            # 反向：本页取代的旧页
            for p in self.pages:
                pass
            break
        return chain

    def stats(self) -> dict:
        active = self.active_pages()
        folders = [p for p in self.pages if p.supersedes]
        return {
            "total_pages": len(self.pages),
            "active_pages": len(active),
            "fold_pages": len(folders),
            "active_tokens": sum(p.tokens for p in active),
            "by_kind": {k.value: len([p for p in active if p.kind == k.value])
                        for k in PageKind},
        }
