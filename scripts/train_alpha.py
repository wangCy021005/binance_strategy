"""
AlphaGPT 加密版训练入口
用法：python scripts/train_alpha.py --steps 2000 --early-stop 500

前置：先获取数据
  python scripts/fetch_data.py --all --start 2022-01-01
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from config import CFG
from model_core.engine import CryptoAlphaEngine


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start",      default="2022-01-01")
    p.add_argument("--end",        default="2024-12-31")
    p.add_argument("--steps",      type=int, default=2000)
    p.add_argument("--early-stop", type=int, default=500)
    p.add_argument("--timeframe",  default=CFG.timeframe)
    args = p.parse_args()

    print(f"训练配置: {args.start}~{args.end}  steps={args.steps}")
    print(f"特征集: {' / '.join(['RET','MOM20','PRESSURE','VOL_RATIO','HL_RANGE','FUNDING','RSI','VOL_TREND'])}")
    print(f"品种: {CFG.symbols}")

    engine = CryptoAlphaEngine(
        symbols   = CFG.symbols,
        timeframe = args.timeframe,
        start     = args.start,
        end       = args.end,
        train_steps = args.steps,
    )
    engine.train(early_stop_steps=args.early_stop)


if __name__ == "__main__":
    main()
