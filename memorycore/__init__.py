"""PPBExt-Memory：缓存友好的分页记忆（三层记忆 x 前缀纪律 x 决策审计）。"""

from memorycore.pages import MemoryPage, MemoryStore, PageKind, PageLifecycle
from memorycore.composer import PromptComposer, ComposeResult
from memorycore.controller import MemoryController, MemoryAction
from memorycore.cache_metric import (DEFAULT_CHARS_PER_BLOCK, BlockMetric,
                                     HitRateTracker, block_metric)
from memorycore.audit import (GENESIS, AuditEvent, append_event, audit_report,
                              collect_purge_events, hash_content, verify_chain)

__version__ = "0.4.0"
__all__ = ["MemoryPage", "MemoryStore", "PageKind", "PageLifecycle",
           "PromptComposer", "ComposeResult", "MemoryController", "MemoryAction",
           "HitRateTracker", "BlockMetric", "block_metric",
           "DEFAULT_CHARS_PER_BLOCK",
           "AuditEvent", "append_event", "verify_chain", "audit_report",
           "collect_purge_events", "hash_content", "GENESIS",
           "__version__"]
