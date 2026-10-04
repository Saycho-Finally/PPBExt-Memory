# PPBExt-Memory ｜ 立项分析与设计 v0.1（2026-10-04）

> 定位：**缓存友好的分页记忆**——把会话记忆做成"页"，页的生命周期受前缀稳定性纪律约束，
> 所有记忆维护决策经 DecisionCore 落证据链。
> 与前几件一致：不做组件级首创声明，先查新后立项。

---

## 一、领域查新（2026-10-04 检索）

**成熟先例（组件级均有方案，不可声称首创）**：

| 方案 | 核心机制 | 数字 |
|---|---|---|
| MemGPT / Letta | 三层记忆（core / recall / archival）+ 显式工具操作 | Deep Memory Retrieval 93.4% |
| Mem0 | 语义事实 + 自动抽取 | LoCoMo 92.5 @ ~6,900 tok/查询 |
| Zep | 双时态知识图谱（事件时间 + 系统时间）| LoCoMo 94.8 / DMR 98.2 |
| LangMem | episodic+semantic+procedural，后台抽取 | p50 18s 延迟 |
| Stanford ACE | generate-reflect-curate 增量 playbook | agent 基准 +10.6% |
| Anthropic Memory tool / Compaction API | 服务端文件记忆 / 会话内自动压缩 | 平台绑定 |
| AgeMem（2026-01）| 记忆操作暴露为 policy 的 tool（Store/Retrieve/Update/Summarize/Discard）| 统一框架 |

**Benchmark 生态**：LoCoMo（1,540 问/35 会话）、LongMemEval（六类含知识更新）、BEAM（1M/10M 尺度）。
关键经济性数字：全上下文 ~25,000 tok/查询 vs 选择性记忆 ~6,900 tok（**-72%**，精度仅让 ~6 点）。

**检索确认的三个开放问题**（先例自己承认的）：
1. **Memory staleness**（事实衰减/偏好变化）——"没人愿意谈的问题"
2. **跨会话身份**（需应用层认证，记忆系统无法自产）
3. **时间抽象**（"偏好从 X 演化到 Y，今天用 Y 但历史推理还用 X"）

## 二、差异化定位（我们的角度）

**检索结论：所有先例都不管两件事——前缀缓存兼容 与 决策可审计。**

| 维度 | 先例状态 | 我们的角度 |
|---|---|---|
| **前缀缓存兼容** | 全部无视（Letta 的 recall 分页与 cache 纪律无关；ACE/Compaction 直接改写上下文）| **记忆页加载必须满足滞后窗纪律**：确定性顺序 + 批量提交 + 前缀稳定性校验——"记忆动一下缓存全失效"是所有人踩过但不谈的坑，三定律给定量框架 |
| **决策可审计** | 无（记忆 ADD/UPDATE/DELETE 多数是启发式或后台 LLM 抽取，不可追问）| **记忆维护决策经 DecisionCore**：ADD/UPDATE/FOLD/NOOP 是决策点，每次落 DecisionRecord（谁、何时、依据什么改了记忆）|
| **staleness（开放问题 1）** | 无公认解（向量库只能覆盖不能失效）| **折叠机制**：append-only 兼容的失效方案——不删旧页，追加"折叠页"声明旧页效力终止（满足纪律 + 保留审计）|
| **成本口径** | 只算 token 量 | 补**含缓存命中价的成本**（hit/miss 分价——本项目已实证两价相差 50 倍）|

## 三、架构设计

```
MemoryPage（记忆页）
  ├─ id / kind: fact | preference | decision | lesson
  ├─ content / tokens
  ├─ lifecycle: active → archived → folded
  ├─ provenance: 来源（会话 id / 时间 / 生成者）
  └─ supersedes: 被本页取代的页 id（折叠链）

MemoryStore（页库）      JSONL append-only；页只追加不修改
PromptComposer（组装器）  缓存友好核心
  ├─ 确定性顺序：kind 分组固定序 → 组内按 id 排序
  ├─ 预算裁剪：按 kind 分配 token 预算（preference 优先于 lesson）
  ├─ 批量提交：变更集攒批，一次只动尾部
  └─ 前缀稳定性校验：组装结果与前次的前缀重合度 ≥ 阈值（落差报警）
MemoryController（控制器）判定/选择接口
  └─ 四操作决策点（DecisionCore）：
     ADD（新事实是否入页）/ UPDATE（翻新 or 折叠）/ FOLD（失效声明）/ NOOP
     每次决策落 DecisionRecord（候选来源、判定器、依据、shift_risk）
```

**关键设计约束**：
1. 页库 append-only（满足滞后窗定律的前缀稳定前提）
2. 组装顺序确定性（页序 = 内容哈希的函数，与加载历史无关）
3. 折叠不删除（staleness 的 append-only 解）
4. 决策必审计（staleness 的问责解：为什么这条记忆被降权）

## 四、实现范围（v0.1）

- `memorycore/pages.py`：MemoryPage / MemoryStore（JSONL append-only）
- `memorycore/composer.py`：PromptComposer（确定性顺序 / 预算裁剪 / 前缀稳定性校验）
- `memorycore/controller.py`：MemoryController（四操作决策点 → DecisionCore 接口，零依赖降级模式）
- `tests/`：页生命周期 / 组装确定性 / 前缀稳定性 / 折叠链 / 决策审计
- 依赖：核心零依赖（decisioncore 为可选增强；未安装时用内置规则判定器）

## 五、与四件套的接口

| 接口 | 方式 |
|---|---|
| 前缀缓存 | 组装器的确定性顺序 + 批量提交 = 缓存纪律在记忆侧的执行；前缀重合度可作为能力探测的输入 |
| 判定/选择 | MemoryController 的四操作决策点（verifiable: 内容门规则 / open: 重要性判断）|
| 知识注入 | 折叠页可作为"知识更新"信号（折叠不等于遗忘，是效力转移）|
| 采样预算 | 记忆页的 token 预算 = 输出预算守卫的一个输入维度 |

## 六、红线（延续）

- 不做组件级首创声明（三层记忆/显式操作/摘要压缩均有先例）
- 增量是**交集**：记忆分页 × 前缀缓存纪律 × 决策审计——三个都有先例，交集没有
- 所有结论带条件限定；staleness 折叠的有效性需实测（用户偏好演化的场景设计）
