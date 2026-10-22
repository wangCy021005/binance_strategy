# Windows 实盘与阿里云模拟盘：同步、验证、恢复

更新于 2026-10-22。本次源码修复基于 `d8e127b`；发布与部署分别核对 Git 远端和服务器实际版本。用户已自行完成一次实盘运行，自动任务需另外创建和核验。

## 是否要把代码同步到服务器

需要同步共享源码，以免 Mac、Windows、阿里云长期使用不同执行逻辑；**阿里云继续只跑模拟盘**。本次 `fetch_data.py --all` 补齐 BTC、显式代理及依赖补充也作用于模拟节点。Windows 的实盘持仓管理仅在实盘分支启用，不要求阿里云切换运行模式。

| 内容 | 同步方式 |
| --- | --- |
| backend/live/*.py、scripts/run_live.py、scripts/fetch_data.py | 经过测试后经 Git 同步源码 |
| requirements.txt、scripts/setup.sh、README、测试、本文档、交接文档、.gitignore | 随同源码发布；服务器使用自己的 Linux 虚拟环境 |
| .env | 每台机器独立维护，不上传；Windows 保留 SKIP_GITHUB_PUSH=1 与本机代理 |
| .runtime/ | 每个实盘账户本地独立保存，含持仓与 pending；绝不能拷给模拟节点 |
| data/*.json | 服务器自己的模拟状态和看板数据；不发布 Windows 运行生成的版本 |
| cache_db/crypto_data.db | 各节点独立更新缓存；本次代码发布不夹带 Windows 数据库 |
| .venv/、logs/、数据库 WAL/SHM | 不同步；Mac/Windows/Linux 不能互拷虚拟环境 |

`cache_db/crypto_data.db` 和若干 `data/*.json` 已被 Git 跟踪，加入 ignore 不会让它们自动退出跟踪。因此不得以 `git add .` 发布当前工作区；只选择源码、测试和文档。正式推送前还需获取远端最新提交，避免与服务器的 Contents API 数据提交冲突，不使用强制推送。

服务器部署顺序：

1. 避开 UTC 00:10 正在执行的日任务，检查是否仍有模拟实例运行；记录现有 cron 与代码版本。
2. 在仓库外备份服务器自己的 `data/`、`.env`（如有）和 SQLite 数据库。数据库使用 SQLite backup 接口或先确认写进程停止并处理 WAL，不在写入中只拷贝主 `.db` 文件。
3. 检查 `git status` 与目标提交的文件列表。此次源码发布不应夹带 Windows 数据库或运行 JSON。服务器运行 JSON 与旧远端提交冲突时，备份后仅暂存 `data/`，拉取后从该快照恢复服务器数据，失败退出也恢复；具体命令见 [服务器更新命令](server-update-commands.md)。不要直接丢弃整个 `data/`。
4. 在服务器原有 Linux 虚拟环境安装所需依赖，运行 `python -m pip check` 与 `python -m unittest discover -s tests -v`。离线回归覆盖模拟分支，无需为验代码额外跑一轮生产模拟并重复结算。
5. 核对服务器仍是 `--dry-run`，保留原有数据发布配置与每日任务；检查下一次正常任务日志和看板。不要给服务器配置 Windows 本机的 `127.0.0.1:7897` 代理地址。

服务器代码版本、cron、依赖和运行状态需在部署时实查；本地提交、GitHub 推送成功均不能代替服务器验证。

## 本机实盘前提

- 2026-10-22 用户已在币安切换单向持仓并手动完成一次实盘运行，随后只读检查确认交易所与本地记录一致、pending 已清除。此前双向模式阻断已解除；程序不自动切换账户设置。具体账户数据只在本机保留。
- 策略保持 `top_k_signals=1`、`solo_pos_pct=0.60`、1 倍杠杆、硬止损 -8%、追踪回撤 20%（浮盈至少 5%）、超时 20 天、同币止损冷静期 3 天。不新增组合熔断。
- 止损按**已收盘 UTC 日线**确认，不是实时保护单；程序每天只执行一轮。关闭终端、关机、休眠或代理失效会影响尚在运行的程序或下一次任务。运行结束正常退出不代表被杀。
- 数据必须包含 BTC 和策略品种最新连续 `max(252, mom_long_bars + 10)` 根已收盘日线，当前为 262 根。资金费率按策略使用的日线时间戳截止，检查最近 9 个结算记录；只拉最近 35 天不够长期动量回看。
- Windows 使用 `python -X utf8` 或 `PYTHONUTF8=1`。`.env` 启用本机代理，API 白名单核对实际代理出口；代码不替用户修改账户权限或白名单。
- 当前没有实盘计划任务、常驻守护或自动故障通知。单次程序的终端窗口无需全天保留；后续任务需要机器与代理在执行时可用。

## 持久化与异常恢复

实盘状态位于 `.runtime/live-account.json`，与 `data/sim_account.json` 分离，包含账户标识、持仓数量、入场时间、收盘峰值、退出原因、最后处理日线和 pending 订单。状态原子替换保存，绑定 API key 的摘要；更换 key 后会阻断自动接管，需先核对旧状态。

CLI 用 `.runtime/binance-live.lock` 防并发，文件记录 PID。正常退出（含捕获的异常）释放锁；断电/强杀可能遗留。锁存在时先核对记录 PID 对应的进程与命令、是否另有实例运行，再由操作者处理遗留锁。不要按文件年龄自动删锁，更不要删除持仓状态。

每笔订单在提交前保存唯一 client order ID 与预期合约数量。市价单只提交一次；提交超时或返回失败后，查询原 client ID 的订单：

- 终态订单且成交数量与账户持仓一致，才登记完成；终止的部分成交开仓可按已确认数量登记。
- 尚未结束、查询失败、暂未查到、数量/方向不符、平仓仍有剩余仓位：保留 pending 并退出，不自动重发、撤单或继续开仓。
- 下一次启动先只读核对原订单及持仓；能够完整确认才恢复执行。未知仓位、外部改动数量、双向持仓、损坏状态均会阻断。

遇到 pending 时，应在币安核对该 client order ID 对应的订单、状态、累计成交和当前持仓，保存日志与本地状态。不要删除 pending 后直接重跑；如果订单确实未提交、被拒绝或只平掉一部分，需人工决定并校正状态。当前没有自动修复本地状态的命令。

标识参数及查询方式已核对 [Binance 交易接口文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade) 与当前安装的 CCXT 实现（`newClientOrderId` / `origClientOrderId`）。

## 验证证据与范围

Windows 离线验证：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

49 项离线测试通过：资金/鉴权失败、永续 symbol、订单只提交一次、订单标识/数量、终态和部分成交、重启恢复、止损/超时/冷静期、去重/并发、行情/资金费率时点与回看、实盘禁止发布、模拟分支回归。交易 SDK 全部使用 mock 或内存假交易所，不向币安发单。

实际缓存只读校验覆盖 19 个交易品种与 BTC；交易品种最少 1309 根历史日线，最新已收盘日线为 2026-10-21。账户只读接口与单向持仓模式已验证；用户随后手动完成一次实盘成交，交易所与本地状态只读核对一致。这不是持续运行或后续成交的保证；当前仍未创建实盘任务，手动创建说明见 [Windows 每日任务](windows-daily-task.md)。源码发布与服务器更新命令见 [服务器更新命令](server-update-commands.md)。
