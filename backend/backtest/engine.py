"""
回测引擎 — 加密版
知识库第21课：DataManager→RegimeAgent→SignalAgent→RiskAgent→Portfolio
"""
from __future__ import annotations
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

from config import CFG, DASH_DIR
from core.data_feed import CryptoDataFeed
from core.portfolio import Portfolio
from core.indicators import calc_atr
from agents.regime_agent import RegimeAgent
from agents.risk_agent import RiskAgent, RiskLevel
from agents.signal_agent import SignalAgent
from backtest.report import write_report, print_summary

logger = logging.getLogger("crypto.engine")


def run(cfg=None, alpha_scorer=None):
    if cfg is None:
        cfg = CFG

    # ── 初始化 ──────────────────────────────────────────────────────────────
    feed    = CryptoDataFeed()
    regime  = RegimeAgent(cfg)
    risk    = RiskAgent(cfg)
    signals = SignalAgent(cfg, alpha_scorer=alpha_scorer)
    port    = Portfolio(cfg.cash)

    # ── 数据加载 ─────────────────────────────────────────────────────────────
    logger.info("加载数据 %s ~ %s  品种=%d  周期=%s",
                cfg.start, cfg.end, len(cfg.symbols), cfg.timeframe)

    all_ohlcv   = feed.get_all_ohlcv(cfg.symbols, cfg.timeframe, cfg.start, cfg.end)
    all_funding = feed.get_all_funding(cfg.symbols, cfg.start, cfg.end) \
                  if cfg.spot_or_futures == "futures" else {}
    btc_df      = feed.get_btc_ohlcv(cfg.timeframe, cfg.start, cfg.end)
    timestamps  = feed.get_trade_timestamps(cfg.timeframe, cfg.start, cfg.end)

    active = [s for s, df in all_ohlcv.items() if not df.empty]
    logger.info("有效品种 %d/%d  时间点 %d", len(active), len(cfg.symbols), len(timestamps))

    if not timestamps:
        logger.error("无数据！请先运行 scripts/fetch_data.py --all --start %s", cfg.start)
        return

    # ── 主循环 ────────────────────────────────────────────────────────────────
    equity_curve = []
    regime_log   = []

    for i, ts in enumerate(timestamps, 1):
        now = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

        # 当前价格（收盘价）
        prices = {}
        for sym, df in all_ohlcv.items():
            if not df.empty and ts in df.index:
                prices[sym] = float(df.loc[ts, "close"])

        # Step 1: 执行挂起止损（上一根K线触发，当前K线开盘执行）
        port.flush_stops(prices, ts)

        # Step 2: 更新持仓状态
        port.tick(prices, ts)

        # Step 3: 止损检查
        port.check_stops(prices, ts, cfg)

        # Step 4: 资金费率结算（每8小时）
        # 资金费率 = 持仓市值 × 资金费率，从盈亏中扣除
        # (简化：在 portfolio 中隐式处理，此处记录)

        # Step 5: 风控等级
        pv    = port.value(prices)
        level = risk.get_level(pv)

        if level == RiskLevel.CIRCUIT:
            risk.trigger_circuit(now)
            # 熔断：强制平掉所有仓位
            for sym in list(port.positions.keys()):
                port._pending_stop[sym] = "熔断强平"

        # Step 6: Regime 识别
        rs = regime.detect(btc_df, ts)
        regime_log.append({"time": ts, "regime": rs.regime})

        # Step 7: 开仓决策
        in_hard_block = (level == RiskLevel.CIRCUIT and risk.in_cooldown(now))
        can_open      = not in_hard_block and rs.max_slots > 0

        if can_open:
            candidates = signals.generate(
                active, all_ohlcv, all_funding, ts, rs
            )

            free_slots = rs.max_slots - len(port.positions)
            total_val  = port.value(prices)

            for sig in candidates:
                if free_slots <= 0:
                    break

                sym = sig["symbol"]
                if sym in port.positions:
                    continue

                # 检查总仓位上限
                mv = sum(
                    pos.qty * prices.get(s, pos.cost)
                    for s, pos in port.positions.items()
                )
                if total_val > 0 and (mv / total_val) >= rs.position_cap - 0.01:
                    break

                # ATR 定仓（知识库第15课）
                atr_pct = sig.get("atr_pct", 0.03)
                size_pct = min(
                    cfg.risk_per_trade / max(atr_pct, 0.005),
                    cfg.max_pos_pct
                )

                # 风控审核
                decision = risk.check_order(size_pct, total_val, level, now)
                if not decision.approve:
                    continue

                price = prices.get(sym, 0)
                if price <= 0:
                    continue

                # 滑点（加密现货流动性好，滑点小）
                buy_price = price * (1 + cfg.slippage_pct) \
                            if sig["direction"] > 0 else price * (1 - cfg.slippage_pct)

                port.open_position(
                    sym, "long" if sig["direction"] > 0 else "short",
                    buy_price, decision.size, total_val, ts, sig["strategy"],
                    atr_pct=atr_pct,
                )
                free_slots -= 1

        # Step 8: 记录净值
        pv = port.value(prices)
        equity_curve.append({"time": ts, "value": pv, "nav": pv / cfg.cash})

        # 进度日志
        if i % 500 == 0 or i == len(timestamps):
            ret = (pv - cfg.cash) / cfg.cash * 100
            logger.info("[%d/%d] %s  资产=%.0f USDT  收益=%.1f%%  Regime=%s",
                        i, len(timestamps), ts[:10], pv, ret, rs.regime)

    # ── 输出报告 ──────────────────────────────────────────────────────────────
    write_report(equity_curve, port.trades, regime_log, cfg)
    print_summary(equity_curve, port.trades, regime_log, cfg)

    return equity_curve
