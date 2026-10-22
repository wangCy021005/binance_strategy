# 币安量化策略 — Memory Bank

> 最后更新：2026-10-22（大重构 + 实盘启动，两天内变化巨大）
> 接手 AI 必读：本文档是唯一可信的项目状态源。CLAUDE.md 的部分内容已过时。

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
  → 鉴权已验证（API Key 已建：只开合约权限，无提现权）

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

## 实盘接入流程（进行中，家里 Windows）

已完成：鉴权验证（余额可查）、代码带 PROXY_URL + SKIP_GITHUB_PUSH 支持（commit c568aee2）
待执行：
1. 家里 `git pull` + `.env` 加 `SKIP_GITHUB_PUSH=1`
2. `run_live.py --dry-run` 空跑验证
3. `run_live.py --live` 首单（200U，单仓 60%≈120U）
4. Windows 计划任务（schtasks，每天 08:15 北京时间）
5. 保活：代理开机自启 + 插电不睡眠

## 实盘风险须知

- 单仓 60% 集中：-37% 级回撤是策略本性，200U 是学费预算
- 收盘确认止损的隔夜 gap：单笔实际亏损可远超 -8%（模拟见 -25% 案例）
- 家用宽带 IP 若动态变化：API 白名单失效，需 DDNS 或去掉 IP 限制（靠无提现权限兜底）
- 代理单点故障：代理挂→cron 静默失败。缓解：data_staleness_alert 已有，实盘侧待加成交确认检查

## 服务器运维备忘

- 服务器上 git pull 前必须 `sudo git -C /root/binance_strategy checkout -- data/`（丢弃本地数据改动）
- GitHub Raw CDN 缓存 ~5 分钟：看板数据改动后没变先等 5 分钟再排查
- fetch_data 多币种可能中途静默退出，需查 per-symbol 齐度；BTC 要单独拉（symbols 不含它但 Regime 依赖）
- 旧前端 frontend/ 已删，用 frontend-react/
