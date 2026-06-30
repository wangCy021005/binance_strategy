# Tick-L2级盘口数据购买渠道

## 一、Level-2 订单簿数据包含内容

| 类型 | 示例字段 |
|------|---------|
| 买卖挂单深度 | 买1~买10价格和挂单量、卖1~卖10 |
| 挂单明细 | 每个价格档位的排队订单数量、委托笔数 |
| 逐笔成交+撮合方向 | 成交价格、方向（主动买or卖） |
| 盘口异动指标 | 内外盘、委比、量比、委差等衍生指标 |

## 二、Level-2 数据获取渠道

### 1. 交易所官方授权渠道

| 交易所 | 获取方式 | 说明 |
|--------|---------|------|
| 上交所/深交所 | Level-2市场数据授权服务商 | 实时数据需付费授权 |
| CFFEX/中金所 | 期货和期权Level-2 | 高频期权/套利者必备 |
| 港交所(HKEX) | HKEX Orion Market Data平台 | 买卖五档以上 |
| 美股(NASDAQ, NYSE) | NASDAQ TotalView / NYSE OpenBook | 全深度Order Book需订阅 |
| 币圈交易所 | 免费API获取order book | 支持top 20~full book |

> 中国大陆Level-2实时数据需经过"交易所认证的第三方数据服务商授权"，价格较贵。

### 2. 主流Level-2数据服务商

| 平台 | 数据类型 | 可用性 |
|------|---------|--------|
| Wind | A股Level-2（深度+撮合） | 付费 |
| 同花顺iFinD | Level-2深度+逐笔 | 企业级 |
| 聚宽(JoinQuant) | Level-2 Tick | 付费且受限 |
| 掘金量化(RiceQuant) | Level-2实时数据 | 付费 |
| 巨灵、恒生电子 | 专业私募机构使用 | 嵌入OMS |
| 雪球、网易财经 | 仅展示买5卖5 | 不开放API |

### 3. 国际市场Tick/Level-2来源

先分清三种粒度：

| 粒度 | 含义 | 适合用途 |
|------|------|---------|
| L1/NBBO/SIP | 最佳买一卖一、逐笔成交、聚合行情 | 普通实盘、分钟级/秒级策略 |
| L2/MBP | 按价格档位聚合的深度盘口 | 执行模拟、盘口失衡、短周期策略 |
| L3/MBO | 逐笔委托、订单ID、增删改撤事件 | 队列位置模拟、做市研究、HFT研究 |

| 市场 | 主要渠道 | 备注 |
|------|---------|------|
| 美股股票 | NASDAQ TotalView、NYSE OpenBook、Databento、Alpaca | Databento适合历史Tick/L2/L3 |
| 美股期权 | OPRA、Cboe DataShop、Databento OPRA | 完整期权链数据量极大 |
| 美股期货 | CME直连、Databento、IBKR、CQG、Rithmic | 延迟与时间戳质量很关键 |
| 港股 | HKEX OMD-C Standard/Premium/FullTick、Wind | FullTick提供market-by-order订单级数据 |
| 日股 | JPX/TSE付费实时行情、LSEG、Bloomberg | 日文读者优先看JPX授权链路 |
| 欧洲/全球股票 | LSEG Tick History、Bloomberg B-PIPE、ICE | 需确认再分发权与历史深度 |
| 外汇 | Dukascopy、Cboe FX、EBS、TrueFX | Dukascopy提供免费历史tick |
| 加密货币 | Binance、OKX、Coinbase、Tardis.dev | Tardis.dev适合历史L2/L3研究 |

**选择顺序建议：**

| 目标 | 优先选择 |
|------|---------|
| 学习盘口与本地order book | Binance/Coinbase WebSocket、Dukascopy tick |
| 美股策略研究 | Databento历史数据、IBKR订阅 |
| 港股/日股研究 | HKEX/JPX授权数据或认证服务商 |
| 实盘执行模拟 | 交易所L2/L3、Databento、HKEX FullTick |

## 三、Level-2数据费用（粗略）

| 平台/渠道 | 费用模型（参考） | 备注 |
|----------|---------------|------|
| Wind Level-2（A股） | 20,000～50,000+元/月 | 面向机构 |
| 掘金Level-2（实盘） | 3,000+元/月 | 开盘前后可订阅 |
| 聚宽Level-2（企业级） | 10,000+元/月 | 非个人开发者 |
| 港交所OMD/服务商L2 | 交易所授权费+服务商费用 | FullTick数据量最大 |
| 美股交易所深度数据 | 按交易所订阅，个人/专业价格不同 | 含TotalView、OpenBook等 |
| Databento | 历史数据按量计费，实时数据走付费计划 | 可先小样本估算成本 |
| Massive(原Polygon.io)/Alpaca | 订阅制或账户权益 | 适合美股L1/逐笔入门 |
| Tardis.dev | 订阅/API/下载制 | 加密货币历史Tick、L2/L3研究 |
| Dukascopy | 免费历史数据导出 | 适合外汇tick学习和回测 |

> 做预算时不要只看API月费，还需把"交易所授权费、用户数、存储、回放、合规审计、再分发许可"一起算进去。

---

## FPGA与DMA（市场准入）

### 一、什么是FPGA？

**FPGA（Field Programmable Gate Array）** 是一种可编程的硬件芯片，可直接执行特定任务，无需操作系统或CPU参与。

| 任务 | FPGA可实现的功能 |
|------|---------------|
| 市场数据处理 | 纳秒级解析Level-2数据、构建Order Book |
| 信号决策 | 直接在硬件中执行策略判断 |
| 下单撮合 | 发出交易指令，直接接入交易网关 |
| 延迟压缩 | 实现总响应时间 < 1微秒 |

编程需使用Verilog/VHDL，适用于极致低延迟做市、ETF套利、期权高频微结构套利。

### 二、什么是直接市场准入（DMA）？

DMA指交易系统绕过传统券商前置系统，直接将交易请求发送到交易所撮合系统的技术。

| 类型 | 简介 |
|------|------|
| DMA | 通过券商通道，跳过UI和风控，直连交易所 |
| SA（Sponsored Access） | 券商"担保"的访问，客户完全控制订单系统 |
| ULSA（Ultra Low-latency SA） | 纳秒级延迟，风险完全自管，需机构级合规背书 |

### DMA + FPGA的组合

> "DMA提供'通道权'，FPGA提供'速度与决策力'"

机构会在Equinix、@Tokyo等交易所附近部署：
- FPGA卡（做order book + 策略）
- DMA线路（走最短光纤/微波）
- 风控服务（自管或最小化中间环节）

---

## 参考链接

- [CIIS样本L2数据](https://www.ciis.com.hk/hongkong/sc/historicaldata1/sampledata/index.shtml)
- [上交所L2](https://english.sse.com.cn/markets/dataservice/products/)
- [深交所L2授权](http://www.szsi.cn/cpfw/fwsq/hq/yw-2.htm)
- [HKEX OMD-C](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/HKEX-Orion-Market-Data-Platform-Securities-Market-OMD-C)
- [NASDAQ TotalView](https://www.nasdaq.com/solutions/data/equities/nasdaq-totalview)
- [NYSE Real-Time Market Data](https://www.nyse.com/market-data/real-time)
- [Databento](https://databento.com/equities)
- [Tardis.dev](https://tardis.dev/)
- [Dukascopy历史数据](https://www.dukascopy.com/swiss/english/marketwatch/historical/)
- [JPX/TSE实时行情](https://www.jpx.co.jp/english/markets/paid-info-equities/realtime/index.html)