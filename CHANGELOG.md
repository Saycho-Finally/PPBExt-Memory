# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [Unreleased]

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

