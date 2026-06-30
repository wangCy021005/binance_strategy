# FIX协议入门

## 一、什么是 FIX 协议？

**FIX（Financial Information eXchange）**：金融信息交换协议，是电子交易的行业标准通信协议。

```
你的交易系统 ←──FIX消息──→ 券商/交易所

发送: "我要买 100 股 AAPL，限价 $185"
接收: "订单已收到，编号 12345"
接收: "50 股成交于 $185.00"
接收: "剩余 50 股成交于 $185.01"
```

### 为什么需要 FIX？

| 问题 | 没有 FIX | 有 FIX |
|------|---------|--------|
| 接入新券商 | 重新开发对接 | 换配置即可 |
| 多券商交易 | N 套代码 | 1 套代码 |
| 订单状态同步 | 各家格式不同 | 标准化消息 |

### FIX 协议版本

| 版本 | 发布年份 | 主要用途 |
|------|---------|---------|
| FIX 4.0 | 1996 | 历史版本 |
| FIX 4.2 | 2000 | 仍有使用 |
| FIX 4.4 | 2003 | **最常用** |
| FIX 5.0 | 2006 | 新功能 |
| FIXT 1.1 | 2008 | 传输层分离 |

大多数券商和交易所支持 **FIX 4.4**。

---

## 二、FIX 消息结构

### 消息格式

FIX 消息是**键值对**的序列，用 SOH（ASCII 01）分隔：

```
8=FIX.4.4|9=176|35=D|49=SENDER|56=TARGET|34=2|52=20240101-09:30:00.000|
11=ORD001|21=1|55=AAPL|54=1|60=20240101-09:30:00.000|38=100|40=2|44=185.00|
59=0|10=123|
```

**人类可读版本**：

```
8=FIX.4.4        # 协议版本
9=176            # 消息体长度
35=D             # 消息类型（D=新订单）
49=SENDER        # 发送方 ID
56=TARGET        # 接收方 ID
34=2             # 消息序号
52=20240101-09:30:00.000  # 发送时间
11=ORD001        # 客户订单 ID
21=1             # 执行指令（1=自动）
55=AAPL          # 股票代码
54=1             # 买卖方向（1=买）
60=20240101-09:30:00.000  # 交易时间
38=100           # 订单数量
40=2             # 订单类型（2=限价）
44=185.00        # 限价价格
59=0             # 有效期（0=当日有效）
10=123           # 校验和
```

### 消息分层

