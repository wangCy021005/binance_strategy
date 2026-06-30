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

---

## 分析师 Workflow

```bash
# 运行5维度全量分析（约15-20分钟）
# 在 Claude Code 中执行：
# Workflow({scriptPath: "scripts/crypto_improve_workflow.js"})
```

**5个分析维度**：
1. **知识库层** — 通用量化原则 + 加密市场差异分析
2. **代码实现层** — config/strategies/regime 缺陷诊断
3. **时序统计层** — 年度收益 / Regime分布 / 策略贡献
4. **交易质量层** — 卖后10日评分（出场时机）/ 资金费率贡献
5. **BTC基准背离层** — 策略净值 vs BTC 的背离期诊断

**分析报告包含**：
- 每个修复方案的 `impact_score / confidence_score / kb_score`（0-10）
- `data_evidence`：具体数字支撑
- `crypto_note`：加密市场特有考虑

## 知识库

`knowledge/quant-book/` — 22章量化教材 + 4个附录

**对加密市场最重要的章节**：
| 章节 | 加密相关性 | 注意事项 |
|------|-----------|---------|
| 第05课：经典策略范式 | ✅ 高（动量/均值回归） | 加密动量IC为正（A股为负） |
| 第12课：市场状态识别 | ✅ 高（Regime） | ADX在加密中滞后，用BTC趋势代替 |
| 第15课：风险控制 | ✅ 高（仓位/止损） | 杠杆>1时止损阈值需相应收紧 |
| 第09课：特征工程 | ✅ 高（Alpha因子） | 资金费率是加密特有Alpha |
| 第08课：对冲/市场中性 | ✅ 中（加密可做空） | 可实现，但成本高 |
| 第13课：Regime误判 | ✅ 高（防误判） | 加密2022熊市容易误判为震荡 |

**知识库不适用的部分（加密中不同）**：
- A股T+1相关内容 → 加密无T+1
- A股涨跌停相关内容 → 加密无限制
- 印花税 → 加密只有手续费（低10倍）
- A股均值回归参数 → 加密动量更强，均值回归较弱
