"""
加密货币趋势动量策略
知识库第05课：趋势跟随（胜率30-45%，盈亏比3:1）

关键差异（A股教训）：
  A股动量IC = -0.02（短期反转，追涨有害）
  加密动量IC = +0.04~0.08（中期趋势有效，做对做大）

因此加密中：
  - 可以追涨（A股教训：不要追涨 → 加密相反）
  - 重要：强调"中期"动量（20-60根4h K线 = 3-10天），而非短期
  - 配合资金费率过滤（资金费率极高时不追多，反向机会大）
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

from core.indicators import calc_atr, calc_rsi, calc_momentum, calc_volume_ratio


@dataclass
class MomSignal:
    symbol:    str
    score:     float    # 综合得分 0~1
    direction: int      # +1 做多，-1 做空
    momentum:  float    # 实际动量值
    atr_pct:   float    # ATR / 价格，用于仓位计算
    vol_ratio: float    # 量比


def score_symbol(symbol: str,
                 df: Optional[pd.DataFrame],
                 funding: Optional[pd.Series],
                 cfg,
                 as_of_ts: str) -> Optional[MomSignal]:
    """
    对单个加密品种评分。
    返回做多/做空信号或 None。
    """
    if df is None or df.empty:
        return None

    hist = df[df.index <= as_of_ts].copy()
    if len(hist) < 260:
        return None

    close = hist["close"].astype(float)

    # ── 计算动量（20根4h K线 ≈ 3.3天）──────────────────────────────────────
    mom_short = float(close.pct_change(42).iloc[-1])    # 短期（7天 = 42根4h）
    mom_mid   = float(close.pct_change(126).iloc[-1])   # 中期（21天 = 126根4h）
    mom_long  = float(close.pct_change(252).iloc[-1])   # 长期（42天 = 252根4h）

    # 趋势一致性（短中长同向得加分）
    direction = 1 if mom_mid > 0 else -1
    consistency = sum([
        1 if mom_short * direction > 0 else 0,
        1 if mom_mid   * direction > 0 else 0,
        1 if mom_long  * direction > 0 else 0,
    ]) / 3

    if consistency < 0.67:     # 三个时间周期至少两个同向
        return None

    # ── 量比过滤（成交量确认）─────────────────────────────────────────────
    vol_ratio = 1.0
    if "volume" in hist.columns and len(hist) >= 21:
        vol  = hist["volume"].astype(float)
        avg5 = float(vol.iloc[-6:-1].mean())
        if avg5 > 0:
            vol_ratio = float(vol.iloc[-1]) / avg5
    if vol_ratio < 0.3:        # 极度缩量，不追
        return None

    # ── RSI 过滤（极端区域不追）──────────────────────────────────────────
    rsi = calc_rsi(hist).iloc[-1]
    if direction > 0 and rsi > 85:   # 做多时RSI不能极度超买
        return None
    if direction < 0 and rsi < 15:   # 做空时RSI不能极度超卖
        return None

    # ── 资金费率过滤（防止与资金费率逆向）────────────────────────────────
    if funding is not None and not funding.empty:
        recent_fr = funding[funding.index <= as_of_ts]
        if not recent_fr.empty:
            current_fr = float(recent_fr.iloc[-1])
            # 资金费率极高时（>0.1%），多头成本高，方向风险大
            if direction > 0 and current_fr > 0.001:
                return None
            # 资金费率极负时（<-0.05%），空头成本高
            if direction < 0 and current_fr < -0.0005:
                return None

    # ── ATR（用于仓位计算）──────────────────────────────────────────────
    atr_pct = 0.03
    atr_series = calc_atr(hist)
    if not atr_series.empty and not np.isnan(atr_series.iloc[-1]):
        latest = float(close.iloc[-1])
        if latest > 0:
            atr_pct = float(atr_series.iloc[-1]) / latest

    # ── 综合评分 ─────────────────────────────────────────────────────────
    mom_strength = min(abs(mom_mid) / 0.10, 1.0)    # 10%动量=满分
    vol_score    = min(vol_ratio / 2.0, 1.0)
    score        = 0.60 * mom_strength + 0.20 * consistency + 0.20 * vol_score

    return MomSignal(
        symbol    = symbol,
        score     = round(score, 3),
        direction = direction,
        momentum  = mom_mid,
        atr_pct   = atr_pct,
        vol_ratio = vol_ratio,
    )


def get_alpha_boosted_score(base_score: float, alpha_score: float,
                             alpha_weight: float = 0.30) -> float:
    """
    用 AlphaGPT 因子增强原始动量得分。
    alpha_weight=0.30: 原始动量70% + Alpha因子30%
    """
    return (1 - alpha_weight) * base_score + alpha_weight * alpha_score


def get_signals(symbols: list[str],
                all_ohlcv: dict[str, pd.DataFrame],
                all_funding: dict[str, pd.Series],
                cfg,
                as_of_ts: str,
                weight: float = 1.0) -> list[dict]:
    """
    批量生成动量信号，叠加 AlphaGPT 发现的 Alpha 因子。
    Alpha 因子 = 放量大波动（ICIR=3.53，2022-2024验证）
    """
    if weight <= 0:
        return []

    # 预计算所有品种的 Alpha 因子得分（截面归一化）
    from core.alpha_factor import rank_alpha_scores
    alpha_weight = getattr(cfg, 'alpha_factor_weight', 0.30)
    alpha_scores = {}
    if alpha_weight > 0:
        alpha_scores = rank_alpha_scores(symbols, all_ohlcv, as_of_ts)

    signals = []
    for symbol in symbols:
        df      = all_ohlcv.get(symbol)
        funding = all_funding.get(symbol)
        sig     = score_symbol(symbol, df, funding, cfg, as_of_ts)
        if sig is not None:
            # 叠加 Alpha 因子
            alpha_s   = alpha_scores.get(symbol, 0.0)
            base_score = sig.score
            if alpha_weight > 0 and alpha_s > 0:
                final_score = get_alpha_boosted_score(base_score, alpha_s, alpha_weight)
            else:
                final_score = base_score

            signals.append({
                "symbol":       sig.symbol,
                "score":        final_score * weight,
                "direction":    sig.direction,
                "atr_pct":      sig.atr_pct,
                "strategy":     "momentum",
                "momentum":     sig.momentum,
                "vol_ratio":    sig.vol_ratio,
                "alpha_score":  round(alpha_s, 3),
            })

    signals.sort(key=lambda x: -x["score"])
    return signals[:cfg.mom_top_n]
