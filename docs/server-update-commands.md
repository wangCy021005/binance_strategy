# 手动发布源码并更新阿里云模拟节点

先核对 Windows 上的源码提交是否已推送，推送成功后才执行服务器段。代码发布与服务器部署是两件事；服务器继续保持模拟模式，不新增实盘任务。

## 1. Windows PowerShell：只发布源码、测试、文档

```powershell
Set-Location C:\Users\10626\binance_strategy
if ((git branch --show-current).Trim() -ne 'main') { throw '当前不是 main，请停止核对分支' }

.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw '测试失败，停止发布' }

git add -- .gitignore README.md requirements.txt scripts/setup.sh scripts/fetch_data.py scripts/run_live.py backend/live/exchange.py backend/live/live_engine.py backend/live/position_manager.py tests docs memory-bank/README.md
if ($LASTEXITCODE -ne 0) { throw '暂存失败，停止发布' }
$blocked = git diff --cached --name-only | Where-Object { $_ -match '^(data/|cache_db/|\.runtime/|\.venv/|\.env$)' }
if ($blocked) { throw '暂存区包含运行数据或私密配置，停止提交并检查 git diff --cached --name-only' }
git diff --cached --stat

if (git diff --cached --name-only) {
    git -c user.name=wangCy021005 -c user.email=97779498+wangCy021005@users.noreply.github.com commit -m "fix: harden live execution and Windows data fetching"
    if ($LASTEXITCODE -ne 0) { throw '提交失败，停止推送' }
}
git -c http.proxy=http://127.0.0.1:7897 push origin main
if ($LASTEXITCODE -ne 0) { throw '推送失败，停止服务器更新；不要强制推送' }
git log -1 --oneline
```

如果 Git 提示远端已有新提交，停止并保留输出，先处理差异。不要强推或暂存 Windows 的 `data/`、数据库、`.env`、`.runtime`。

## 2. 阿里云网页终端：先进入 root

```bash
sudo -i
```

看到 root 提示符后粘贴下面完整的一段。它在子 shell 中执行，任何错误都会停止后续步骤并返回提示符；不会自动丢弃 Git 改动。

```bash
(
set -e
cd /root/binance_strategy
test -x .venv/bin/python
if pgrep -f '[s]cripts/(run_live|fetch_data)\.py' >/dev/null; then
    echo '有交易或数据更新进程正在运行，稍后再更新。'
    exit 1
fi

umask 077
backup_dir="/root/binance_strategy-backups/$(TZ=Asia/Shanghai date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cp -a data "$backup_dir/data"
if [ -f .env ]; then cp -a .env "$backup_dir/.env"; fi
crontab -l > "$backup_dir/crontab.txt" 2>/dev/null || true
git status --short > "$backup_dir/git-status.txt"
git diff -- . ':!cache_db/crypto_data.db' > "$backup_dir/local-changes.patch"
.venv/bin/python -c 'import sqlite3,sys; src=sqlite3.connect("file:cache_db/crypto_data.db?mode=ro",uri=True); dst=sqlite3.connect(sys.argv[1]); src.backup(dst); dst.close(); src.close()' "$backup_dir/crypto_data.db"
echo "备份完成：$backup_dir"

if ! git diff --cached --quiet; then
    echo '服务器有暂存中的改动，请先核对，停止更新。'
    exit 1
fi
saved_runtime=''
restore_runtime() {
    if [ -n "$saved_runtime" ]; then
        git restore --source="$saved_runtime" --worktree -- data/
        echo "服务器模拟数据已恢复；保留恢复快照：$saved_runtime"
    fi
}
trap restore_runtime EXIT
if ! git diff --quiet HEAD -- data/; then
    git stash push -m "server-runtime-$(TZ=Asia/Shanghai date +%Y%m%d-%H%M%S)" -- data/
    saved_runtime=$(git rev-parse refs/stash)
fi
git pull --ff-only origin main
restore_runtime
saved_runtime=''
trap - EXIT
test -f backend/live/position_manager.py
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
git log -1 --oneline
if crontab -l | grep -q 'run_live\.py.*--live'; then
    echo '发现实盘定时命令，请停止并核对服务器任务。'
    exit 1
fi
if crontab -l | grep -q 'run_live\.py.*--dry-run'; then
    echo '已找到模拟盘定时命令；本次没有修改 cron。'
else
    echo '未找到模拟盘定时命令，请核对原任务，暂不新建。'
    exit 1
fi
echo '源码更新及离线验证完成；下一次正常模拟任务仍由原 cron 执行。'
)
```

如果 `.venv/bin/python` 不存在、Git 提示其他本地改动冲突、网络失败或测试失败，就停在该错误处，把错误发回核对；不要执行 `git reset --hard`、`checkout -- data/` 或强制推送。数据暂存只限 `data/`，原数据会在拉取成功后立即恢复，拉取失败退出时也通过 EXIT trap 恢复。保留 stash 快照，不自动删除。数据库备份通过 SQLite backup 接口包含已提交 WAL 数据，不直接拷贝运行中的主数据库文件。

此过程不额外运行生产模拟盘，避免重复结算；保留服务器自己的模拟账户、缓存、环境变量、日志和原有任务。推送到 GitHub 与拉取到服务器均需分别成功，Windows 只提交源码不会让服务器自动更新。
