# 币安量化交易系统

基于 AlphaGPT（强化学习公式挖掘） + 规则策略 的加密量化框架。

## 核心优势 vs A股

| | A股 | 币安 |
|--|--|--|
| 做空 | ❌ | ✅ 永续合约 |
| 动量IC | -0.02（反转） | +0.05（跟随） |
| 交易成本 | 0.16%/次 | 0.04%/次 |
| 24/7 | ❌ | ✅ |
| 数据 | 付费 | 免费 API |

## 策略架构

```
Binance API → SQLite缓存 → 特征工程 → 
  Regime识别（BTC趋势）→ 策略路由：
    bull:    动量策略（趋势跟随）
    ranging: 资金费率套利
    bear:    做空 + 防御
    crisis:  全现金
```

## 快速开始

```bash
cd binance_strategy

# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 获取历史数据
python scripts/fetch_data.py --all --start 2022-01-01

# 3. 运行回测
python backend/run_backtest.py

# 4. 训练 AlphaGPT（可选）
python scripts/train_alpha.py --steps 2000
```

### Windows / PowerShell

本机使用 Python 3.10（64 位），依赖安装在项目的 `.venv` 中。macOS 的虚拟环境不能直接复制到 Windows 使用；新机器请重新创建：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# NVIDIA 显卡：先安装 CUDA 12.8 版 PyTorch，再安装其余依赖
# 本机 RTX 3060 使用以下版本验证；其他机器需有兼容的 NVIDIA 驱动
.\.venv\Scripts\python.exe -m pip install "torch==2.11.0+cu128" --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check

# 当前 PowerShell 会话启用 UTF-8，避免中文 JSON 按 Windows 的 GBK 编码读写
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe backend\run_backtest.py --help
.\.venv\Scripts\python.exe scripts\serve_web.py
```

没有 NVIDIA 显卡时，跳过上面的 CUDA 命令即可。CUDA 安装方式参考 [PyTorch 官方安装说明](https://pytorch.org/get-started/previous-versions/)。直接调用 `.venv\Scripts\python.exe` 无需激活环境，也无需调整 PowerShell 执行策略。

迁移检查结果：

- `requirements.txt` 中的库均可用于 Windows；已补上 Web 服务需要的 `Flask`，以及代码直接使用的 `requests`、`python-dotenv`。SQLite 随 Python 提供，无需通过 pip 安装。
- `scripts/setup.sh` 使用 Bash 和 `.venv/bin/activate`，Windows 请使用上面的 PowerShell 命令。
- 多处 JSON 文件读写未显式指定编码；Windows 运行项目时请在当前会话设置 `PYTHONUTF8=1`，或使用 `python -X utf8`。
- AlphaGPT 的设备配置已支持 MPS、CUDA、CPU；`scripts/train_regime.py` 目前只选择 MPS 或 CPU，因此在 Windows 上仍会使用 CPU。
- 本机的 `torch 2.11.0+cu128` 在强制 LSTM 使用 CUDA/cuDNN 后，会在进程退出时崩溃（`0xc0000409`）；AlphaGPT CUDA 和 Regime 默认 CPU 路径验证正常。若自行将 LSTM 改为 CUDA，可先用 `torch.backends.cudnn.enabled = False` 绕过，本机已验证该设置下前后向计算及进程退出正常。
- `scripts/experiment.py` 将结果写入 `/tmp/experiment_results.json`，运行该实验脚本前需改为 Windows 可用的路径。
- `scripts/run_live.py` 注释中的 `export` 和 `crontab` 是 Unix 用法；Windows 应使用 PowerShell 环境变量和任务计划程序。

## 已实现组件

- [x] 数据层（ccxt + SQLite缓存）
- [x] Regime识别（BTC四态：bull/ranging/bear/crisis）
- [x] 动量策略（加密动量IC+，与A股反向不同）
- [x] 资金费率套利（A股特有，加密独有Alpha）
- [ ] 均值回归策略
- [ ] 仓位管理（portfolio.py）
- [ ] 风控Agent（risk_agent.py）
- [ ] 回测引擎（backtest/engine.py）
- [ ] AlphaGPT 加密版（model_core/）

## 关键参数（config.py）

- 实盘默认 1 倍杠杆
- `top_k_signals = 1`、`solo_pos_pct = 0.60`（当前集中持仓配置）
- `max_pos_pct = 0.30`（非 top-k 模式的单仓上限）
- `hard_stop = -0.08`（-8%硬止损，生产按日线收盘确认）
- `funding_short_threshold = 0.001`（资金费率>0.1%做空）

部署状态见 [交接文档](memory-bank/README.md)，节点同步边界与异常恢复见 [部署说明](docs/live-node-deployment.md)。
