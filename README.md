# 币安量化交易系统

基于 AlphaGPT（强化学习公式挖掘） + 规则策略 的加密量化框架。

## 核心优势 vs A股

| | A股 | 币安 |
|--|--|--|
| 做空 | ❌ | ✅ 永续合约 |
| 动量IC | -0.02（反转） | +0.05（跟随） |
| 交易成本 | 0.16%/次 | 0.04%/次 |
| 24/7 | ❌ | ✅ |
| 数据 | 付费 | 免费 API |

## 策略架构

```
Binance API → SQLite缓存 → 特征工程 → 
  Regime识别（BTC趋势）→ 策略路由：
    bull:    动量策略（趋势跟随）
    ranging: 资金费率套利
    bear:    做空 + 防御
    crisis:  全现金
```

## 快速开始

```bash
cd binance_strategy

# 1. 安装依赖
pip install ccxt pandas torch ta

# 2. 获取历史数据
python scripts/fetch_data.py --all --start 2022-01-01

# 3. 运行回测
python backend/run_backtest.py

# 4. 训练 AlphaGPT（可选）
python scripts/train_alpha.py --steps 2000
```

## 已实现组件

- [x] 数据层（ccxt + SQLite缓存）
- [x] Regime识别（BTC四态：bull/ranging/bear/crisis）
- [x] 动量策略（加密动量IC+，与A股反向不同）
- [x] 资金费率套利（A股特有，加密独有Alpha）
- [ ] 均值回归策略
- [ ] 仓位管理（portfolio.py）
- [ ] 风控Agent（risk_agent.py）
- [ ] 回测引擎（backtest/engine.py）
- [ ] AlphaGPT 加密版（model_core/）

## 关键参数（config.py）

- `leverage = 1.0`（默认不杠杆）
- `max_pos_pct = 0.25`（单仓25%上限）
- `hard_stop = -0.08`（-8%硬止损）
- `funding_short_threshold = 0.001`（资金费率>0.1%做空）