```
┌─────────────────────────────────────────────────────────────┐
│                     FIX 消息结构                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Header（消息头）                                     │   │
│  │   8=版本  9=长度  35=类型  49=发送方  56=接收方      │   │
│  │   34=序号  52=时间                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Body（消息体）                                       │   │
│  │   根据消息类型（Tag 35）不同而不同                   │   │
│  │   订单消息: 55=标的 54=方向 38=数量 44=价格...       │   │
│  └─────────────────────────────────────────────────────┘   │
│                            ↓                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Trailer（消息尾）                                    │   │
│  │   10=校验和                                         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、核心消息类型

### 会话层消息

| MsgType (35) | 名称 | 用途 |
|-------------|------|------|
| A | Logon | 建立会话 |
| 5 | Logout | 断开会话 |
| 0 | Heartbeat | 心跳检测 |
| 1 | TestRequest | 测试连接 |
| 2 | ResendRequest | 请求重发 |
| 4 | SequenceReset | 序号重置 |

### 应用层消息（订单相关）

| MsgType (35) | 名称 | 方向 | 用途 |
|-------------|------|------|------|
| D | NewOrderSingle | 客户→券商 | 提交新订单 |
| F | OrderCancelRequest | 客户→券商 | 撤销订单 |
| G | OrderCancelReplaceRequest | 客户→券商 | 修改订单 |
| 8 | ExecutionReport | 券商→客户 | 订单状态/成交回报 |
| 9 | OrderCancelReject | 券商→客户 | 撤单拒绝 |

### 市场数据消息

| MsgType (35) | 名称 | 用途 |
|-------------|------|------|
| V | MarketDataRequest | 订阅行情 |
| W | MarketDataSnapshotFullRefresh | 行情快照 |
| X | MarketDataIncrementalRefresh | 行情增量更新 |

---

## 四、关键 Tag 详解

### 订单方向 (Tag 54 - Side)

| 值 | 含义 |
|----|------|
| 1 | Buy（买入）|
| 2 | Sell（卖出）|
| 5 | Sell Short（卖空）|
| 6 | Sell Short Exempt（豁免卖空）|

### 订单类型 (Tag 40 - OrdType)

| 值 | 含义 | 必填 Tag |
|----|------|---------|
| 1 | Market（市价单）| 无 |
| 2 | Limit（限价单）| 44=价格 |
| 3 | Stop（止损单）| 99=触发价 |
| 4 | Stop Limit（止损限价单）| 44=限价, 99=触发价 |
| P | Pegged（锚定单）| 特定字段 |

### 订单有效期 (Tag 59 - TimeInForce)

| 值 | 含义 | 说明 |
|----|------|------|
| 0 | Day | 当日有效 |
| 1 | GTC | 直到取消 |
| 2 | OPG | 开盘竞价 |
| 3 | IOC | 立即成交或取消 |
| 4 | FOK | 全部成交或取消 |
| 6 | GTD | 指定日期前有效 |

### 订单状态 (Tag 39 - OrdStatus)

| 值 | 含义 |
|----|------|
| 0 | New（已接受）|
| 1 | Partially Filled（部分成交）|
| 2 | Filled（全部成交）|
| 4 | Canceled（已撤销）|
| 8 | Rejected（被拒绝）|
| C | Expired（已过期）|

### 执行类型 (Tag 150 - ExecType)

| 值 | 含义 |
|----|------|
| 0 | New（新订单确认）|
| F | Trade（成交）|
| 4 | Canceled（撤销确认）|
| 8 | Rejected（拒绝）|
| C | Expired（过期）|

---

## 五、典型消息流

### 正常下单流程

```
客户                                    券商
  │                                      │
  │ ────── NewOrderSingle (35=D) ──────→ │
  │        11=ORD001, 55=AAPL,           │
  │        54=1, 38=100, 40=2, 44=185    │
  │                                      │
  │ ←── ExecutionReport (35=8) ───────── │
  │     150=0 (New), 39=0 (New)          │
  │     订单已接受                        │
  │                                      │
  │ ←── ExecutionReport (35=8) ───────── │
  │     150=F (Trade), 39=1 (PartFilled) │
  │     31=185.00, 32=50                 │
  │     成交 50 股于 $185.00             │
  │                                      │
  │ ←── ExecutionReport (35=8) ───────── │
  │     150=F (Trade), 39=2 (Filled)     │
  │     31=185.01, 32=50                 │
  │     成交剩余 50 股于 $185.01         │
  │                                      │
```

### 撤单流程

```
客户                                    券商
  │                                      │
  │ ── OrderCancelRequest (35=F) ──────→ │
  │    11=CANCEL001, 41=ORD001           │
  │    (41=原订单 ID)                    │
  │                                      │
  │ ←── ExecutionReport (35=8) ───────── │
  │     150=4 (Canceled), 39=4           │
  │     撤单成功                         │
  │                                      │

或者撤单失败：

  │ ←── OrderCancelReject (35=9) ─────── │
  │     102=1 (Unknown order)            │
  │     撤单失败：订单不存在             │
  │                                      │
```

### 会话建立

```
客户                                    券商
  │                                      │
  │ ────────── Logon (35=A) ───────────→ │
  │            98=0 (无加密)             │
  │            108=30 (心跳间隔 30s)     │
  │                                      │
  │ ←────────── Logon (35=A) ─────────── │
  │             会话建立成功             │
  │                                      │
  │ ←───────── Heartbeat (35=0) ──────── │
  │             每 30 秒                 │
  │ ────────── Heartbeat (35=0) ───────→ │
  │                                      │
```

---

## 六、Python 实现示例

### 使用 QuickFIX

```python
import quickfix as fix
import quickfix44 as fix44

