"""MemoryController：记忆维护决策（ADD / UPDATE / FOLD / NOOP）→ DecisionCore 接口。

设计（SPEC §三）：记忆维护的每个动作都是一个决策点——
  未安装 decisioncore 时用内置规则判定器降级；安装时委托 DecisionCore 并落证据链。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from memorycore.pages import MemoryPage, MemoryStore, PageKind

_HAS_DC = importlib.util.find_spec("decisioncore") is not None


@dataclass
class MemoryAction:
    op: str            # add / update / fold / noop
    reason: str
    page_id: str = ""
    decision_id: str = ""


class MemoryController:
    """四操作决策：相似度与来源规则判定，经 DecisionCore 落审计（如可用）。"""

    def __init__(self, store: MemoryStore, similarity_threshold: float = 0.5,
                 dc=None, similarity_fn=None):
        """similarity_fn: 可插拔语义判定器 —— 默认字符级 Jaccard（零依赖降级）。

        实验结论（staleness_experiment）：字符级判定器**无法识别语义相反的偏好**
        （"喜欢 React" vs "改用 Svelte" 几乎零重叠）→ 折叠零触发。
        升级路径：注入嵌入相似度或 LLM 判定（后者经 DecisionCore 的 open 决策点，
        落 shift_risk 标注）。
        """
        self.store = store
        self.sim_threshold = similarity_threshold
        self.dc = dc                      # DecisionCore 实例（可选）
        self.similarity_fn = similarity_fn or self._similarity
        self.actions: list[MemoryAction] = []
        self.sim_cache: dict[tuple, float] = {}    # v0.2：判定结果缓存（同对不重复调用）
        self.cache_hits = 0

    # ---- 核心：新信息入场决策 ----

    def ingest(self, kind: PageKind, content: str, provenance: str = "") -> MemoryAction:
        """新信息入场：与现存同 kind 页比对 → ADD / UPDATE(折叠旧页) / NOOP。"""
        cand = MemoryPage(kind=kind.value, content=content, provenance=provenance).finalize()
        same_kind = [p for p in self.store.active_pages(kind.value)]

        best, sim = None, 0.0
        for p in same_kind:
            ck = (p.content, content) if p.content <= content else (content, p.content)
            if ck in self.sim_cache:
                s = self.sim_cache[ck]
                self.cache_hits += 1
            else:
                s = self.similarity_fn(p.content, content)
                self.sim_cache[ck] = s
            if s > sim:
                best, sim = p, s

        if best is not None and sim >= 0.92:
            # 近乎重复 → NOOP（不写页，避免膨胀）
            act = MemoryAction("noop", f"重复（相似度 {sim:.2f} ≥ 0.92）",
                               best.page_id)
        elif best is not None and sim >= self.sim_threshold:
            # 相似但不同 → UPDATE：折叠旧页 + 追加新页（append-only 兼容）
            fold = self.store.fold(best.page_id,
                                   reason=f"被更新（相似度 {sim:.2f}）",
                                   provenance=provenance)
            page = self.store.add(cand)
            act = MemoryAction("update",
                               f"翻新旧页（相似度 {sim:.2f}）→ 折叠 {best.page_id}",
                               page.page_id)
        else:
            page = self.store.add(cand)
            act = MemoryAction("add", "新页入账", page.page_id)

        act.decision_id = self._audit(act, kind, content, sim)
        self.actions.append(act)
        return act

    def fold(self, page_id: str, reason: str, provenance: str = "") -> MemoryAction:
        """显式失效（staleness 的正规出口）。"""
        self.store.fold(page_id, reason=reason, provenance=provenance)
        act = MemoryAction("fold", reason, page_id)
        act.decision_id = self._audit(act, PageKind.DECISION, reason, None)
        self.actions.append(act)
        return act

    # ---- 判定器（降级模式：字符级 Jaccard；decisioncore 可用时不改变行为，只加审计）----

    def _similarity(self, a: str, b: str) -> float:
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _audit(self, act: MemoryAction, kind, content: str, sim: float | None) -> str:
        """决策落审计：决策点类型按操作分——folding 是 verifiable（规则明确），
        add/update 是 open（重要性判定，需覆盖证据）。"""
        if self.dc is None:
            return ""
        try:
            from decisioncore import DecisionPoint, DecisionType, CoverageEvidence
            if act.op in ("add", "update"):
                point = DecisionPoint(
                    name=f"memory.{act.op}", type=DecisionType.OPEN,
                    candidates=[content],
                    coverage=CoverageEvidence(
                        n_candidates=1, source="session_stream",
                        source_diversity="single_provenance"))
                rec, _ = self.dc.decide_open(point, vote_keys=[content])
            else:
                point = DecisionPoint(
                    name=f"memory.{act.op}", type=DecisionType.VERIFIABLE,
                    predicate=lambda r: isinstance(r, str) and len(r) > 0)
                rec = self.dc.decide_verifiable(point, subject=act.reason)
            return rec.decision_id
        except Exception:
            return ""

    def report(self) -> dict:
        from collections import Counter
        c = Counter(a.op for a in self.actions)
        return {"n_actions": len(self.actions), "ops": dict(c),
                "store": self.store.stats(),
                "audited": sum(1 for a in self.actions if a.decision_id),
                "sim_cache_size": len(self.sim_cache),
                "sim_cache_hits": self.cache_hits}
