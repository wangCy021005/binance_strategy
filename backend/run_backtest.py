"""
币安量化策略回测入口（调用完整引擎）
用法：python backend/run_backtest.py [--start 2022-01-01] [--end 2025-12-31]
"""
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import CFG
from backtest.engine import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=CFG.start)
    parser.add_argument("--end",   default=CFG.end)
    args = parser.parse_args()

    cfg = CFG.__class__(**{**CFG.__dict__, "start": args.start, "end": args.end})
    run(cfg)
