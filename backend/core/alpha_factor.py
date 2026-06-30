"""
AlphaGPT 发现的 Alpha 因子 v1
公式：HL_RANGE GATE MAX3 MIN3 MIN3 MIN3 MIN3 ABS VOL_RATIO GATE MUL MAX3
ICIR = 3.53（极显著，训练数据 2022-2024）

经济含义：放量大波动因子
  - HL_RANGE（振幅）：(high-low)/close，衡量单根K线的波动强度
  - VOL_RATIO（量比）：today_vol / 20日均量，衡量资金涌入程度
  - 核心逻辑：振幅大 + 量比高 → 真实行情，不是噪音波动

ICIR > 3 说明：
  因子值越高的币种，未来20日收益率越高（统计显著）
  在2022-2024年加密市场上，这个信号跑赢随机选股3倍以上

使用方法：
  对每个候选币计算 alpha_score，
  在 momentum.py 的评分中加权混合
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_alpha_score(df: pd.DataFrame, as_of_ts: str,
                        clip_max: float = 5.0,
                        window: int = 20) -> float:
    """
    计算单个品种的 AlphaGPT 因子得分（越高越好）

    Parameters
    ----------
    df       : OHLCV DataFrame，index=open_time
    as_of_ts : 当前时间点（严格不使用未来数据）
    clip_max : MAX3/MIN3 等价的截断值（防极值）
    window   : 历史参考窗口（计算相对量比/振幅）

    Returns
    -------
    float: 0 到 clip_max 之间的得分，越大越强
    """
    if df is None or df.empty:
        return 0.0

    hist = df[df.index <= as_of_ts].tail(window + 5)
    if len(hist) < window:
        return 0.0

    close  = hist["close"].astype(float)
    high   = hist["high"].astype(float)
    low    = hist["low"].astype(float)
    volume = hist["volume"].astype(float)

    # ── HL_RANGE：振幅 = (high - low) / close ────────────────────────────
    hl_range = (high - low) / (close + 1e-9)

    # ── VOL_RATIO：今日量 / N日均量 ────────────────────────────────────────
    vol_ma   = volume.rolling(window).mean()
    vol_ratio = volume / (vol_ma + 1e-9)

    # 当前值
    cur_hl = float(hl_range.iloc[-1])
    cur_vr = float(vol_ratio.iloc[-1])

    # ── 门控归一化（对应公式中的 GATE + MIN3 层）────────────────────────────
    # 用历史中位数作为基准（比均值更稳健）
    hl_med = float(hl_range.iloc[-window:].median())
    vr_med = float(vol_ratio.iloc[-window:].median())

    # 相对历史基准的倍数，截断到 [0, clip_max]
    hl_norm = float(np.clip(cur_hl / (hl_med + 1e-9), 0.0, clip_max))
    vr_norm = float(np.clip(cur_vr / (vr_med + 1e-9), 0.0, clip_max))

    # ── 核心：振幅 × 量比（对应 MUL，最终再 MAX3 裁剪）────────────────────
    score = hl_norm * vr_norm
    score = float(np.clip(score, 0.0, clip_max ** 2))   # 最大 25

    return score


def rank_alpha_scores(symbols: list[str],
                      all_ohlcv: dict,
                      as_of_ts: str,
                      top_n: int = None) -> dict[str, float]:
    """
    批量计算所有品种的 Alpha 因子，返回 {symbol: normalized_score(0~1)}

    截面归一化：最高分 = 1.0，用于和原始动量得分混合
    """
    raw_scores = {}
    for sym in symbols:
        df = all_ohlcv.get(sym)
        raw_scores[sym] = compute_alpha_score(df, as_of_ts)

    if not raw_scores:
        return {}

    # fix-P2: 用95分位数归一化（防止极端值污染截面）
    scores_list = sorted(raw_scores.values())
    p95_idx = max(0, int(len(scores_list) * 0.95) - 1)
    p95_val = scores_list[p95_idx] if scores_list else 1.0
    max_score = max(p95_val, 1e-6)
    normalized = {sym: min(s / max_score, 1.0) for sym, s in raw_scores.items()}

    if top_n:
        top_syms = sorted(normalized, key=lambda x: -normalized[x])[:top_n]
        return {sym: normalized[sym] for sym in top_syms}

    return normalized
