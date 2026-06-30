# 券商的平台和API

## 一、Prime Broker（主力经纪商）

顶级量化对冲基金通过 **Prime Brokers** 执行交易，而非零售平台。常见包括：

- Goldman Sachs
- Morgan Stanley
- JPMorgan Chase
- **IBKR Prime Services**（针对中小型基金）

这些机构提供融资、证券借贷、清算、低延迟执行等服务。

---

## 二、零售级量化 API

### 富途 OpenAPI

富途牛牛提供 OpenAPI，支持：

- **行情接口**：实时报价、K线、tick数据
- **交易接口**：下单、撤单、改单、查询
- **支持市场**：港股、美股、A股通、期货、期权
- **支持语言**：Python、Java、C#、C++、JavaScript
- **架构**：需运行本地网关程序 **Futu OpenD**

适合中低频策略，不适合机构级超高频交易。

---

## 三、API 延迟分析

### IBKR 接口类型

- **TWS API**：通过 TWS 或 IB Gateway 连接
- **Client Portal API**：RESTful HTTP 接口
- **FIX CTCI**：机构级 FIX 协议（需单独申请）

### 延迟对比

| 类型 | 延迟 | 适用场景 |
|------|------|----------|
| 零售交易者 | 70ms+ | 中低频策略 |
| 机构Prime Broker | < 1ms | HFT、算法交易 |
| VPS优化后零售 | ~1ms到IB，3-5ms到交易所 | 中频优化 |

HFT要求延迟 `< 1ms`，零售API的 round-trip latency 通常在 **50–100ms**，不适合高频场景。