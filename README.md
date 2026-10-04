# PPBExt-Memory ｜ 补遗：缓存友好的分页记忆 · 折叠机制与三维对照实测

**一句话**：把会话记忆做成"页"，页的生命周期受前缀稳定性纪律约束，所有记忆维护决策
落证据链——并在偏好演化场景里实测了三种失效策略的**三角张力**（回答质量 / 追问可答 /
缓存代价），**折叠 + LLM 语义判定是唯一在三个维度都不差的方案**（回答正确率 1.00 实测）。

> 作者：Saycho-Finally（独立研究者） ｜ AI 使用声明见 [AI_DISCLOSURE.md](AI_DISCLOSURE.md) ｜ License: MIT ｜ 核心零依赖 ｜ Python ≥3.10（依赖 DecisionCore 时自动启用审计）

---

## 三条设计约束（从实测批判继承）

1. **页库 append-only**：页只追加不修改——前缀稳定的前提
2. **折叠不删除**：失效通过追加"折叠页"声明旧页终止——staleness 的 append-only 解，
   审计链完整（能回答"这条记忆何时被谁改的"）
3. **组装确定性**：页序 = 内容的函数（kind 固定序 → page_id 排序），与加载历史无关

## 实测：staleness 折叠的三维对照（12 轮偏好演化）

场景：用户偏好演化（重复/精化/改口/回退/并行/收敛），四策略对照：

| 策略 | 回答正确率 | 追问可答率 | 前缀重合 | 折叠页 | 审计 |
|---|---|---|---|---|---|
| naive（全追加） | 0.75 | **1.00** | 0.68 | 0 | 0 |
| delete（物理删除） | 0.92 | **0.11** | 0.63 | 0 | 0 |
| fold + 字符判定 | 0.50 | 1.00 | 0.75 | 0 | 12 |
| **fold + LLM 判定** | **1.00** | 0.67 | **0.73** | **4** | 12 |

**四个结论**：
1. **折叠机制强依赖语义判定器**：字符级相似度对"喜欢 React" vs "改用 Svelte" 这类
   语义相反、字面零重叠的偏好演化完全无感——折叠零触发，退化为 naive（回答正确率 0.50）
2. **"回答正确"与"可追问"是两个分离的属性**：delete 回答正确率 0.92 但追问可答仅 0.11
   ——它用审计换正确率
3. **折叠 + LLM 判定是唯一三个维度都不差的方案**（1.00 / 0.67 / 0.73）
4. **缓存代价的诚实记录**：折叠引起的组装重排会削弱字符级前缀重合（v0.1 实测 0.57）；
   v0.2 的"原位占位"在字符级指标上无改善（0.52）——折叠点在字符级必然断裂，
   块级收益需 64-token 块指标专门测量（已知局限）

## 仓库结构

```
memorycore/    核心库（pages 页库+折叠 / composer 确定性组装 / controller 四操作决策）
experiments/   staleness 实验（离线四策略 + LLM 侧三维验证）
results/       实验原始数据（两份 JSON）
tests/         16 项测试全过
SPEC.md        立项分析与设计（含领域查新与差异化定位）
EXPERIMENT_REPORT.md  完整实验报告（离线 + LLM 侧）
```

## 差异化定位（与已有方案的关系）

三层记忆（MemGPT/Letta）、显式记忆操作（AgeMem）、摘要压缩（LangChain/LlamaIndex）、
事实抽取（Mem0/Zep）——组件级均有成熟方案。本仓库的增量是**交集**：

- **记忆分页 × 前缀缓存纪律**（先行方案不处理缓存兼容；本仓库的组装器把三定律的
  确定性纪律落到记忆侧）
- **记忆维护 × 决策审计**（折叠/更新决策经 DecisionCore 落 DecisionRecord：谁、何时、
  依据什么改了记忆）

## MCP server（可选形态）

本外挂同时提供 **MCP（Model Context Protocol）server** 形态——任何支持 MCP 的 agent
客户端可直接把记忆作为工具调用：

```bash
python mcp_server.py        # stdio JSON-RPC
```

暴露三个工具：`memory_ingest`（写入/更新，自动 ADD/UPDATE/NOOP）、`memory_recall`
（组装有效记忆 + 前缀稳定性指标）、`memory_fold`（折叠失效，审计链保留）。
零依赖实现（纯 stdio JSON-RPC），冒烟测试随仓库（initialize / tools/list / tools/call）。

## 快速上手

```python
from memorycore import MemoryController, MemoryPage, MemoryStore, PageKind, PromptComposer

store = MemoryStore("memory.jsonl")
ctl = MemoryController(store)                      # 可选：dc=DecisionCore() 启用审计
ctl.ingest(PageKind.PREFERENCE, "偏好中文回复")      # ADD / UPDATE / FOLD / NOOP 自动决策
ctl.fold("<page_id>", reason="偏好已更新")           # 显式失效（append-only）

comp = PromptComposer(kind_budgets={"preference": 400, "fact": 800})
r = comp.compose(store.active_pages(), folded_pages=[p for p in store.pages if p.lifecycle == "folded"])
print(r.text, r.prefix_overlap, r.stable)          # 组装 + 前缀稳定性自检
```

## 已知局限

- 降级判定器（字符级 Jaccard）**不适用于语义演化场景**——生产用法应注入嵌入或
  LLM 判定（`similarity_fn` 可插拔）
- 跨会话身份不在本仓库范围（需应用层认证）
- 时间抽象（"偏好从 X 演化到 Y，历史推理用 X"）只做了基础支持（折叠链可回溯）

## 引用的先行者

- MemGPT / Letta（三层记忆 + 显式操作）、Mem0（事实抽取）、Zep（双时态图）、
  LangMem（后台抽取）、Stanford ACE（增量 playbook）、AgeMem（记忆操作工具化）
- LoCoMo / LongMemEval / BEAM（记忆评测基准）
- 本仓库的实验设计与数据：见 EXPERIMENT_REPORT.md

---

## 贡献与引用

- 贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)；行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题请走 [SECURITY.md](SECURITY.md) 的私密渠道（勿开公开 Issue）
- 版本变更见 [CHANGELOG.md](CHANGELOG.md)；学术引用格式见 [CITATION.cff](CITATION.cff)
- 许可：MIT
