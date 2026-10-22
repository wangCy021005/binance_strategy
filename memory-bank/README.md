# 币安量化策略 — Memory Bank

> 最后更新：2026-10-22（Windows 依赖适配、实盘执行缺口修复）
> 接手 AI 必读：本文档是唯一可信的项目状态源。CLAUDE.md 的部分内容已过时。
> 下文为 10-22 Windows 实盘修复集；发布状态以 Git 为准，服务器是否部署须核对服务器版本与验证结果。

---

## ⚠️ 重要状态变更（2026-10-20/21，推翻旧基准）

**旧基准（00cbef4c，2026-07-01）已作废**。原因：发现止损滑出 bug——`check_stops` 只用收盘价检查，盘中击穿被漏检，回测/模拟收益含大量虚假利润（+31.58% 的模拟曲线实际是 -31.56%）。所有旧参数结论（fix-001~008 的数值）基于失真模拟器，不可再引用。

**新策略「集中持仓 v2」**（commit c568aee2 附近，2026-10-21）经实验框架 9 轮 ~40 组变体、双窗口验证后上线。

---

## 当前系统架构（三节点）

```
阿里云国内服务器 118.178.121.83（root crontab，每天 UTC 00:10）
  → run_live.py --dry-run 模拟盘（唯一数据推送者）
  → 推 data/*.json 到 GitHub main（走 Contents API 绕墙）
  → Vercel 看板 https://binance-strategy-henna.vercel.app 读 raw.githubusercontent.com
  → 登录方式：网页终端 admin + sudo（root SSH 密码不在本地）

家里 Windows 电脑（实盘节点，2026-10-22 部署中）
  → run_live.py --live 真实下单（币安 fapi.binance.com 被墙，走本机代理 127.0.0.1:7897）
  → SKIP_GITHUB_PUSH=1（不推数据，避免和服务器打架）
  → 用户已切换单向持仓并手动首跑；实盘状态仅在本机保存

本地 Mac /Users/wangcy/binance_strategy（开发节点）
  → 策略实验、代码修改、push
  → 本地 crontab 无币安任务（勿加，会和服务器双推打架）
```

## 当前策略配置（backend/config.py，双窗口验证）

| 配置项 | 值 | 说明 |
|---|---|---|
| top_k_signals | 1 | 只做评分最高的信号 |
| solo_pos_pct | 0.60 | 集中持仓单仓 60% |
| max_hold_days | 20 | 持仓超时平仓（动量衰减） |
| cooldown_days | 3 | 同币止损后冷静期 |
| trailing_stop_pct | 0.20 | 追踪止损（从 12% 放宽） |
| hard_stop | -0.08 | 硬止损（收盘确认模式） |
| 止损模式 | 收盘确认 | 每日 00:10 单次检查 = 真实执行模型 |

**业绩（诚实模拟器重放）**：
- 2025-01→今：年化 +46.3%，Sharpe 1.04，MDD -37%
- 2022-01→今：年化 +109.5%，Sharpe 1.30，MDD -54%
- 模拟盘实跑（服务器）：NAV 2.6884（2026-10-21），45 笔，胜率 44.4%

## 关键文件

| 文件 | 作用 |
|---|---|
| scripts/experiment.py | 策略实验框架（变体扫描、双窗口验证，寻优入口） |
| scripts/backfill_sim.py | 净值曲线重放（改策略后跑它刷新基线） |
| scripts/run_live.py | 每日运行入口（--dry-run 模拟 / --live 实盘） |
| backend/live/sim_exchange.py | SimExchange 模拟器（record_equity/open/close 带 ts 参数） |
| backend/live/live_engine.py | 主引擎（数据更新→止损→超时→信号→开仓→推送） |
| backend/live/exchange.py | 币安实盘接口（支持 PROXY_URL 环境变量） |
| backend/live/position_manager.py | 实盘独立状态、持仓对账、退出/冷静期、订单结果确认 |
| .runtime/live-account.json | 本机实盘状态，含订单 pending；禁止上传或与模拟状态互换 |
| docs/live-node-deployment.md | Windows 实盘与阿里云模拟盘的同步边界、恢复说明 |
| backend/config.py | 所有参数唯一入口 |

## 实验负结论（勿重做，2026-10-21 验证）

- 均值回归 RSI 极值：-22%（阴跌接刀）
- 裸 carry 做空高费率币：-82%（无现货对冲=方向自杀）
- BTC 趋势过滤：-24%（熊市反弹专杀趋势跟随）
- 快动量 20/60/120：噪音，慢动量（默认 42/126/252）最优
- ranging 仓位放大/槽位增加：信号质量才是天花板
- 组合熔断（5日内N止损停开仓）：挡住再入场=挡住利润
- MATIC 已从币安下架，已从 config 移除（2026-10-20）

## 2026-10-20/21 修复历史（当前代码状态）

