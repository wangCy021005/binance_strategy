# Part4概述

## 核心目标
"构建协作架构" —— 理解多专家Agent的分工、协作设计，以及风控的一票否决权。

## 课程列表

| 课程 | 主题 | 交付物 |
|------|------|--------|
| 第11课 | 为什么需要多智能体 | 多Agent架构设计 |
| 第12课 | 市场状态识别(Regime Detection) | Regime Agent |
| 第13课 | Regime误判与系统性崩溃 | 误判诊断清单、降级策略 |
| 第14课 | LLM在量化中的应用 | LLM增强层设计 |
| 第15课 | 风险控制与资金管理 | Risk Agent |
| 第16课 | 组合构建与风险暴露管理 | Portfolio Agent、因子监控 |
| 第17课 | 在线学习与策略进化 | Evolution Agent |

## 背景知识
- 多智能体框架对比（Shannon vs AutoGen vs CrewAI）
- 量化开源框架对比（VectorBT vs Backtrader vs FinRL）
- 均值方差组合优化（Markowitz模型）

## 学完后你将能够
- 设计Meta Agent、专家Agent、Risk Agent架构
- 实现Regime Detection（趋势市/震荡市/危机市）
- 理解LLM的正确用法：**增强而非替代**
- 构建多层风控系统
- 设计策略在线学习与淘汰机制