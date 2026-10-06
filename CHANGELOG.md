# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [Unreleased]

### Fixed

- **MCP stdio 分帧不兼容规范客户端**（2026-10-07 复核确认）：服务原先只认 NDJSON，
  而 MCP 的 stdio 传输用 LSP 式 `Content-Length: N` 头；规范客户端会被静默跳过
  从而握手挂住（与协议版本无关）。现已同时支持两种分帧并按请求分帧回复
- **`MemoryStore.fold_chain()` 完全失效**（2026-10-07 外部评审触发，已复核确认）：
  旧实现的 `next((p.supersedes ...))` 取到的值恒等于 `cur`，函数只会返回输入 id 的
  一到两份拷贝（实测 `fold_chain(p2)` → `[p2, p2]`），且循环体内有
  `for p in self.pages: pass` 死代码与无条件 break。已重写为双向展开的链
  （从旧到新，含成环保护），并补 `tests/test_fold_chain.py`（8 项）
- README 正文把 `fold_char` 的 0.50 误标为 naive 的分数（表格本身无误）——
  已更正，并把"fold_char 折叠零触发（`fold_pages=0`）却比 naive 低 0.25"这个
  **未解释的异常**如实标出（此前被含糊表述为"退化为 naive"）

### Added

- `reports/外部对照_查新_2026-10-06.md`：MemMA 与 Dependency-Guided Rollback Repair
  的核实对照（M1/M2），及记忆安全工程实践的定位修正（M5）。

### Changed

- README 已知局限补两条诚实声明：删除审计链与记忆库同存储（不构成对抗性完整性）；
  "折叠即取代"概念已有工程先例，本仓库增量在三维代价实测与前缀稳定性处理

## [0.4.0] - 2026-10-05

### Added

- **块级前缀命中率指标**（`memorycore/cache_metric.py`）：补齐 v0.2 留下的已知局限。
  口径按 provider 物理语义——**不完整的尾块不入分母**（不可缓存）；
  同时给出块级与字符级两个口径、`partial_tail`、`tail_waste`，
  以及 `HitRateTracker` 会话级汇总（均值 / 前缀被破坏次数 / 低命中轮次）
- **删除审计的可验证输出格式**（`memorycore/audit.py`）：哈希链事件
  （`prev_hash` 衔接 + 自身可复算）。只记哈希不记内容——审计要能证明删了哪一条，
  但不能变相留存被删内容
- MCP server 新增 `memory_audit` 工具（第六个），导出审计链与校验结果
- `tests/test_v4_metrics_audit.py`：30 项测试

### Fixed

- 块级命中率的初版口径把**向上取整的总块数**当分母，导致"两轮文本完全相同"
  算出的命中率不是 1.0（不完整的尾块本不可缓存，不该计入分母）。
  改为按完整块数计算，并单独报告尾块长度

## [0.3.0] - 2026-10-05

### Fixed

- 实验与测试脚本接入决策层时的路径默认值失效（历史品牌前缀 + 已改名的旧目录名），
  统一为 `PPB_DECIDE_ROOT` / `PPB_SAMPLE_ROOT`，并改为以脚本位置为基准解析，
  不再依赖当前工作目录

## [0.2.0] - 2026-10-04

- 原位占位（保前缀）与判定结果缓存；staleness LLM 侧三维对照实验（fold+LLM 判定为唯一三维不差方案）

## [0.1.0] - 2026-10-04

- 立项：页库（append-only）+ 组装器（确定性/预算/前缀校验）+ 控制器（ADD/UPDATE/FOLD/NOOP 接 DecisionCore）+ 16 测试

