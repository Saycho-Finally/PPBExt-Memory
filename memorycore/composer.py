"""PromptComposer：缓存友好的记忆组装器（本项目的核心差异点）。

三条缓存纪律（对应 SPEC §三）：
  1. 确定性顺序：kind 固定序 → 组内按 page_id 排序（页序是内容的函数，与加载历史无关）
  2. 预算裁剪：每 kind 分配 token 预算，超出时按（优先级, page_id）确定性淘汰
  3. 批量提交 + 前缀稳定性校验：变更攒批；组装结果与前次前缀重合度 < 阈值时报警
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from memorycore.pages import KIND_ORDER, MemoryPage


@dataclass
class ComposeResult:
    text: str
    used_pages: list[str]
    tokens: int
    prefix_overlap: float | None = None    # 与前次的公共前缀比例（None=首次）
    stable: bool = True


class PromptComposer:
    """确定性组装的记忆注入器。"""

    def __init__(self, kind_budgets: dict[str, int] | None = None,
                 stability_threshold: float = 0.8):
        """
        kind_budgets: 每类页的 token 预算（如 {"preference": 400, "decision": 300,
                      "fact": 800, "lesson": 300}）——超出按 (优先级, page_id) 淘汰
        stability_threshold: 前缀重合度低于此值 → stable=False（缓存将大幅失效）
        """
        self.kind_budgets = kind_budgets or {
            "preference": 400, "decision": 300, "fact": 800, "lesson": 300}
        self.stability_threshold = stability_threshold
        self._last_text: str | None = None

    FOLDED_PLACEHOLDER = "- [folded] <中括号内为已失效记忆占位，保持前缀稳定>" 

    def compose(self, active_pages: list[MemoryPage],
                header: str = "[记忆]", folded_pages: list[MemoryPage] | None = None,
                inplace_placeholder: bool = True) -> ComposeResult:
        """确定性组装：kind 固定序 → 组内 page_id 排序 → 预算裁剪。

        v0.2：folded_pages（已折叠页）+ inplace_placeholder=True 时，折叠页在序列中
        **原位输出固定占位行**（而非移除）——后续内容字符偏移不变，前缀稳定。
        实验（EXPERIMENT_REPORT §三）显示折叠的缓存代价来自组装重排，此为本优化。
        """
        lines: list[str] = []
        used: list[str] = []
        total = 0

        for kind in KIND_ORDER:
            budget = self.kind_budgets.get(kind.value, 0)
            group = sorted([p for p in active_pages if p.kind == kind.value],
                           key=lambda p: p.page_id)   # 确定性排序
            folded_here = sorted(
                [p for p in (folded_pages or []) if p.kind == kind.value],
                key=lambda p: p.page_id)
            spent = 0
            # 合并序列（active + folded 原位）：确定性按 page_id 排序合并
            merged = sorted(group + folded_here, key=lambda p: p.page_id)
            for p in merged:
                if p in folded_here:
                    if inplace_placeholder:
                        lines.append(self.FOLDED_PLACEHOLDER)
                    continue
                if spent + p.tokens > budget:
                    continue          # 确定性淘汰（不改顺序、跳过即可）
                lines.append(f"- [{kind.value}] {p.content}")
                used.append(p.page_id)
                spent += p.tokens
                total += p.tokens

        text = header + "\n" + "\n".join(lines) if lines else ""
        overlap = None
        stable = True
        if self._last_text is not None:
            overlap = self._prefix_overlap(self._last_text, text)
            stable = overlap >= self.stability_threshold
        self._last_text = text
        return ComposeResult(text=text, used_pages=used, tokens=total,
                             prefix_overlap=overlap, stable=stable)

    @staticmethod
    def _prefix_overlap(a: str, b: str) -> float:
        """公共前缀长度 / 较短者长度（字符级；与 token 级近似）。"""
        if not a or not b:
            return 0.0
        n = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                break
            n += 1
        return n / min(len(a), len(b))

    def batch_key(self, pages: list[MemoryPage]) -> str:
        """变更集的批次指纹：同指纹 = 无需重组装（缓存友好的幂等检查）。"""
        payload = "|".join(sorted(p.page_id for p in pages))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
