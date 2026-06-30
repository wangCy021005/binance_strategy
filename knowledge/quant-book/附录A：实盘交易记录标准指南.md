# 附录A：实盘交易记录标准指南

## 前言

在量化交易实战中，原始交易日志是连接模拟与实盘的核心纽带，用于采集能反哺策略训练（尤其是RL）的高质量数据。

---

## A1.1 核心数据结构

### A1.1.1 订单级信息（Order Level）

- **标识符**：`order_id`、`symbol`
- **指令参数**：`side`、`order_type`、`order_price`、`order_qty`
- **生命周期**：`submit_ts`、`cancel_ts`

### A1.1.2 成交级信息（Fill Level）

- **关联标识**：`fill_id`、`order_id`
- **成交明细**：`fill_price`、`fill_qty`、`fill_ts`（精确到毫秒）

### A1.1.3 派生关键指标（Derived Metrics）

- `expected_price`：信号触发时的理论价
- `slippage`：实际成交均价与理论价的偏差
- `latency_ms`：下单到首笔成交的时间差
- `fill_ratio`：实际成交量与计划量之比

---

## A1.2 成本核算与市场快照

### A1.2.1 财务损益与摩擦成本

- **显性成本**：`commission`、`tax`
- **最终收益**：`realized_pnl`

### A1.2.2 决策时的市场状态

- **Bar数据**：`bar_ts`、`bar_open/high/low/close`、`bar_vwap`
- **波动率**：`atr_5min`
- **（可选）流动性深度**：`bid1`/`ask1`

---

## A1.3 Agent决策元数据（RL专用）

- **版本标识**：`agent_id` / `version`
- **动作详情**：`action`、`target_position`
- **置信度**：`confidence` 或模型预测分数

---

## A1.4 总结

标准化日志的核心价值：

1. **还原滑点真相**：区分"信号错误"与"执行偏差"
2. **训练执行逻辑**：为执行型RL提供真实Reward信号
3. **摆脱数据依赖**：仅靠实盘日志即可构建执行模拟器

> 核心原则：若不完整记录"下单→成交→延迟→失败"的全过程，实盘数据对策略进化便毫无价值。