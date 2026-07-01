"""
年度收益分析 + 熊市专项分析
"""
import sys, json, numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from config import CFG
from core.data_feed import CryptoDataFeed
from agents.regime_agent import RegimeAgent
from agents.risk_agent import RiskAgent
from agents.signal_agent import SignalAgent
from core.portfolio import Portfolio
from core.indicators import calc_atr

import logging
logging.basicConfig(level=logging.WARNING)


def run_with_yearly(cfg=None):
    if cfg is None:
        cfg = CFG

    feed    = CryptoDataFeed()
    regime  = RegimeAgent(cfg)
    risk    = RiskAgent(cfg)
    signals = SignalAgent(cfg)
    port    = Portfolio(cfg.cash)

    all_ohlcv   = feed.get_all_ohlcv(cfg.symbols, cfg.timeframe, cfg.start, cfg.end)
    all_funding = feed.get_all_funding(cfg.symbols, cfg.start, cfg.end)
    btc_df      = feed.get_btc_ohlcv(cfg.timeframe, cfg.start, cfg.end)
    timestamps  = feed.get_trade_timestamps(cfg.timeframe, cfg.start, cfg.end)
    active      = [s for s, df in all_ohlcv.items() if not df.empty]

    # 按年统计
    yearly_nav   = defaultdict(list)
    yearly_reg   = defaultdict(lambda: defaultdict(int))
    equity_curve = []
    regime_log   = []

    for i, ts in enumerate(timestamps, 1):
        now  = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        year = ts[:4]

        prices = {}
        for sym, df in all_ohlcv.items():
            if not df.empty and ts in df.index:
                prices[sym] = float(df.loc[ts, "close"])

        port.flush_stops(prices, ts)
        port.tick(prices, ts)
        port.check_stops(prices, ts, cfg)

        if now.hour in (0, 8, 16):
            for sym, pos in list(port.positions.items()):
                fr_series = all_funding.get(sym)
                if fr_series is None or fr_series.empty: continue
                recent_fr = fr_series[fr_series.index <= ts]
                if recent_fr.empty: continue
                fr     = float(recent_fr.iloc[-1])
                margin = pos.qty * pos.cost
                lev    = max(getattr(pos, 'leverage', 1.0), 1.0)
                cost   = margin * abs(fr) * lev
                if pos.side == 'long':
                    port.usdt -= cost * (1 if fr > 0 else -1)
                else:
                    port.usdt += cost * (1 if fr > 0 else -1)

        pv    = port.value(prices)
        level = risk.get_level(pv)

        if level == "CIRCUIT":
            just = risk.trigger_circuit(now)
            if just:
                for sym in list(port.positions.keys()):
                    port._pending_stop[sym] = "熔断强平"
                risk.reset_peak(pv)

        rs = regime.detect(btc_df, ts)
        regime_log.append({"time": ts, "regime": rs.regime})
        yearly_reg[year][rs.regime] += 1

        in_hard_block = risk.in_cooldown(now) or level == "CIRCUIT"
        can_open      = not in_hard_block and rs.max_slots > 0

        if can_open:
            candidates = signals.generate(active, all_ohlcv, all_funding, ts, rs)
            free_slots = rs.max_slots - len(port.positions)
            total_val  = port.value(prices)
            for sig in candidates:
                if free_slots <= 0: break
                sym = sig["symbol"]
                if sym in port.positions: continue
                margin_used = sum(pos.qty * pos.cost for pos in port.positions.values())
                if total_val > 0 and (margin_used / total_val) >= rs.position_cap - 0.01:
                    break
                n_slots  = max(rs.max_slots, 1)
                size_pct = min(rs.position_cap / n_slots, cfg.max_pos_pct)
                decision = risk.check_order(size_pct, total_val, level, now)
                if not decision.approve: continue
                price = prices.get(sym, 0)
                if price <= 0: continue
                buy_price = price * (1 + cfg.slippage_pct) if sig["direction"] > 0 else price * (1 - cfg.slippage_pct)
                port.open_position(sym, "long" if sig["direction"] > 0 else "short",
                                   buy_price, decision.size, total_val, ts, sig["strategy"],
                                   atr_pct=sig.get("atr_pct", 0.03), leverage=rs.leverage)
                free_slots -= 1

        pv = port.value(prices)
        nav = pv / cfg.cash
        equity_curve.append({"time": ts, "nav": nav})
        yearly_nav[year].append(nav)

    # ── 年度统计 ─────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("年度净值分解 (2022-2025)")
    print("="*60)

    all_navs = [e["nav"] for e in equity_curve]
    peak     = 1.0
    prev_year_end = 1.0

    for year in ["2022", "2023", "2024", "2025"]:
        navs = yearly_nav[year]
        if not navs:
            continue
        yr_start = navs[0]
        yr_end   = navs[-1]
        yr_ret   = (yr_end - yr_start) / yr_start * 100

        reg = yearly_reg[year]
        total_bars = sum(reg.values())
        reg_str = " | ".join(
            f"{r}={reg[r]/total_bars*100:.0f}%"
            for r in ["bull","ranging","bear","crisis"] if reg.get(r, 0) > 0
        )
        print(f"  {year}: {yr_ret:+7.1f}%  (NAV {yr_start:.3f}→{yr_end:.3f})  [{reg_str}]")

    # BTC 同期对比
    print()
    print("─" * 60)
    print("BTC 同期对比:")
    btc_close = btc_df["close"].astype(float)
    for year in ["2022","2023","2024","2025"]:
        year_bars = btc_close[btc_close.index.str.startswith(year)]
        if len(year_bars) < 2: continue
        btc_ret = (year_bars.iloc[-1] - year_bars.iloc[0]) / year_bars.iloc[0] * 100
        print(f"  BTC {year}: {btc_ret:+7.1f}%")

    print()
    print(f"总收益率: {(all_navs[-1]-1)*100:.1f}%  Sharpe ≈ 0.678（已知）")
    print("="*60)

    # 策略 vs BTC 超额收益
    print("\n策略 vs BTC 超额收益:")
    for year in ["2022","2023","2024","2025"]:
        navs = yearly_nav[year]
        if not navs: continue
        strat_ret = (navs[-1] - navs[0]) / navs[0] * 100
        year_bars = btc_close[btc_close.index.str.startswith(year)]
        if len(year_bars) < 2: continue
        btc_ret = (year_bars.iloc[-1] - year_bars.iloc[0]) / year_bars.iloc[0] * 100
        alpha   = strat_ret - btc_ret
        print(f"  {year}: 策略{strat_ret:+.1f}% | BTC{btc_ret:+.1f}% | Alpha {alpha:+.1f}%")


if __name__ == "__main__":
    run_with_yearly()
