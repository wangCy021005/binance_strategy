"""
策略参数实验框架
一次加载数据，内存中跑多组参数配置，输出对比表

用法:
  python scripts/experiment.py                        # 跑预设实验组
  python scripts/experiment.py --sweep hard_stop      # 单参数扫描
"""
import sys, json, argparse, logging, itertools
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("experiment")

PROJECT_ROOT = Path(__file__).parent.parent


class StrategyParams:
    """实验参数（默认值 = 当前 config 基准）"""
    def __init__(self, **kw):
        # 止损
        self.hard_stop = -0.08          # 硬止损阈值
        self.trailing_pct = 0.12        # 追踪止损回撤
        self.trailing_min = 0.05        # 追踪启动最小盈利
        self.stop_mode = "intraday"     # intraday=盘中击穿按止损价 / close_confirm=收盘确认按收盘价
        self.cooldown_days = 0          # 同币种止损后冷静期（天）
        # 仓位
        self.position_cap = None        # None=用 regime 的
        # 组合熔断：trailing lookback 天内止损 ≥ portfolio_stop_count 笔 → 停止开新仓 portfolio_halt_days 天
        self.portfolio_stop_count = 0   # 0=禁用
        self.portfolio_lookback = 5
        self.portfolio_halt_days = 5
        # alpha 层实验
        self.mom_windows = None         # None=默认(42,126,252)，否则 (short, mid, long)
        self.btc_trend_filter = False   # ranging 时只做与 BTC 趋势同向的信号
        self.btc_trend_bars = 90        # BTC 趋势判定窗口
        # 均值回归策略（独立测试）
        self.strategy = "default"       # default=现有信号路由 / mr=RSI极值回归 / carry=费率收割
        self.mr_rsi_period = 2          # RSI 周期
        self.mr_rsi_low = 10            # 超卖阈值（做多）
        self.mr_rsi_high = 90           # 超买阈值（做空）
        self.mr_max_hold = 5            # 最大持有天数
        # 仓位层实验
        self.ranging_cap = None         # None=regime默认 / 数值=ranging 时总仓位上限覆盖
        self.ranging_slots = None       # None=regime默认 / 数值=ranging 时槽位数覆盖
        # carry 策略（独立测试）
        self.carry_threshold = 0.0001   # 3日平均费率高于此值才做空（0.01%/8h）
        self.carry_max_positions = 3    # 同时持有的 carry 空单数
        # 质量层实验
        self.max_hold = None            # None=不限 / 数值=持仓超过 N 平仓（动量衰减）
        self.top_k = None               # None=填满槽位 / 数值=只做评分前 K
        self.solo_pos_pct = None        # None=默认 / 数值=top_k=1 时的单仓比例
        # 实验标签
        self.label = "baseline"
        for k, v in kw.items():
            setattr(self, k, v)