class TradingApplication(fix.Application):
    """FIX 交易应用"""

    def __init__(self):
        super().__init__()
        self.session_id = None
        self.order_id = 0

    def onCreate(self, session_id):
        """会话创建"""
        self.session_id = session_id
        print(f"Session created: {session_id}")

    def onLogon(self, session_id):
        """登录成功"""
        print(f"Logged on: {session_id}")

    def onLogout(self, session_id):
        """登出"""
        print(f"Logged out: {session_id}")

    def toAdmin(self, message, session_id):
        """发送管理消息前的回调"""
        pass

    def fromAdmin(self, message, session_id):
        """收到管理消息"""
        pass

    def toApp(self, message, session_id):
        """发送应用消息前的回调"""
        print(f"Sending: {message}")

    def fromApp(self, message, session_id):
        """收到应用消息"""
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)

        if msg_type.getValue() == fix.MsgType_ExecutionReport:
            self._handle_execution_report(message)

    def _handle_execution_report(self, message):
        """处理执行报告"""
        exec_type = fix.ExecType()
        message.getField(exec_type)

        if exec_type.getValue() == fix.ExecType_FILL:
            # 成交回报
            order_id = fix.ClOrdID()
            last_px = fix.LastPx()
            last_qty = fix.LastQty()

            message.getField(order_id)
            message.getField(last_px)
            message.getField(last_qty)

            print(f"Fill: {order_id.getValue()} "
                  f"{last_qty.getValue()} @ {last_px.getValue()}")

    def send_new_order(self, symbol: str, side: str,
                       quantity: int, price: float):
        """发送新订单"""
        self.order_id += 1
        cl_ord_id = f"ORD{self.order_id:06d}"

        order = fix44.NewOrderSingle()

        # 必填字段
        order.setField(fix.ClOrdID(cl_ord_id))
        order.setField(fix.Symbol(symbol))
        order.setField(fix.Side(fix.Side_BUY if side == 'buy'
                                else fix.Side_SELL))
        order.setField(fix.OrderQty(quantity))
        order.setField(fix.OrdType(fix.OrdType_LIMIT))
        order.setField(fix.Price(price))
        order.setField(fix.TimeInForce(fix.TimeInForce_DAY))
        order.setField(fix.TransactTime())

        fix.Session.sendToTarget(order, self.session_id)

        return cl_ord_id

    def cancel_order(self, orig_cl_ord_id: str, symbol: str, side: str):
        """撤销订单"""
        self.order_id += 1
        cl_ord_id = f"CXL{self.order_id:06d}"

        cancel = fix44.OrderCancelRequest()

        cancel.setField(fix.ClOrdID(cl_ord_id))
        cancel.setField(fix.OrigClOrdID(orig_cl_ord_id))
        cancel.setField(fix.Symbol(symbol))
        cancel.setField(fix.Side(fix.Side_BUY if side == 'buy'
                                 else fix.Side_SELL))
        cancel.setField(fix.TransactTime())

        fix.Session.sendToTarget(cancel, self.session_id)

        return cl_ord_id
```

### 配置文件

```ini
# fix_client.cfg

[DEFAULT]
ConnectionType=initiator
ReconnectInterval=5
FileStorePath=./store
FileLogPath=./log
StartTime=00:00:00
EndTime=00:00:00
UseDataDictionary=Y
DataDictionary=./FIX44.xml
ValidateUserDefinedFields=N

[SESSION]
BeginString=FIX.4.4
SenderCompID=YOUR_CLIENT_ID
TargetCompID=BROKER_ID
SocketConnectHost=fix.broker.com
SocketConnectPort=9876
HeartBtInt=30
```

### 启动客户端

```python
def main():
    settings = fix.SessionSettings("fix_client.cfg")
    application = TradingApplication()
    store_factory = fix.FileStoreFactory(settings)
    log_factory = fix.FileLogFactory(settings)

    initiator = fix.SocketInitiator(
        application, store_factory, settings, log_factory
    )

    initiator.start()

    try:
        # 等待登录
        import time
        time.sleep(2)

        # 发送订单
        order_id = application.send_new_order(
            symbol="AAPL",
            side="buy",
            quantity=100,
            price=185.00
        )
        print(f"Order submitted: {order_id}")

        # 保持运行
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        initiator.stop()
```

---

## 七、常见问题与排查

### 序号不同步

```
问题: "MsgSeqNum too low, expecting 100 but received 50"

