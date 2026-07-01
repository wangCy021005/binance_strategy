"""
第四轮测试（基于 F2 后的新基准 Sharpe≈0.675）
  H: fix-008 Alpha 因子几何平均（修复右偏）
  I: F2 确认回测（bull_threshold=0.08 的稳定性验证）
  J: 组合优化 — Regime 边界添加滞后带（bear 由 -10% 收窄到 -12%）
"""
import sys, copy, logging, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from config import CFG  # bull_threshold=0.08 已写入
from backtest.engine import run
import core.alpha_factor as af_mod   # 正确 import 路径

def bt(label, alpha_patch=False, **overrides):
    cfg = copy.deepcopy(CFG)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    if alpha_patch:
        _orig = af_mod.compute_alpha_score
        def _geo(df, ts, **kw):
            score = _orig(df, ts, **kw)
            return float(np.sqrt(max(0, score)))
        af_mod.compute_alpha_score = _geo
        run(cfg)
        af_mod.compute_alpha_score = _orig
    else:
        run(cfg)

# I: 当前基准验证（bull_threshold=0.08）
bt("I（基准验证）: bull_threshold=0.08  预期 Sharpe≈0.675")

# H: Alpha 因子几何平均
bt("H: Alpha 因子几何平均（sqrt，修复右偏）", alpha_patch=True)

# J: bear 阈值由 -10% 收窄到 -12%（避免边界熊市误判）
bt("J: bear 阈值 -10% → -12%（牛/震荡边界收窄）",
   bear_threshold=-0.12)

# K: bull 8% + bear -12%（J和F2组合）
bt("K: 组合 bull_threshold=0.08 + bear_threshold=-0.12",
   bear_threshold=-0.12)