def run_variant(all_ohlcv, all_funding, btc_df, ts_to_run, params, initial_cash=1000.0):
    """跑一组参数，返回 (nav_series, trades, metrics)"""
    from config import CFG
    from live.sim_exchange import SimExchange

    sim = SimExchange(initial_cash=initial_cash)
    sim.state = {
        "cash": initial_cash, "initial_cash": initial_cash,
        "positions": {}, "trades": [], "equity_history": [], "last_update": "",
    }
    sim._save()

    from agents.regime_agent import RegimeAgent
    from agents.signal_agent import SignalAgent
    import dataclasses
    if params.mom_windows:
        cfg2 = dataclasses.replace(CFG, mom_short_bars=params.mom_windows[0],
                                   mom_mid_bars=params.mom_windows[1],
                                   mom_long_bars=params.mom_windows[2])
    else:
        cfg2 = CFG
    regime = RegimeAgent(cfg2)
    signals = SignalAgent(cfg2)

    active = [s for s, df in all_ohlcv.items() if not df.empty]
    cooldown_until = {}  # symbol -> ts index 截止
    ts_index_cache = {t: i for i, t in enumerate(ts_to_run)}

    for idx, ts in enumerate(ts_to_run):
        prices, bar_ext = {}, {}
        for sym, df in all_ohlcv.items():
            if not df.empty and ts in df.index:
                prices[sym] = float(df.loc[ts, "close"])
                bar_ext[sym] = {"high": float(df.loc[ts, "high"]),
                                "low":  float(df.loc[ts, "low"])}

        # 止损检查
        if params.stop_mode == "intraday":
            sim.check_stops(prices, hard_stop=params.hard_stop,
                            trailing_pct=params.trailing_pct,
                            trailing_min=params.trailing_min,
                            bar_extremes=bar_ext, ts=ts)
        else:  # close_confirm: 不传极值，收盘价确认触发（可实盘实现：收盘条件单）
            sim.check_stops(prices, hard_stop=params.hard_stop,
                            trailing_pct=params.trailing_pct,
                            trailing_min=params.trailing_min, ts=ts)

        # 资金费率
        now = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now.hour in (0, 8, 16):
            sim.settle_funding(prices)

        # 持仓时间上限（动量衰减强制离场）
        if params.max_hold:
            for sym in list(sim.state["positions"].keys()):
                pos = sim.state["positions"][sym]
                ot = pos.get("open_time")
                if ot and ot in ts_index_cache and idx - ts_index_cache[ot] >= params.max_hold \
                        and prices.get(sym, 0) > 0:
                    sim.close_position(sym, prices[sym], "超时平仓", ts=ts)

        # Regime + 信号
        rs = regime.detect(btc_df, ts)

        if params.strategy == "carry":
            # ── carry 独立路径：做空 3 日平均费率最高的币，费率转负平仓 ──
            funding_avg = {}
            for sym in active:
                f = all_funding.get(sym)
                if f is None or f.empty:
                    continue
                recent = f[f.index <= ts].iloc[-9:]  # 3天=9个周期
                if len(recent) >= 3:
                    funding_avg[sym] = float(recent.mean())
            ranked = sorted(funding_avg.items(), key=lambda x: -x[1])
            top = [s for s, fr in ranked[:params.carry_max_positions] if fr > params.carry_threshold]
            for sym in top:
                if sym not in sim.state["positions"] and prices.get(sym, 0) > 0:
                    total_val = sim.get_balance(prices)["total"]
                    sim.open_position(sym, "short", total_val / params.carry_max_positions * 0.95,
                                     prices[sym], "carry", ts=ts)
            # 平仓：费率转负或跌出 top-N
            top_set = set(top)
            for sym in list(sim.state["positions"].keys()):
                pos = sim.state["positions"][sym]
                if pos.get("strategy") != "carry":
                    continue
                if sym not in top_set or funding_avg.get(sym, 0) <= 0:
                    if prices.get(sym, 0) > 0:
                        sim.close_position(sym, prices[sym], "carry退出", ts=ts)

        elif params.strategy == "mr":
            # ── 均值回归独立路径：RSI 极值进场，均值/超时出场 ──
            import numpy as np
            for sym in active:
                df = all_ohlcv[sym]
                hist = df[df.index <= ts]
                if len(hist) < 30:
                    continue
                close = hist["close"].astype(float)
                # RSI（Wilder 或简单均值版）
                delta = close.diff()
                period = params.mr_rsi_period
                gain = delta.clip(lower=0).rolling(period).mean()
                loss = (-delta.clip(upper=0)).rolling(period).mean()
                rs_ = gain / loss.replace(0, np.nan)
                rsi = 100 - 100 / (1 + rs_)
                if np.isnan(rsi.iloc[-1]):
                    continue
                pos = sim.state["positions"].get(sym)
                price = prices.get(sym, 0)
                if price <= 0:
                    continue
                if pos:
                    # 出场：持有超 mr_max_hold 天
                    open_idx = ts_to_run.index(pos.get("open_time")) if pos.get("open_time") in ts_to_run else idx
                    if idx - open_idx >= params.mr_max_hold:
                        sim.close_position(sym, price, "mr超时", ts=ts)
                    continue
                # 进场：RSI 极值
                total_val = sim.get_balance(prices)["total"]
                size = total_val * 0.10
                if rsi.iloc[-1] < params.mr_rsi_low:
                    sim.open_position(sym, "long", size, price, "mr", ts=ts)
                elif rsi.iloc[-1] > params.mr_rsi_high:
                    sim.open_position(sym, "short", size, price, "mr", ts=ts)

        elif rs.max_slots > 0:
            # 组合熔断：近 lookback 天内止损次数 ≥ 阈值 → 跳过开仓 halt_days 天
            halt = False
            if params.portfolio_stop_count > 0:
                ts_index = {t: i for i, t in enumerate(ts_to_run)}
                recent_stops = sum(
                    1 for t in sim.state["trades"]
                    if "止损" in t.get("reason", "")
                    and t["time"] in ts_index
                    and idx - ts_index[t["time"]] <= params.portfolio_lookback)
                halt = recent_stops >= params.portfolio_stop_count
            if not halt:
                candidates = signals.generate(active, all_ohlcv, all_funding, ts, rs)
                # BTC 趋势过滤：ranging 时只做与 BTC 慢趋势同向的信号
                if params.btc_trend_filter and rs.regime == "ranging" and not btc_df.empty:
                    btc_close = btc_df[btc_df.index <= ts]["close"].astype(float)
                    if len(btc_close) > params.btc_trend_bars:
                        btc_trend = btc_close.pct_change(params.btc_trend_bars).iloc[-1]
                        if btc_trend > 0:
                            candidates = [s for s in candidates if s["direction"] > 0]
                        elif btc_trend < 0:
                            candidates = [s for s in candidates if s["direction"] < 0]
                n_slots = max(rs.max_slots, 1)
                pos_cap = rs.position_cap
                if rs.regime == "ranging":
                    if params.ranging_slots:
                        n_slots = params.ranging_slots
                    if params.ranging_cap:
                        pos_cap = params.ranging_cap
                if params.top_k:
                    n_slots = min(n_slots, params.top_k)
                size_pct = min(pos_cap / n_slots, CFG.max_pos_pct)
                if params.solo_pos_pct and params.top_k:
                    size_pct = params.solo_pos_pct
                total_val = sim.get_balance(prices)["total"]
                opened = 0
                for sig in candidates[:n_slots]:
                    if opened >= n_slots:
                        break
                    sym = sig["symbol"]
                    if sym in sim.state["positions"]:
                        continue
                    # 冷静期检查：该币最近一笔止损在 cooldown_days 内则跳过
                    if params.cooldown_days > 0:
                        last_trade = None
                        for t in reversed(sim.state["trades"]):
                            if t["symbol"] == sym:
                                last_trade = t
                                break
                        if last_trade and "止损" in last_trade.get("reason", ""):
                            t_idx = ts_to_run.index(last_trade["time"]) if last_trade["time"] in ts_to_run else -1
                            if 0 <= t_idx and idx - t_idx <= params.cooldown_days:
                                continue
                    price = prices.get(sym, 0)
                    if price <= 0:
                        continue
                    margin_used = sum(p["qty"] * p["entry"] for p in sim.state["positions"].values())
                    if total_val > 0 and margin_used / total_val >= pos_cap - 0.01:
                        break
                    size = total_val * size_pct
                    if sim.open_position(sym, "long" if sig["direction"] > 0 else "short",
                                         size, price, sig.get("strategy", ""), ts=ts):
                        opened += 1

        sim.record_equity(prices, ts=ts)

    # 指标
    eh = sim.state["equity_history"]
    navs = [e["nav"] for e in eh]
    trades = sim.state["trades"]
    total_ret = navs[-1] - 1
    days = len(eh)
    annual = (navs[-1]) ** (365 / days) - 1
    # Sharpe（日收益）
    rets = [(navs[i] / navs[i - 1] - 1) for i in range(1, len(navs)) if navs[i - 1] > 0]
    import statistics
    if len(rets) > 30 and statistics.stdev(rets) > 0:
        sharpe = (statistics.mean(rets) / statistics.stdev(rets)) * (365 ** 0.5)
    else:
        sharpe = 0
    peak, maxdd = 0, 0
    for n in navs:
        peak = max(peak, n)
        maxdd = min(maxdd, n / peak - 1)
    wins = sum(1 for t in trades if t["pnl"] > 0)

    metrics = {
        "label": params.label,
        "total": round(total_ret * 100, 2),
        "annual": round(annual * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(maxdd * 100, 2),
        "trades": len(trades),
        "winrate": round(wins / max(len(trades), 1) * 100, 1),
        "final_nav": round(navs[-1], 4),
    }
    return metrics, trades, eh


def load_data(start="2025-01-01"):
    from config import CFG
    from core.data_feed import CryptoDataFeed
    feed = CryptoDataFeed()
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_ohlcv = feed.get_all_ohlcv(CFG.symbols, "1d", "2022-01-01", end_date)
    all_funding = feed.get_all_funding(CFG.symbols, "2022-01-01", end_date)
    btc_df = feed.get_btc_ohlcv("1d", "2022-01-01", end_date)
    timestamps = feed.get_trade_timestamps("1d", "2022-01-01", end_date)
    ts_to_run = [t for t in timestamps if t >= f"{start}T00:00:00Z"]
    return all_ohlcv, all_funding, btc_df, timestamps, ts_to_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--sweep", default=None, help="扫描参数名")
    parser.add_argument("--mode", default="combo", help="combo|window")
    args = parser.parse_args()

    print(f"加载数据（回放区间 {args.start} → 今天）...")
    all_ohlcv, all_funding, btc_df, _, ts_to_run = load_data(args.start)
    print(f"回放 {len(ts_to_run)} 个交易日\n")

    variants = []
    if args.sweep == "hard_stop":
        for hs in [-0.06, -0.08, -0.10, -0.12, -0.15, -0.20]:
            variants.append(StrategyParams(hard_stop=hs, label=f"hard_stop={hs}"))
    elif args.sweep == "trailing":
        for tp in [0.08, 0.10, 0.12, 0.15, 0.20, 0.25]:
            variants.append(StrategyParams(trailing_pct=tp, label=f"trailing={tp}"))
    elif args.sweep == "stop_mode":
        variants.append(StrategyParams(stop_mode="close_confirm", label="close_confirm"))
        variants.append(StrategyParams(stop_mode="intraday", label="intraday(基准)"))
    elif args.sweep == "cooldown":
        for cd in [0, 3, 5, 10]:
            variants.append(StrategyParams(cooldown_days=cd, label=f"cooldown={cd}天"))
    elif args.sweep == "window":
        variants = [
            StrategyParams(stop_mode="close_confirm", label="收盘确认"),
            StrategyParams(stop_mode="intraday", label="盘中击穿"),
        ]
    else:
        # 集中持仓放宽 + 超时微调（底座=超时20+top1，双窗口验证过）
        base = dict(stop_mode="close_confirm", cooldown_days=3, trailing_pct=0.20,
                    max_hold=20, top_k=1)
        variants = [
            StrategyParams(**base, solo_pos_pct=0.70, label="单仓70%(参照)"),
            StrategyParams(**base, solo_pos_pct=0.40, label="单仓40%"),
            StrategyParams(**base, solo_pos_pct=0.60, label="单仓60%"),
            StrategyParams(**{**base, "top_k": 2}, solo_pos_pct=0.35, label="top2×单仓35%"),
            StrategyParams(**{**base, "top_k": 2}, solo_pos_pct=0.45, label="top2×单仓45%"),
        ]

    results = []
    for p in variants:
        m, _, _ = run_variant(all_ohlcv, all_funding, btc_df, ts_to_run, p)
        results.append(m)
        print(f"{m['label']:24s} 年化{m['annual']:8.2f}%  总{m['total']:8.2f}%  "
              f"Sharpe {m['sharpe']:6.3f}  MDD {m['mdd']:7.2f}%  "
              f"{m['trades']}笔 胜率{m['winrate']}%")

    Path("/tmp/experiment_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("\n结果已存 /tmp/experiment_results.json")


if __name__ == "__main__":
    main()