1. 净值曲线时间戳 bug：record_equity 用 now() → 加 ts 参数传真实交易日
2. 交易记录时间戳同源 bug：open_position/close_position 同样加 ts
3. 止损滑出修复：check_stops 支持 bar_extremes（盘中击穿按止损价成交）——但生产用收盘确认模式（与真实执行一致）
4. 看板前端三个 bug：useSimAccount 缺 simEquity 返回值 / KPI 卡片读静态回测 stats / 交易表读回测旧数据——全部改读 sim_account.json
5. fetch timeout 180s→600s；数据滞后≥3天写 data_staleness_alert.json 告警
6. equity_history 保留 500→1000 条

## Windows 接入状态（2026-10-22）

- Windows 修复集基于 `d8e127b`；Python 3.10 虚拟环境与依赖可用，Windows 安装方式见根 README。
- `.env` 已配置本地代理与 `SKIP_GITHUB_PUSH=1`。模拟空跑已完成，推送已跳过。
- 用户手动首跑暴露鉴权失败回退假资金、CCXT 永续 symbol 不匹配等问题，随后已修复；该次运行自然结束。只读检查未发现真实持仓。
- 用户已在币安切换为单向持仓，并手动完成一次实盘运行；随后只读核对交易所与本地状态一致，pending 已清除。持仓模式阻断已解除，代码没有修改账户模式。具体余额、仓位及订单标识只保留在本机，不写入公共交接文档。
- Clash 开机自启、插电不睡眠/不休眠已配置；没有创建实盘定时任务。
- `run_live.py` 是每日单次程序，正常完成会退出，不是常驻守护进程。

本次补齐的实盘分支：

1. 鉴权、余额或持仓读取失败立即中止，不再使用 10000 假资金，也不把查询失败当作空仓。
2. `ETH/USDT` 等策略符号转换为 CCXT USDT 永续符号；按原始合约数量、`reduceOnly` 平仓。
3. 按现有配置执行单信号 60%、硬止损、追踪止损、20 天超时与 3 天同币止损冷静期；不修改策略参数。
4. `.runtime/live-account.json` 独立保存开仓时间、峰值、持仓量、交易原因及待确认订单；重启先对账，未知/变化持仓阻断。
5. 下单前保存唯一 client order ID 和精确数量；下单只提交一次。通过只读订单查询核对终态、成交量与账户持仓，结果不明不重发。
6. 相同已收盘日线决策去重；CLI 进程锁防并发。实盘模式强制跳过 GitHub 推送，即使遗漏环境变量也不发布账户数据。
7. 实盘数据检查：包含 BTC 的最新连续日线，最低 `max(252, mom_long_bars + 10)` 根（当前 262）；资金费率核对策略 `<= latest_ts` 切片的最近 9 期，行情/数据更新失败中止。

当前离线测试 49 项通过，独立只读复核通过；离线测试不发真实订单，用户随后已手动完成一次实盘成交并对账。待确认订单或异常遗留锁须按 [部署与恢复说明](../docs/live-node-deployment.md) 核对，禁止删除整个 `.runtime` 来重试。每日任务仍未创建，用户手动设置命令见 [Windows 每日任务](../docs/windows-daily-task.md)。

## 实盘风险须知

- 单仓 60% 集中：-37% 级回撤是策略本性，200U 是学费预算
- 收盘确认止损的隔夜 gap：单笔实际亏损可远超 -8%（模拟见 -25% 案例）
- API 白名单必须对应访问币安的实际出口 IP；走代理时不能直接用家用宽带 IP。出口变化后需重新核对并更新白名单，保留 IP 限制。
- 代理故障或电脑关机/休眠会错过该次检查；当前没有常驻补跑或自动故障通知。已增加实盘订单确认与非零错误退出，但这不等于持续监控。

## 服务器运维备忘

- 本次共享源码修复应同步至服务器，服务器仍运行 `--dry-run` 并保持唯一发布者。是否部署成功须核对服务器 Git 版本和离线测试结果。
- 部署前先备份服务器自己的模拟账户、数据与数据库，再检查 Git 差异。不要照旧命令直接 `checkout -- data/` 丢弃运行状态；不要把 Windows 的 data/、.env、.runtime 或数据库覆盖到服务器。
- `cache_db/crypto_data.db` 与多个 `data/*.json` 已被 Git 跟踪，`.gitignore` 不会自动取消跟踪。提交时只暂存源码、测试和文档；不要 `git add .`。
- GitHub Raw CDN 缓存 ~5 分钟：看板数据改动后没变先等 5 分钟再排查
- `fetch_data.py --all` 本次已补为同时抓 BTC 与策略品种，并显式传递代理；首次迁移仍需足量历史缓存，默认最近 35 天不足以生成长期动量。
- 旧前端 frontend/ 已删，用 frontend-react/
