"""
币安量化策略回测入口
用法：python backend/run_backtest.py [--start 2022-01-01] [--end 2024-12-31]

前置条件：
  1. 先运行 python scripts/fetch_data.py --all --start 2022-01-01 获取数据
  2. cache_db/crypto_data.db 必须有数据
"""
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import CFG
from core.data_feed import CryptoDataFeed
from core.portfolio import Portfolio
from agents.regime_agent import RegimeAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crypto.backtest")


def run(cfg=None):
    if cfg is None:
        cfg = CFG

    feed    = CryptoDataFeed()
    regime  = RegimeAgent(cfg)
    port    = Portfolio(cfg.cash)

    # ── 加载数据 ──────────────────────────────────────────────────────────
    logger.info("加载数据 %s ~ %s ...", cfg.start, cfg.end)
    all_ohlcv   = feed.get_all_ohlcv(cfg.symbols, cfg.timeframe, cfg.start, cfg.end)
    all_funding = feed.get_all_funding(cfg.symbols, cfg.start, cfg.end) \
                  if cfg.spot_or_futures == "futures" else {}
    btc_df      = feed.get_btc_ohlcv(cfg.timeframe, cfg.start, cfg.end)
    timestamps  = feed.get_trade_timestamps(cfg.timeframe, cfg.start, cfg.end)

    loaded = sum(1 for df in all_ohlcv.values() if not df.empty)
    logger.info("已加载 %d/%d 个品种  %d 个时间点",
                loaded, len(cfg.symbols), len(timestamps))

    if not timestamps:
        logger.error("没有数据！请先运行 scripts/fetch_data.py")
        return

    # ── 主循环 ────────────────────────────────────────────────────────────
    equity_curve = []
    peak_value   = cfg.cash

    for i, ts in enumerate(timestamps, 1):
        # 当前价格
        prices = {}
        for sym, df in all_ohlcv.items():
            if df is not None and not df.empty and ts in df.index:
                prices[sym] = float(df.loc[ts, "close"])

        # Step 1: 执行挂起止损
        port.flush_stops(prices, ts)

        # Step 2: 更新持仓
        port.tick(prices, ts)

        # Step 3: 止损检查
        port.check_stops(prices, ts, cfg)

        # Step 4: Regime 识别
        rs = regime.detect(btc_df, ts)

        # Step 5: 信号生成（简版，完整版待 signal_agent.py 实现）
        pv = port.value(prices)
        if pv > peak_value:
            peak_value = pv
        dd = (pv - peak_value) / peak_value

        # 记录净值
        equity_curve.append({"time": ts, "value": pv, "drawdown": dd})

        if i % 200 == 0 or i == len(timestamps):
            logger.info("[%d/%d] %s  资产=%.0f USDT  回撤=%.1f%%  Regime=%s",
                        i, len(timestamps), ts, pv, dd*100, rs.regime)

    # ── 输出结果 ──────────────────────────────────────────────────────────
    if equity_curve:
        final_val  = equity_curve[-1]["value"]
        total_ret  = (final_val - cfg.cash) / cfg.cash * 100
        max_dd     = min(e["drawdown"] for e in equity_curve) * 100
        logger.info("\n" + "="*50)
        logger.info("总收益: %.2f%%  最大回撤: %.2f%%", total_ret, max_dd)
        logger.info("总交易次数: %d", len([t for t in port.trades if "open" in t["side"]]))
        logger.info("="*50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=CFG.start)
    parser.add_argument("--end",   default=CFG.end)
    args = parser.parse_args()

    cfg = CFG.__class__(**{**CFG.__dict__, "start": args.start, "end": args.end})
    run(cfg)
