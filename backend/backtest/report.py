"""
回测报告生成
输出 data/latest.json（可接前端展示）
"""
from __future__ import annotations
import json
import numpy as np
from pathlib import Path

from config import DASH_DIR


def write_report(equity_curve: list, trades: list, regime_log: list, cfg):
    """写入 data/latest.json"""
    if not equity_curve:
        return

    navs = [e["nav"] for e in equity_curve]

    # 年化收益
    n_periods = len(navs)
    periods_per_year = _periods_per_year(cfg.timeframe)
    total_ret = navs[-1] - 1
    annual_ret = ((navs[-1]) ** (periods_per_year / max(n_periods, 1)) - 1) * 100

    # 最大回撤
    peak = navs[0]
    max_dd = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Sharpe（无风险利率取3% USDT 稳定币年化）
    rf_per_period = 0.03 / periods_per_year
    rets = np.diff(navs) / np.array(navs[:-1])
    excess = rets - rf_per_period
    sharpe = float(np.mean(excess) / (np.std(excess) + 1e-9) * np.sqrt(periods_per_year)) \
             if len(excess) > 0 else 0.0

    # 交易统计
    sells = [t for t in trades if "close" in t.get("side", "")]
    wins  = [t for t in sells if t.get("pnl_pct", 0) > 0]
    win_rate = len(wins) / max(len(sells), 1)

    # 策略分布
    strategy_dist = {}
    for t in trades:
        s = t.get("strategy", "?")
        strategy_dist[s] = strategy_dist.get(s, 0) + 1

    # Regime 分布
    regime_dist = {}
    for r in regime_log:
        regime_dist[r["regime"]] = regime_dist.get(r["regime"], 0) + 1

    data = {
        "meta": {
            "start":     cfg.start,
            "end":       cfg.end,
            "cash":      cfg.cash,
            "symbols":   cfg.symbols,
            "timeframe": cfg.timeframe,
        },
        "stats": {
            "annual_return": round(annual_ret, 2),
            "total_return":  round(total_ret * 100, 2),
            "sharpe":        round(sharpe, 3),
            "max_drawdown":  round(max_dd * 100, 2),
            "total_trades":  len(sells),
            "win_rate":      round(win_rate, 3),
        },
        "equity":  equity_curve[-500:],   # 最近500个点
        "trades":  trades[-200:],          # 最近200笔
        "regime":  [[r["time"][:10], r["regime"]] for r in regime_log],
        "strategy_dist": strategy_dist,
        "regime_dist":   regime_dist,
    }

    DASH_DIR.mkdir(parents=True, exist_ok=True)
    out = DASH_DIR / "latest.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def print_summary(equity_curve: list, trades: list, regime_log: list, cfg):
    sells     = [t for t in trades if "close" in t.get("side", "")]
    wins      = [t for t in sells if t.get("pnl_pct", 0) > 0]
    navs      = [e["nav"] for e in equity_curve]
    final_nav = navs[-1] if navs else 1.0

    periods_per_year = _periods_per_year(cfg.timeframe)
    n = len(navs)
    annual_ret = ((final_nav) ** (periods_per_year / max(n, 1)) - 1) * 100

    peak = navs[0] if navs else 1
    max_dd = 0.0
    for nav in navs:
        if nav > peak: peak = nav
        dd = (nav - peak) / peak
        if dd < max_dd: max_dd = dd

    rets    = np.diff(navs) / np.array(navs[:-1]) if len(navs) > 1 else []
    rf_pp   = 0.03 / periods_per_year
    excess  = np.array(rets) - rf_pp if len(rets) else np.array([0])
    sharpe  = float(np.mean(excess) / (np.std(excess)+1e-9) * np.sqrt(periods_per_year))

    regime_dist = {}
    for r in regime_log:
        regime_dist[r["regime"]] = regime_dist.get(r["regime"], 0) + 1
    total_d = len(regime_log)

    print("\n" + "="*60)
    print("币安量化策略回测结果")
    print("="*60)
    print(f"回测区间:       {cfg.start} ~ {cfg.end}")
    print(f"初始资金:       {cfg.cash:,.0f} USDT")
    print(f"最终资产:       {final_nav * cfg.cash:,.0f} USDT")
    print(f"总收益率:       {(final_nav-1)*100:.2f}%")
    print(f"年化收益率:     {annual_ret:.2f}%")
    print(f"Sharpe 比率:    {sharpe:.3f}")
    print(f"最大回撤:       {max_dd*100:.2f}%")
    print("-"*60)
    print(f"总交易次数:     {len(sells)}")
    win_rate = len(wins) / max(len(sells), 1)
    print(f"胜率:           {win_rate*100:.1f}%")
    print("-"*60)
    print("市场状态分布:")
    for r, cnt in sorted(regime_dist.items(), key=lambda x: -x[1]):
        pct = cnt / total_d * 100 if total_d > 0 else 0
        print(f"  {r:<12}:  {cnt:4d} 根K线  ({pct:.1f}%)")
    print("="*60)


def _periods_per_year(timeframe: str) -> float:
    mapping = {"1m": 525600, "5m": 105120, "15m": 35040,
               "1h": 8760, "4h": 2190, "1d": 365}
    return mapping.get(timeframe, 2190)
