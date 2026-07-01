"""
第三轮单变量测试（基于 Sharpe=0.630 基准，已移除BTC交易）
  D2: fix-002 修正版 — 动量窗口 42/126/252 → 21/63/126（全部缩短一半）
  E2: fix-004 — Regime 确认天数 2 → 4 天
  F2: fix-007 — Bull 过热（BTC 20日涨幅>25%）自动降仓
  G2: fix-008 — Alpha 因子几何平均（修复右偏）
"""
import sys, copy, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from config import CFG
from backtest.engine import run

def bt(label, **overrides):
    cfg = copy.deepcopy(CFG)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    run(cfg)

# 对照（当前基准：无BTC，Sharpe=0.630）
bt("基准（Sharpe=0.630，无BTC）")

# D2: 动量窗口缩短一半（fix-002 修正版）
# 逻辑：加密动量半衰期2-4周，42天等于6周已经是"中期"
# 21/63/126 比例不变（1:3:6），但整体更贴近加密市场节奏
bt("Test D2: 动量窗口 42/126/252 → 21/63/126",
   mom_short_bars=21,
   mom_mid_bars=63,
   mom_long_bars=126)

# E2: Regime 确认天数 2 → 4 天（减少边界震荡）
bt("Test E2: Regime 确认 2 → 4 天",
   regime_confirm_days=4)

# F2: Bull 过热降仓（在 config 层面配置，engine 需感知）
# 简化方案：在 ranging 状态也保留，通过 bull_threshold 调低触发更保守的 bull
# 实际：提高牛市进入门槛 5%→8%，只有更确定的牛市才满仓
bt("Test F2: 牛市门槛 5%→8%（更保守的 Bull 判断）",
   bull_threshold=0.08)

# G2: Alpha 几何平均（改 alpha_factor.py，临时patch）
import numpy as np
import backend.core.alpha_factor as af_mod
_original_compute = af_mod.compute_alpha_score

def _geo_compute(df_slice, as_of_ts):
    """几何平均版本，修复分布右偏"""
    score = _original_compute(df_slice, as_of_ts)
    # 原公式：score = hl_norm * vr_norm（最大25，右偏严重）
    # 改为：sqrt(score)，压缩到[0,5]，分布更均匀
    return float(np.sqrt(max(0, score)))

af_mod.compute_alpha_score = _geo_compute

bt("Test G2: Alpha 因子几何平均（sqrt，修复右偏）")

# 恢复
af_mod.compute_alpha_score = _original_compute