原因: 客户端和服务端的消息序号不一致

解决方案:
1. 发送 SequenceReset (35=4) 重置序号
2. 或在 Logon 消息中设置 ResetSeqNumFlag (141=Y)
3. 生产环境：使用持久化存储保持序号
```

### 心跳超时

```
问题: 连接断开，日志显示心跳超时

原因: 网络延迟或阻塞

解决方案:
1. 检查网络连接
2. 增加 HeartBtInt 值（但不要太大）
3. 确保应用没有长时间阻塞
```

### 订单被拒绝

```
问题: ExecutionReport 显示 OrdStatus=8 (Rejected)

排查步骤:
1. 检查 Tag 58 (Text) 获取拒绝原因
2. 常见原因:
   - 资金不足 (Insufficient funds)
   - 标的不可交易 (Symbol not found)
   - 价格超出限制 (Price out of range)
   - 数量不符合规则 (Invalid quantity)
```

### 消息解析工具

```python
def parse_fix_message(raw_message: str) -> dict:
    """解析 FIX 消息为字典"""
    # 替换 SOH 为可见字符
    if '\x01' in raw_message:
        raw_message = raw_message.replace('\x01', '|')

    fields = {}
    for pair in raw_message.split('|'):
        if '=' in pair:
            tag, value = pair.split('=', 1)
            fields[int(tag)] = value

    return fields


def format_fix_message(fields: dict) -> str:
    """格式化打印 FIX 消息"""
    tag_names = {
        8: 'BeginString',
        9: 'BodyLength',
        35: 'MsgType',
        49: 'SenderCompID',
        56: 'TargetCompID',
        34: 'MsgSeqNum',
        52: 'SendingTime',
        11: 'ClOrdID',
        55: 'Symbol',
        54: 'Side',
        38: 'OrderQty',
        40: 'OrdType',
        44: 'Price',
        39: 'OrdStatus',
        150: 'ExecType',
        31: 'LastPx',
        32: 'LastQty',
        10: 'CheckSum',
    }

    lines = []
    for tag, value in sorted(fields.items()):
        name = tag_names.get(tag, f'Tag{tag}')
        lines.append(f"  {tag:>3} ({name}): {value}")

    return '\n'.join(lines)
```

---

## 八、安全注意事项

### 生产环境要求

| 要求 | 说明 |
|------|------|
| TLS/SSL | 必须使用加密连接 |
| IP 白名单 | 券商通常限制连接 IP |
| 证书认证 | 部分券商要求客户端证书 |
| 序号持久化 | 防止重启后序号冲突 |
| 消息日志 | 所有消息必须记录备查 |

### 测试环境

1. 大多数券商提供 UAT（用户验收测试）环境
2. 先在 UAT 测试所有消息类型
3. 模拟各种异常场景（网络断开、消息乱序等）
4. 验证订单生命周期完整性

---

## 九、常见误区

**误区一：FIX 协议很复杂，只有专业机构才需要**

对于直接对接券商的量化交易者，理解 FIX 是必要的。即使使用封装好的 API，了解底层协议有助于排查问题。

**误区二：所有券商的 FIX 实现都一样**

虽然 FIX 是标准协议，但各券商可能有：
- 自定义 Tag
- 不同的必填字段要求
- 特定的消息流程

**误区三：可以忽略会话层管理**

会话层（心跳、序号）的正确处理是稳定运行的基础。忽略这些会导致连接不稳定和消息丢失。

---

## 十、总结

| 要点 | 说明 |
|------|------|
| 核心用途 | 订单提交、成交回报、撤单 |
| 消息结构 | Header + Body + Trailer，键值对格式 |
| 关键消息 | D(新订单), 8(执行报告), F(撤单) |
| 实现方式 | QuickFIX 是最常用的开源库 |
| 生产要求 | TLS、序号持久化、完整日志 |

---

## 延伸阅读

- [FIX Protocol 官网](https://www.fixtrading.org/) — 官方文档和规范
- [QuickFIX 文档](https://quickfixengine.org/) — 开源 FIX 引擎
- 第 19 课：执行系统 — Execution Agent 设计
