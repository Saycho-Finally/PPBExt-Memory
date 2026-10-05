"""块级前缀命中率指标（M3）。

**为什么要把块级与字符级分开看**：前缀缓存按**块**匹配，不足一块的部分不缓存
（三定律之二「块级匹配」）。两个口径合起来才有诊断力：

  - **块级高、字符级低** → 损失落在不可缓存的尾部，属正常开销，无需处理
  - **块级骤降** → 缓存边界本身被动过（缓存杀手）

口径定义（按 provider 的物理语义）：

    total_blocks   本轮**完整块数**（= 字符数 // 块大小）——不完整的尾块不入分母，
                   因为它根本不可缓存
    shared_blocks  与上一轮共享的完整块数
    block_hit_rate shared_blocks / total_blocks
    token_hit_rate 共享前缀字符数 / 总字符数（字符级近似，与 provider 的 token 口径
                   有系统性差异，仅作对照）
    partial_tail   尾部不足一块的字符数（结构性不可缓存）
    tail_waste     从分歧点到下一块边界的字符数——这段因块粒度而浪费

无 tokenizer 依赖：块大小以**字符**计（`chars_per_block`），是 token 块的代理口径。
"""

from __future__ import annotations

from dataclasses import dataclass

# 默认块大小（字符）。经验值：64 token 的中文负载大致落在 200-300 字符区间。
DEFAULT_CHARS_PER_BLOCK = 256


@dataclass
class BlockMetric:
    total_blocks: int
    shared_blocks: int
    total_chars: int
    shared_chars: int
    partial_tail: int         # 尾部不足一块的字符数（结构性不可缓存）
    tail_waste: int           # 从分歧点到下一块边界的字符数
    block_hit_rate: float
    token_hit_rate: float
    prefix_changed: bool      # 首个块未完整共享 → 前缀被动过

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def block_metric(prev: str | None, cur: str,
                 chars_per_block: int = DEFAULT_CHARS_PER_BLOCK) -> BlockMetric:
    """比较两轮组装结果，给出块级与字符级两个命中口径。"""
    total_chars = len(cur)
    total_blocks = total_chars // chars_per_block      # 完整块数（尾块不缓存，不入分母）
    partial_tail = total_chars % chars_per_block
    if not prev:
        return BlockMetric(total_blocks, 0, total_chars, 0, partial_tail, 0,
                           0.0, 0.0, False)
    shared = _common_prefix_len(prev, cur)
    shared_blocks = shared // chars_per_block
    next_boundary = min(total_chars, (shared_blocks + 1) * chars_per_block)
    tail_waste = max(0, next_boundary - shared)
    return BlockMetric(
        total_blocks=total_blocks,
        shared_blocks=shared_blocks,
        total_chars=total_chars,
        shared_chars=shared,
        partial_tail=partial_tail,
        tail_waste=tail_waste,
        block_hit_rate=round(shared_blocks / total_blocks, 4) if total_blocks else 0.0,
        token_hit_rate=round(shared / total_chars, 4) if total_chars else 0.0,
        prefix_changed=shared < chars_per_block,
    )


class HitRateTracker:
    """逐轮观测块级命中率，输出会话语义下的汇总。

    汇总里刻意区分两种恶化：`prefix_breaks` 记"前缀被动过"的次数，
    `low_block_rate_turns` 记"块级命中率低于阈值"的轮次——前者是事故，
    后者可能只是尾部自然增长。
    """

    def __init__(self, chars_per_block: int = DEFAULT_CHARS_PER_BLOCK,
                 low_rate_threshold: float = 0.5):
        self.chars_per_block = chars_per_block
        self.low_rate_threshold = low_rate_threshold
        self.metrics: list[BlockMetric] = []
        self._prev: str | None = None

    def observe(self, text: str) -> BlockMetric:
        m = block_metric(self._prev, text, self.chars_per_block)
        self._prev = text
        self.metrics.append(m)
        return m

    def summary(self) -> dict:
        n = len(self.metrics)
        if n == 0:
            return {"turns": 0, "mean_block_hit_rate": 0.0,
                    "mean_token_hit_rate": 0.0, "prefix_breaks": 0,
                    "low_block_rate_turns": 0, "total_tail_waste": 0}
        return {
            "turns": n,
            "mean_block_hit_rate": round(
                sum(m.block_hit_rate for m in self.metrics) / n, 4),
            "mean_token_hit_rate": round(
                sum(m.token_hit_rate for m in self.metrics) / n, 4),
            "prefix_breaks": sum(1 for m in self.metrics if m.prefix_changed),
            "low_block_rate_turns": sum(
                1 for m in self.metrics if m.block_hit_rate < self.low_rate_threshold),
            "total_tail_waste": sum(m.tail_waste for m in self.metrics),
        }
