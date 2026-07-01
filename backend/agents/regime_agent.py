"""
Regime Agent — 加密市场状态识别
知识库第12课：状态识别先于策略选择

币安四态（不用ADX，用BTC市场结构）：
  bull    = BTC 20日涨幅 > 5%，波动率适中 → 动量策略
  ranging = BTC 20日涨跌幅绝对值 < 5% → 资金费率套利
  bear    = BTC 20日跌幅 > 10% → 谨慎，可小仓做空
  crisis  = 波动率极高（>80%年化）→ 全防御

注意（4h K线）：
  - 20日 = 120根4h K线（20天 × 24h/天 ÷ 4h/根 = 120根）
  - 年化波动率 = 日收益率标准差 × sqrt(2190)  （2190根/年）
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import numpy as np
import pandas as pd

# 4h K线参数
_TF_PARAMS = {
    '1d': (1, 365, 20),      # (bars_per_day, bars_per_year, 20d_bars)
    '4h': (6, 2190, 120),    # 4h: 6bars/day
    '1h': (24, 8760, 480),   # 1h: 24bars/day
}
_PERIODS_PER_DAY  = 1      # default: 1d
_PERIODS_PER_YEAR = 365    # default: 1d
_20D_PERIODS      = 20     # default: 1d


@dataclass
class RegimeState:
    regime:         str
    btc_ret_20d:    float
    vol_20d:        float
    mom_weight:     float
    funding_weight: float
    mr_weight:      float
    def_weight:     float
    max_slots:      int
    position_cap:   float
    leverage:       float = 1.0   # 该状态下的杠杆倍数


class RegimeAgent:
    def __init__(self, cfg):
        self.cfg = cfg
        self._window: deque = deque(maxlen=cfg.regime_confirm_days)
        self._current = "ranging"
        # 根据 timeframe 设置年化系数（修复：日线不能用4h系数）
        tf = getattr(cfg, 'timeframe', '4h')
        params = _TF_PARAMS.get(tf, _TF_PARAMS['4h'])
        self._bars_per_year = params[1]
        self._20d_bars      = params[2]

    def detect(self, btc_df: pd.DataFrame, timestamp: str) -> RegimeState:
        raw       = self._raw_detect(btc_df, timestamp)
        confirmed = self._confirm(raw)
        return self._build_state(btc_df, timestamp, confirmed)

    def _raw_detect(self, btc_df: pd.DataFrame, timestamp: str) -> str:
        if btc_df is None or btc_df.empty or timestamp not in btc_df.index:
            return "ranging"

        pos  = btc_df.index.get_loc(timestamp)   # O(1) hash lookup，原来 O(N) 列表搜索
        hist = btc_df["close"].iloc[:pos + 1].astype(float)

        if len(hist) < 30:
            return "ranging"

        # 20日收益率（120根4h K线）
        lookback = min(self._20d_bars, len(hist) - 1)
        ret_20d  = float((hist.iloc[-1] - hist.iloc[-lookback-1]) / hist.iloc[-lookback-1])

        # 20日年化波动率
        rets    = hist.pct_change().dropna().iloc[-self._20d_bars:]
        vol_20d = float(rets.std() * np.sqrt(self._bars_per_year)) if len(rets) >= 10 else 0.15

        cfg = self.cfg

        # 危机判断（年化波动率过高）
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
            pos  = btc_df.index.get_loc(timestamp)   # O(1) hash lookup
            hist = btc_df["close"].iloc[:pos + 1].astype(float)

            lookback = min(self._20d_bars, len(hist) - 1)
            ret_20d  = float((hist.iloc[-1] - hist.iloc[-lookback-1]) / hist.iloc[-lookback-1]) \
                       if len(hist) > 1 else 0.0

            rets    = hist.pct_change().dropna().iloc[-self._20d_bars:]
            vol_20d = float(rets.std() * np.sqrt(self._bars_per_year)) if len(rets) >= 10 else 0.0
        else:
            ret_20d = 0.0
            vol_20d = 0.0

        if regime not in self.cfg.regime_weights:
            raise KeyError(f"regime_weights 中缺少状态 '{regime}'")
        entry = self.cfg.regime_weights[regime]
        mw, fw, rw, dw, slots, cap = entry[:6]
        lev = float(entry[6]) if len(entry) > 6 else 1.0
        lev = min(lev, getattr(self.cfg, 'max_leverage', 10.0))

        return RegimeState(
            regime=regime, btc_ret_20d=ret_20d, vol_20d=vol_20d,
            mom_weight=mw, funding_weight=fw, mr_weight=rw, def_weight=dw,
            max_slots=slots, position_cap=cap, leverage=lev,
        )
