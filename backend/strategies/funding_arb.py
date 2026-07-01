"""
资金费率套利策略 — 加密特有 Alpha 源
知识库无此内容（A股没有资金费率机制）

资金费率（Funding Rate）机制：
  每8小时结算一次，多头/空头互付利息
  率 > 0：多头付费给空头（看空信号）
  率 < 0：空头付费给多头（看多信号）

策略逻辑：
  1. 资金费率持续正（多头拥挤） → 开空，收取费率 + 等待回调
  2. 资金费率持续负（空头拥挤） → 开多，收取费率 + 等待反弹
  3. 纯套利：资金费率极高时，现货对冲合约（delta neutral）

这是A股完全没有的 Alpha 源，也是加密量化中最稳定的收益来源之一。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class FundingSignal:
    symbol:        str
    score:         float
    direction:     int     # +1=做多（空头拥挤，收取负费率），-1=做空（多头拥挤，收取正费率）
    funding_rate:  float   # 当前资金费率
    avg_rate_3d:   float   # 近3天平均资金费率
    atr_pct:       float


def score_funding(symbol: str,
                  df: Optional[pd.DataFrame],
                  funding: Optional[pd.Series],
                  cfg,
                  as_of_ts: str) -> Optional[FundingSignal]:
    """
    资金费率套利信号评分。
    只在资金费率显著偏离时开仓。
    """
    if funding is None or funding.empty:
        return None
    if df is None or df.empty:
        return None

    # 获取当前及近期资金费率
    recent_fr = funding[funding.index <= as_of_ts]
    if len(recent_fr) < 3:
        return None

    current_fr = float(recent_fr.iloc[-1])
    # 每个资金费率周期8小时，3天=9个周期
    avg_fr_3d  = float(recent_fr.iloc[-9:].mean()) if len(recent_fr) >= 9 else float(recent_fr.mean())

    # ── 触发条件 ───────────────────────────────────────────────────────────
    long_threshold  = cfg.funding_long_threshold   # < -0.05%
    short_threshold = cfg.funding_short_threshold  # > +0.10%

    if current_fr >= short_threshold and avg_fr_3d >= short_threshold * 0.5:
        # 做空：多头持续拥挤，收取资金费率
        direction = -1
        fee_score = min(current_fr / (short_threshold * 3), 1.0)
    elif current_fr <= long_threshold and avg_fr_3d <= long_threshold * 0.5:
        # 做多：空头持续拥挤，收取负资金费率
        direction = +1
        fee_score = min(abs(current_fr) / (abs(long_threshold) * 3), 1.0)
    else:
        return None   # 资金费率不够极端，不开仓

    # ── ATR ────────────────────────────────────────────────────────────────
    hist = df[df.index <= as_of_ts]
    atr_pct = 0.03
    if len(hist) >= 14:
        from core.indicators import calc_atr
        atr_series = calc_atr(hist)
        if not atr_series.empty:
            latest = float(hist["close"].iloc[-1])
            if latest > 0:
                atr_pct = float(atr_series.iloc[-1]) / latest

    return FundingSignal(
        symbol       = symbol,
        score        = round(fee_score, 3),
        direction    = direction,
        funding_rate = current_fr,
        avg_rate_3d  = avg_fr_3d,
        atr_pct      = atr_pct,
    )


def get_signals(symbols: list[str],
                all_ohlcv: dict,
                all_funding: dict,
                cfg,
                as_of_ts: str,
                weight: float = 1.0) -> list[dict]:
    """资金费率套利信号批量生成"""
    if weight <= 0:
        return []

    signals = []
    for symbol in symbols:
        sig = score_funding(symbol, all_ohlcv.get(symbol),
                            all_funding.get(symbol), cfg, as_of_ts)
        if sig is not None:
            signals.append({
                "symbol":       sig.symbol,
                "score":        sig.score * weight,
                "direction":    sig.direction,
                "atr_pct":      sig.atr_pct,
                "strategy":     "funding_arb",
                "funding_rate": sig.funding_rate,
                "avg_rate_3d":  sig.avg_rate_3d,
            })

    signals.sort(key=lambda x: -x["score"])
    return signals
