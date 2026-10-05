# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-10-05

### Fixed

- 实验与测试脚本接入决策层时的路径默认值失效（历史品牌前缀 + 已改名的旧目录名），
  统一为 `PPB_DECIDE_ROOT` / `PPB_SAMPLE_ROOT`，并改为以脚本位置为基准解析，
  不再依赖当前工作目录

## [0.2.0] - 2026-10-04

- 原位占位（保前缀）与判定结果缓存；staleness LLM 侧三维对照实验（fold+LLM 判定为唯一三维不差方案）

## [0.1.0] - 2026-10-04

- 立项：页库（append-only）+ 组装器（确定性/预算/前缀校验）+ 控制器（ADD/UPDATE/FOLD/NOOP 接 DecisionCore）+ 16 测试

