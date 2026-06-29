#!/bin/bash
# 一键初始化币安量化策略环境

set -e

echo "=== 币安量化策略初始化 ==="
cd "$(dirname "$0")/.."

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -q ccxt pandas numpy torch ta tqdm python-dateutil

echo ""
echo "✅ 环境初始化完成"
echo ""
echo "下一步："
echo "  1. source .venv/bin/activate"
echo "  2. python scripts/fetch_data.py --all --start 2022-01-01"
echo "  3. python backend/run_backtest.py"
