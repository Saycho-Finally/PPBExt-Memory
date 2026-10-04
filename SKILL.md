---
name: ppb-memory
description: "缓存友好的分页记忆：页生命周期、折叠机制（staleness 的 append-only 解）与决策审计。适用于「长期偏好/事实演化需要正确失效」「记忆改动不想破坏前缀缓存」的场景。"
---

# ppb-memory

## 能力

- append-only 页库（事实/偏好/决策/教训四类页）
- 折叠机制（不删除的失效声明，审计链完整）
- 确定性组装（页序是内容的函数）+ 前缀稳定性校验
- 四操作决策（ADD/UPDATE/FOLD/NOOP）接 DecisionCore 落证据链

## 实测（偏好演化 12 轮四策略对照）

fold+LLM 判定是唯一在「回答正确率 1.00 / 追问可答 0.67 / 前缀重合 0.73」三维都不差的方案。

## 接口

`from memorycore import MemoryStore, MemoryController, PromptComposer`

## 边界

降级判定器（字符级）不适用于语义演化场景——生产用法应注入嵌入或 LLM 判定。

---

*本技能为 PPBExt-Memory 仓库的 agent 可加载形态（SKILL.md 标准）。完整文档与数据见仓库 README。*
