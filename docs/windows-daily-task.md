# Windows 每日运行任务（由用户手动创建）

`run_live.py` 是一次执行程序，结束后退出。日线策略每天检查一次仓位，不持续盯盘，也不会在程序退出后继续执行止损。

以下命令由用户在本机管理员 PowerShell 手动执行，会创建每天北京时间 08:15 执行实盘逻辑的任务，届时可能产生真实订单。首次触发从创建后的下一天开始，不立即启动程序。任务使用当前 Windows 用户的交互登录身份，不保存账户密码。

```powershell
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\10626\binance_strategy'
if (Get-ScheduledTask -TaskName 'binance-live' -ErrorAction SilentlyContinue) { throw '任务已存在，请先核对，勿重复创建' }
Add-Content -LiteralPath "$root\.env" -Value "`nPYTHONUTF8=1" -Encoding utf8
$action = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\python.exe" -Argument "-X utf8 `"$root\scripts\run_live.py`" --live" -WorkingDirectory $root
$firstRun = (Get-Date).Date.AddDays(1).AddHours(8).AddMinutes(15)
$trigger = New-ScheduledTaskTrigger -Daily -At $firstRun
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'binance-live' -Action $action -Trigger $trigger -Principal $principal -Settings $settings
Get-ScheduledTaskInfo -TaskName 'binance-live' | Select-Object NextRunTime, LastRunTime, LastTaskResult
```

`NextRunTime` 应显示下一天 08:15。此段不调用 `Start-ScheduledTask`，不会为了测试再次发起实盘运行。保持电脑开机、Windows 用户已登录、代理在运行；锁屏仍属于已登录，注销或关机会影响执行。唤醒设置不能让已经关机的电脑自行完成交易。

每日程序日志保存在 `logs/live.log`。如果任务或脚本失败，不应把“任务已创建”当作“交易已完成”；结合任务结果、日志与交易所持仓核对。异常 pending 或遗留锁按 [恢复说明](live-node-deployment.md) 处理。

登录类型参考 [Microsoft Task Scheduler 文档](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)。服务器仍只跑模拟盘，服务器更新命令见 [源码发布及服务器更新](server-update-commands.md)。
