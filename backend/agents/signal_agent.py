"""
Signal Agent — 信号路由（加密版）
根据 Regime 状态把权重分配给不同策略
"""
from __future__ import annotations
from typing import Optional, Callable
import logging

from agents.regime_agent import RegimeState
from strategies import momentum, funding_arb

logger = logging.getLogger("crypto.signal")


class SignalAgent:
    def __init__(self, cfg, alpha_scorer: Optional[Callable] = None):
        """
        alpha_scorer: AlphaGPT 公式评分函数（可选）
        """
        self.cfg          = cfg
        self.alpha_scorer = alpha_scorer

    def generate(self,
                 symbols:      list[str],
                 all_ohlcv:    dict,
                 all_funding:  dict,
                 as_of_ts:     str,
                 regime:       RegimeState) -> list[dict]:
        """
        生成候选信号列表，按综合得分排序。
        每个信号包含：symbol, direction(+1/-1), score, strategy, atr_pct
        """
        if regime.max_slots == 0:
            return []

        candidates: list[dict] = []

        # ── 动量信号 ─────────────────────────────────────────────────────
        if regime.mom_weight > 0:
            mom_sigs = momentum.get_signals(
                symbols, all_ohlcv, all_funding, self.cfg,
                as_of_ts, regime.mom_weight
            )
            candidates.extend(mom_sigs)

        # ── 资金费率套利信号 ──────────────────────────────────────────────
        if regime.funding_weight > 0 and self.cfg.spot_or_futures == "futures":
            fr_sigs = funding_arb.get_signals(
                symbols, all_ohlcv, all_funding, self.cfg,
                as_of_ts, regime.funding_weight
            )
            candidates.extend(fr_sigs)

        # ── 合并：同一品种取得分更高的信号 ──────────────────────────────
        combined: dict[str, dict] = {}
        for sig in candidates:
            sym = sig["symbol"]
            if sym not in combined or sig["score"] > combined[sym]["score"]:
                combined[sym] = sig

        # ── AlphaGPT 二次评分（可选）──────────────────────────────────
        result = list(combined.values())
        if self.alpha_scorer and result:
            try:
                result = self.alpha_scorer(result)
            except Exception as e:
                logger.warning("AlphaGPT 评分失败: %s", e)

        result.sort(key=lambda x: -x["score"])

        if result:
            logger.debug("候选信号 %d 个 | Regime=%s | top3=%s",
                         len(result), regime.regime,
                         [f"{s['symbol']}({s['direction']:+d})" for s in result[:3]])

        return result
