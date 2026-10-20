"""
历史模拟补全脚本
从指定日期用 SimExchange 逻辑逐日回测，生成完整净值曲线

用途：Dashboard 净值曲线从去年连续到今天
逻辑：和实时模拟完全一致（开仓/止损/资金费率），用历史 K 线逐日推进

用法：
  python scripts/backfill_sim.py                    # 默认 2025-01 至今
  python scripts/backfill_sim.py --start 2025-06-01
"""
import sys, json, argparse, logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("backfill")

PROJECT_ROOT = Path(__file__).parent.parent


def run_backfill(start_date: str = "2025-01-01"):
    from config import CFG
    from core.data_feed import CryptoDataFeed
    from agents.regime_agent import RegimeAgent
    from agents.signal_agent import SignalAgent
    from live.sim_exchange import SimExchange

    feed    = CryptoDataFeed()
    regime  = RegimeAgent(CFG)
    signals = SignalAgent(CFG)

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 加载历史数据
    logger.info("加载数据 %s ~ %s", start_date, end_date)
    all_ohlcv   = feed.get_all_ohlcv(CFG.symbols, "1d", "2022-01-01", end_date)
    all_funding = feed.get_all_funding(CFG.symbols, "2022-01-01", end_date)
    btc_df      = feed.get_btc_ohlcv("1d", "2022-01-01", end_date)
    timestamps  = feed.get_trade_timestamps("1d", "2022-01-01", end_date)

    # 只跑 start_date 之后的
    ts_to_run = [t for t in timestamps if t >= f"{start_date}T00:00:00Z"]
    logger.info("回测 %d 个交易日 (%s ~ %s)", len(ts_to_run),
                ts_to_run[0][:10], ts_to_run[-1][:10])

    # 初始化模拟账户 — 从干净状态开始（不加载已有持仓，避免价格尺度冲突）
    sim = SimExchange(initial_cash=1000.0)
    sim.state = {
        "cash":           1000.0,
        "initial_cash":   1000.0,
        "positions":      {},
        "trades":         [],
        "equity_history": [],
        "last_update":    "",
    }
    sim._save()
    logger.info("初始化干净账户: 1000 USDT")

    active = [s for s, df in all_ohlcv.items() if not df.empty]

    for i, ts in enumerate(ts_to_run, 1):
        # 当日收盘价（用历史数据，不用实时拉取）
        prices = {}
        for sym, df in all_ohlcv.items():
            if not df.empty and ts in df.index:
                prices[sym] = float(df.loc[ts, "close"])

        # 1. 止损检查（用当日价格）
        sim.check_stops(
            prices,
            hard_stop=CFG.hard_stop,
            trailing_pct=CFG.trailing_stop_pct,
            trailing_min=CFG.trailing_stop_min,
        )

        # 2. 资金费率结算
        now = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now.hour in (0, 8, 16):
            sim.settle_funding(prices)

        # 3. Regime 识别
        rs = regime.detect(btc_df, ts)

        # 4. 信号生成 + 开仓
        if rs.max_slots > 0:
            candidates = signals.generate(active, all_ohlcv, all_funding, ts, rs)
            n_slots  = max(rs.max_slots, 1)
            size_pct = min(rs.position_cap / n_slots, CFG.max_pos_pct)
            total_val = sim.get_balance(prices)["total"]

            opened = 0
            for sig in candidates[:n_slots]:
                if opened >= n_slots:
                    break
                sym = sig["symbol"]
                if sym in sim.state["positions"]:
                    continue
                price = prices.get(sym, 0)
                if price <= 0:
                    continue
                # 保证金上限检查
                margin_used = sum(p["qty"]*p["entry"] for p in sim.state["positions"].values())
                if total_val > 0 and margin_used / total_val >= rs.position_cap - 0.01:
                    break
                size = total_val * size_pct
                if sim.open_position(sym, "long" if sig["direction"] > 0 else "short",
                                      size, price, sig.get("strategy", "")):
                    opened += 1

        # 5. 记录净值（用当日价格 + 当日时间戳，不能用 now()）
        nav = sim.record_equity(prices, ts=ts)

        if i % 50 == 0 or i == len(ts_to_run):
            n_pos = len(sim.state["positions"])
            n_trades = len(sim.state["trades"])
            logger.info("[%d/%d] %s NAV=%.4f 持仓%d 交易%d",
                        i, len(ts_to_run), ts[:10], nav, n_pos, n_trades)

    # 保存
    sim_path = PROJECT_ROOT / "data" / "sim_account.json"
    sim.state["equity_history"] = sim.state["equity_history"][-1000:]  # 保留1000天（覆盖2025起完整区间）
    sim_path.write_text(json.dumps(sim.state, indent=2, ensure_ascii=False))
    logger.info("✅ 保存到 %s", sim_path)

    # 统计
    hist = sim.state["equity_history"]
    if hist:
        final_nav = hist[-1]["nav"]
        logger.info("最终净值: %.4f (收益 %.2f%%)", final_nav, (final_nav-1)*100)
        logger.info("交易笔数: %d, 胜率: %.1f%%",
                     len(sim.state["trades"]),
                     sum(1 for t in sim.state["trades"] if t.get("pnl",0)>0)/max(len(sim.state["trades"]),1)*100)

    return sim


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    args = parser.parse_args()
    run_backfill(args.start)
