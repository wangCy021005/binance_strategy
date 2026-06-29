"""
Regime Agent — 加密市场状态识别
知识库第12课：状态识别先于策略选择

币安四态（不用ADX，用BTC市场结构）：
  bull    = BTC 20日涨幅 > 5%，波动率适中 → 动量策略
  ranging = BTC 20日涨跌幅绝对值 < 5% → 资金费率套利
  bear    = BTC 20日跌幅 > 10% → 谨慎，可小仓做空
  crisis  = 波动率极高（>80%年化）→ 全防御

与A股不同：动量在加密市场IC为正，趋势跟随有效。
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class RegimeState:
    regime:       str    # bull | ranging | bear | crisis
    btc_ret_20d:  float  # BTC 20日收益率
    vol_20d:      float  # 20日年化波动率
    mom_weight:   float
    funding_weight: float
    mr_weight:    float
    def_weight:   float
    max_slots:    int
    position_cap: float


class RegimeAgent:
    def __init__(self, cfg):
        self.cfg = cfg
        self._window: deque = deque(maxlen=cfg.regime_confirm_days)
        self._current = "ranging"

    def detect(self, btc_df: pd.DataFrame, timestamp: str) -> RegimeState:
        raw       = self._raw_detect(btc_df, timestamp)
        confirmed = self._confirm(raw)
        return self._build_state(btc_df, timestamp, confirmed)

    def _raw_detect(self, btc_df: pd.DataFrame, timestamp: str) -> str:
        if btc_df is None or btc_df.empty or timestamp not in btc_df.index:
            return "ranging"

        pos  = btc_df.index.tolist().index(timestamp)
        hist = btc_df["close"].iloc[:pos + 1].astype(float)

        if len(hist) < 21:
            return "ranging"

        ret_20d = float((hist.iloc[-1] - hist.iloc[-21]) / hist.iloc[-21])
        rets    = hist.pct_change().dropna().iloc[-20:]
        vol_20d = float(rets.std() * np.sqrt(365 * 6))  # 4h K线，每天6根

        cfg = self.cfg

        # 危机判断（波动率极高）
        if vol_20d > cfg.vol_crisis:
            return "crisis"

        # 牛市（BTC 20日涨幅 > 5%）
        if ret_20d > cfg.bull_threshold:
            return "bull"

        # 熊市（BTC 20日跌幅 > 10%）
        if ret_20d < cfg.bear_threshold:
            return "bear"

        return "ranging"

    def _confirm(self, raw: str) -> str:
        if raw == "crisis":
            self._window.clear()
            self._current = "crisis"
            return "crisis"
        self._window.append(raw)
        if len(self._window) < self.cfg.regime_confirm_days:
            return self._current
        counts = {}
        for s in self._window:
            counts[s] = counts.get(s, 0) + 1
        majority = max(counts, key=counts.__getitem__)
        if counts[majority] > self.cfg.regime_confirm_days // 2:
            self._current = majority
        return self._current

    def _build_state(self, btc_df: pd.DataFrame, timestamp: str,
                     regime: str) -> RegimeState:
        if btc_df is not None and not btc_df.empty and timestamp in btc_df.index:
            pos  = btc_df.index.tolist().index(timestamp)
            hist = btc_df["close"].iloc[:pos + 1].astype(float)
            ret_20d = float((hist.iloc[-1] - hist.iloc[-21]) / hist.iloc[-21]) if len(hist) >= 22 else 0.0
            rets    = hist.pct_change().dropna().iloc[-20:]
            vol_20d = float(rets.std() * np.sqrt(365 * 6)) if len(rets) >= 10 else 0.0
        else:
            ret_20d = 0.0
            vol_20d = 0.0

        if regime not in self.cfg.regime_weights:
            raise KeyError(f"regime_weights 中缺少状态 '{regime}'")
        mw, fw, rw, dw, slots, cap = self.cfg.regime_weights[regime]

        return RegimeState(
            regime=regime, btc_ret_20d=ret_20d, vol_20d=vol_20d,
            mom_weight=mw, funding_weight=fw, mr_weight=rw, def_weight=dw,
            max_slots=slots, position_cap=cap,
        )
