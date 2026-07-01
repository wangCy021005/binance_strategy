# 币安量化策略 — Memory Bank

> 最后更新：2026-07-01

---

## 项目状态

**当前基准（commit 00cbef4c，稳定可复现）**：

| 指标 | 值 |
|------|-----|
| 回测区间 | 2022-01-01 ~ 2025-12-31 |
| 总收益率 | **+80.80%**（含资金费率成本）|
| 年化收益率 | **15.96%** |
| **Sharpe** | **0.678**（目标 0.7，差 0.022）|
| 最大回撤 | **-22.66%** |
| 交易笔数 | 191 |
| 胜率 | 40.8% |

**修复历史（完整）**：
- `fix-001`：资金费率每8小时结算接入回测
- `fix-002`：sqrt(365) 年化修正（日线周期）
- `fix-003`：**熔断死循环** — 幂等化 + peak 重置，Sharpe 0.116 → 0.613
- `fix-004`：BTC/USDT 移出交易标的（仅用于 Regime），0.613 → 0.630
- `fix-005`：regime_agent O(N²)→O(1) 索引（5-10x 速度提升）
- `fix-006`：FundingSignal.direction 注释修正
- `fix-007`：bull_threshold 5%→8%，0.630 → 0.675，MaxDD -26%→-22.7%
- `fix-008`：bear_threshold -10%→-12%，0.675 → 0.678

---

## 架构概述

```
数据层：ccxt → SQLite（9只币，4h K线 + 资金费率）
策略层：Regime三态（bull/ranging/bear/crisis）
  bull:   动量策略 85% + 资金费率套利 10%（3-4槽，90%仓位）
  ranging: 动量 30% + 资金费率 50%（3槽，50%仓位）
  bear:   防御为主（2槽，30%仓位）
  crisis: 全防御（0槽）
Alpha层：AlphaGPT v1（ICIR=3.53，HL_RANGE×VOL_RATIO放量大波动因子）
风控层：WARN/STOP/CIRCUIT三层（8%/15%/25%）
```

---

## 交易标的（9只币）

| 类别 | 币种 | 选择原因 |
|------|------|---------|
| 核心大盘 | BTC/USDT, ETH/USDT | 趋势清晰，资金费率套利主战场 |
| 高Beta L1 | SOL/USDT, AVAX/USDT | 牛市弹性强，独立动量 |
| L2代币 | ARB/USDT, OP/USDT | 生态扩张期高Beta |
| DeFi/基础设施 | LINK/USDT, NEAR/USDT | 走势独立 |
| 交易所代币 | BNB/USDT | 资金费率套利（OI大）|

---

## AlphaGPT 发现的核心因子

**v1 公式（ICIR=3.53，生产使用中）**：
```
HL_RANGE GATE MAX3 MIN3 MIN3 MIN3 MIN3 ABS VOL_RATIO GATE MUL MAX3
```
含义：振幅（HL_RANGE）× 量比（VOL_RATIO）的门控乘积 = 放量大波动因子
效果：接入后 Sharpe 从 0.591 → 0.700（v3→v4，1x无杠杆时）

**v2 训练结果（ICIR=0.9843，未使用）**：
```
FUNDING FUNDING HL_RANGE FUNDING RSI_NORM DIV SIGN DELAY1 DIV DIV DIV MAX3
```
含义：以资金费率为主的套利信号，方向与v1不同。ICIR 远低于v1，未接入。

**训练结论**：
- 9只币宇宙太小，截面IC统计意义有限
- 扩展到 50+ 只币后 AlphaGPT 才能充分发挥
- 当前用 v1 公式（经回测验证有效）

---

## 关键历史决策

| 决策 | 结果 | 原因 |
|------|------|------|
| 9只币替代6只（+ARB/OP/NEAR）| ✅ 有效 | 高Beta增加收益 |
| 资金费率结算接入回测 | ✅ 正确 | 真实成本 -4.3%/年 |
| 3x杠杆 | ❌ 失败 | 胜率33%加杠杆放大亏损 |
| Workflow P0-P1修复（批量）| ❌ 破坏信号 | consistency+vol阈值同时改，trades 170→12 |
| AlphaGPT v1因子 | ✅ 有效 | Sharpe +0.1提升（v3→v4） |
| 熔断死循环(fix-003) | ✅ 修复 | 每根K线重置冷静期→永远熔断→错过2025牛市 |
| 移除BTC交易(fix-004) | ✅ 有效 | BTC动量IC低，移除后Sharpe +0.017 |
| 牛市门槛8%(fix-007) | ✅ 有效 | Sharpe +0.045，MaxDD -26%→-22.7% |
| 止损放宽(追踪16%/硬止损10%) | ❌ 破坏 | Sharpe -0.370，勿再尝试 |
| 动量窗口缩短(21/63/126) | ❌ 破坏 | Sharpe -0.808，日线级噪音过大 |
| Regime确认延长(4天) | ❌ 破坏 | Sharpe -0.159，错过入场时机 |
| Alpha几何平均(sqrt) | ❌ 破坏 | Sharpe -0.186，削弱极端事件 |

---

## Workflow 分析师使用方法

```
# 在 Claude Code 中执行：
Workflow({scriptPath: "scripts/crypto_improve_workflow.js"})
```

5维度分析：知识库 / 代码 / 年度统计 / 交易质量（卖后10日）/ BTC基准背离

---

## 下一步方向

1. **扩展宇宙（Top 50 市值币）**
   - AlphaGPT 截面 IC 才有统计意义
   - 更多 Alpha 机会，Sharpe 自然提升

2. **Sharpe 0.7 达成**（差 0.022）
   - 扩宇宙后更多动量机会 → 可能自然突破
   - ⚠️ 止损/动量窗口已充分测试，勿再尝试修改

3. **实盘验证**（Sharpe > 0.7 后）
   - 币安合约小资金前向测试
   - 监控资金费率成本与回测的一致性

---

## 项目路径

```
/Users/wangcy/binance_strategy/
├── backend/          # 核心策略代码
├── cache_db/         # SQLite 数据（9币，2022-2026）
├── data/             # 回测结果 + AlphaGPT公式
├── knowledge/        # 22章量化教材
├── scripts/          # Workflow + 数据采集 + 训练脚本
└── memory-bank/      # 本文件
```

GitHub: https://github.com/wangCy021005/binance_strategy（私有）
