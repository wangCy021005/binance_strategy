# 币安量化交易系统 — 项目总览

## 架构
双层设计：AlphaGPT强化学习挖掘Alpha公式 + 规则策略执行

```
binance_strategy/
├── backend/
│   ├── config.py              # 所有参数唯一入口
│   ├── core/
│   │   ├── data_feed.py       # Binance数据获取（ccxt）
│   │   ├── indicators.py      # 技术指标 + 加密特有指标
│   │   └── portfolio.py       # 仓位管理
│   ├── agents/
│   │   ├── regime_agent.py    # 市场状态（bull/bear/volatile/crisis）
│   │   ├── signal_agent.py    # 信号路由
│   │   └── risk_agent.py      # 三层风控
│   ├── strategies/
│   │   ├── momentum.py        # 趋势动量（加密市场IC为正）
│   │   ├── funding_arb.py     # 资金费率套利
│   │   └── mean_revert.py     # 均值回归（震荡市）
│   ├── model_core/            # AlphaGPT（加密版）
│   │   ├── alphagpt.py        # Transformer + REINFORCE
│   │   ├── factors.py         # 加密特有特征
│   │   ├── data_loader.py     # 币安OHLCV+资金费率
│   │   └── vm.py              # StackVM公式执行器
│   ├── backtest/
│   │   ├── engine.py
│   │   └── report.py
│   └── run_backtest.py
├── cache_db/                  # SQLite本地缓存
│   └── crypto_data.db
├── data/                      # 回测结果
└── scripts/
    ├── fetch_data.py          # 历史数据采集
    └── train_alpha.py         # AlphaGPT训练入口
```

## 与A股的关键区别（更有利于量化）

| 特性 | A股 | 币安 |
|------|-----|------|
| 做空 | ❌ 极难 | ✅ 永续合约随时做空 |
| T+1 | ❌ 隔日才能卖 | ✅ 即时买卖 |
| 涨跌幅限制 | ±10% | 无限制 |
| 交易时间 | 每天4小时 | 24/7 |
| 动量IC | 负（短期反转） | 正（强趋势跟随） |
| 数据获取 | 付费/限制 | 免费API（Binance) |
| 手续费 | 0.16%/次 | 0.02-0.04%/次（低8倍）|

## 加密特有Alpha信号

1. **资金费率（Funding Rate）**：资金费率>0.1%时做空，<-0.05%时做多
2. **未平仓合约（Open Interest）**：OI上升+价格下跌=空头陷阱
3. **清算热图**：大量多头清算后反弹，大量空头清算后回落
4. **BTC主导率**：BTC.D上升=风险偏差，山寨币看空
5. **链上数据**：大额转入/转出交易所，鲸鱼动向

## 开发规范

### 绝对禁止
- ❌ 在回测中使用未来数据
- ❌ 不加杠杆上限（最高5x）
- ❌ 单笔超过总资产10%（初期）
- ❌ 忽略资金费率成本（对持仓成本影响很大）

### 数据规范
- 所有时间戳统一UTC
- K线数据：open_time为K线开盘UTC时间
- 资金费率：每8小时结算，需计入持仓成本

### 策略规范
- 空头通过永续合约实现（不是现货做空）
- 回测时考虑流动性（小市值币种滑点大）
- 杠杆默认1x，最高3x（初期）

## 快速开始

```bash
# 安装依赖
pip install ccxt pandas torch sqlite3 ta

# 采集历史数据
python scripts/fetch_data.py --symbol BTCUSDT --start 2022-01-01

# 运行回测
python backend/run_backtest.py

# 训练 AlphaGPT
python scripts/train_alpha.py --steps 2000
```
