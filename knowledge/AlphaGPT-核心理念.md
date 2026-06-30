# AlphaGPT 核心理念沉淀

> 来源：`/Users/wangcy/AlphaGPT`（Solana meme 生态量化系统）  
> 核心 Takeaway：**不预测价格，而是自动生成因子公式**

---

## 一、系统定位

AlphaGPT 不是一个价格预测模型，而是一个**因子公式自动挖掘系统**：

```
原始行情 → 特征提取 → Transformer 生成公式 → StackVM 执行 → 回测打分 → 强化学习优化生成器
```

核心理念：把"策略研究"和"交易执行"清晰分层，模型只负责生成可解释的因子公式，交易层只消费最终信号分数。

---

## 二、架构分层

```
data_pipeline/      ← 链上/行情数据拉取入库（Birdeye/DexScreener → Postgres）
    ↓
model_core/         ← 策略挖掘核心
  ├── factors.py      特征工程（收益/流动性/买卖压力/成交量等）
  ├── vocab.py        词汇表（特征 token + 算子 token）
  ├── vm.py           StackVM：将 token 序列执行为因子信号
  ├── alphagpt.py     Transformer 模型（GPT 架构）
  ├── backtest.py     回测评分器（reward 函数）
  └── engine.py       训练引擎（REINFORCE + LoRD 正则化）
    ↓
strategy_manager/   ← 实盘信号应用（加载公式 → 打分 → 风控 → 下单）
    ↓
execution/          ← 交易执行（Solana RPC + Jupiter 聚合器）
    ↓
dashboard/          ← Streamlit 看板（持仓/市场快照/日志）
```

---

## 三、核心机制：公式即 Token 序列

### 3.1 词汇表设计

公式由两类 token 组成：

| 类型 | 说明 | 示例 |
|------|------|------|
| 特征 token | 对应一个市场特征维度 | ret（对数收益）、pressure（买卖力量）、fomo（成交量加速度）|
| 算子 token | 对应一种数学运算 | ADD、MUL、DECAY、GATE（门控）、JUMP（跳变检测）|

### 3.2 StackVM 执行逻辑

采用**后缀表达式 + 栈机器**的方式执行公式：

```python
# 例：公式 [ret, fomo, MUL, DECAY]
# 等价于：DECAY(ret * fomo)

stack = []
for token in formula_tokens:
    if token 是特征:
        stack.push(feat_tensor[:, token, :])  # 压入特征向量
    elif token 是算子:
        args = stack.pop(arity个)              # 弹出操作数
        stack.push(op(args))                   # 压入结果
# 最终 stack 只剩一个元素 = 因子信号
```

好处：公式天然可解释（能还原成数学表达式），且执行高效。

### 3.3 主要算子（12个）

| 算子 | 含义 | 特别说明 |
|------|------|---------|
| ADD/SUB/MUL/DIV | 基础四则 | — |
| NEG/ABS/SIGN | 符号处理 | — |
| GATE | 门控选择 | `cond > 0` 选 x，否则 y |
| JUMP | 极端跳变检测 | z-score > 3 才触发 |
| DECAY | 时间衰减叠加 | `t + 0.8*lag1 + 0.6*lag2` |
| DELAY1 | 滞后1期 | — |
| MAX3 | 三期最大值 | 当前/滞后1/滞后2 取最大 |

---

## 四、训练方式：用回测结果做 Reward

这是 AlphaGPT 最独特的地方——**强化学习 + 回测奖励**：

```
Transformer 采样公式 token 序列
    ↓
StackVM 执行 → 得到因子信号
    ↓
MemeBacktest.evaluate() → 回测打分（扣除滑点/手续费/大回撤惩罚）
    ↓
REINFORCE 梯度更新 → Transformer 学会生成高分公式
```

**回测打分逻辑**（`backtest.py`）：
```python
score = 累计收益 - 大回撤惩罚 × 2
# 信号太弱（活跃持仓 < 5）→ 直接扣分 -10
# 最终取 median score（鲁棒性强于 mean）
```

交易成本建模：
- 固定手续费：0.6%（单边）
- 市场冲击滑点：交易额 / 流动性，最高 5%
- 流动性门控：流动性 < 50万美金的代币不交易

---

## 五、技术亮点：LoRD 正则化

**Low-Rank Decay（LoRD）**：用 Newton-Schulz 迭代替代 SVD，高效地对 Attention 矩阵做低秩约束。

```python
# Newton-Schulz 迭代（5次）→ 近似最小奇异向量
Y_{k+1} = 0.5 × Y_k × (3I - Y_k^T × Y_k)

# 然后对 Attention 权重施加衰减
W = W - decay_rate × Y  # 压制低秩噪声，提升模型稳定性
```

效果：防止 Transformer 过拟合短暂的市场模式，在 meme coin 高噪声环境中尤其重要。

---

## 六、与 A股系统的对比与借鉴

| 维度 | AlphaGPT | 本系统（hot_sector_strategy）|
|------|---------|--------------------------|
| 信号来源 | Transformer 生成公式 | 规则法（ADX/MA/RSI） |
| 市场 | Solana meme coin | A股主板 |
| 交易制度 | T+0，无涨跌限制 | T+1，±10%涨跌停 |
| 策略 | 单一做多（无做空） | 动量 + 均值回归双策略 |
| Regime | 无显式 Regime 识别 | Regime Agent（trend/ranging/uncertain/crisis）|
| 风控 | 流动性门控 + 回撤惩罚 | 三层风控（WARN/STOP/CIRCUIT）|
| 执行 | Jupiter 聚合器链上 | 手动/富途API（待接入）|

### 可以借鉴的思路

1. **公式即 Token**：把因子选股公式参数化为 token 序列，可以用 Transformer 搜索最优组合——这比手动调参更系统化。可以考虑在 `SignalAgent` 里引入类似的公式搜索机制。

2. **回测即奖励**：用回测打分直接驱动模型优化，而不是用预测精度——这和本系统的知识库第09课（监督学习局限性）理念一致。

3. **LoRD 正则化**：在高噪声市场（meme coin/A股 uncertain 状态）中，低秩约束有助于防止过拟合。如果未来引入 ML 信号，可以参考这个正则化方式。

4. **中位数评估**：用 `median score` 而非 `mean score` 评估策略，对异常值更鲁棒——本系统的回测报告可以加这个指标。

5. **交易成本显式建模**：市场冲击（交易额/流动性）的显式建模，比固定手续费更准确——A股中大单买入同样有冲击成本。

---

## 七、A股实验结论（2026-06）

实际在 A 股上跑了 3000 步 REINFORCE 训练（200只股票 × 60天，MPS加速），结果：

| 指标 | 数值 |
|------|------|
| 最优公式 Score | -0.099（负值）|
| 收敛情况 | 第550步就卡住，3000步无突破 |
| 根本原因 | A股单边手续费 0.16%（来回0.32%）太高，公式产生的换手成本吃掉了所有Alpha |

**结论：AlphaGPT 不适合直接用于 A 股个股交易（高手续费市场）。**

它在 Solana meme coin 上有效（手续费仅0.6%），核心差异就是成本。

如果未来想继续探索，两个方向：
1. 目标改为 A 股 ETF（510300/510500等）：换手成本 < 0.05%，低10倍
2. 降低成本假设找公式结构，再手动控制换手率

---

## 八、一句话 Takeaway（理念层面，不考虑成本）

> AlphaGPT 的核心是：**让机器自动写因子公式，用回测结果训练写公式的机器**。
> 分层设计清晰：模型层只管"哪个因子好"，执行层只管"怎么交易"，两层通过一个 JSON 公式文件解耦。
