"""
单变量快速对比测试
  A：移除 BTC/USDT 交易（保留 Regime 检测）
  B：追踪止损 0.12 → 0.16
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import copy
import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from config import CFG
from backtest.engine import run

def backtest_with(label, **overrides):
    cfg = copy.deepcopy(CFG)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    run(cfg)

# 基准（复现确认）
backtest_with("基准（Sharpe=0.613）")

# Test A：BTC 不参与交易（只用于 Regime 检测）
no_btc_symbols = [s for s in CFG.symbols if s != "BTC/USDT"]
backtest_with(
    "Test A: 移除 BTC/USDT 交易（保留 Regime 检测）",
    symbols=no_btc_symbols
)

# Test B：追踪止损拓宽 0.12 → 0.16
backtest_with(
    "Test B: 追踪止损 0.12 → 0.16",
    trailing_stop_pct=0.16
)

# Test C：A+B 组合
backtest_with(
    "Test C: BTC移除 + 止损0.16",
    symbols=no_btc_symbols,
    trailing_stop_pct=0.16
)
