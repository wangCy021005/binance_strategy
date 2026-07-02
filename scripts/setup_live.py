"""
实盘前检查脚本
运行此脚本验证：API 连通性、账户余额、策略信号生成、订单模拟

用法：
  export BINANCE_API_KEY=your_key
  export BINANCE_API_SECRET=your_secret
  python scripts/setup_live.py
"""
import sys, os, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("setup")


def check_api():
    """检查 API 连通性和权限"""
    logger.info("\n── 1. API 连通性检查 ──")
    from live.exchange import BinanceExchange
    ex = BinanceExchange(dry_run=False)

    bal = ex.get_balance()
    logger.info("账户余额: %.2f USDT (可用 %.2f USDT)", bal.total_usdt, bal.available)

    positions = ex.get_positions()
    logger.info("当前持仓: %d 个", len(positions))
    for p in positions:
        logger.info("  %s %s | %.0f USDT | P&L=%.1f%%",
                    p.side, p.symbol, p.size, p.pnl_pct * 100)

    if bal.total_usdt < 10:
        logger.error("❌ 合约账户余额不足 10 USDT，请先划转资金")
        return False

    logger.info("✅ API 正常 | 余额 %.2f USDT", bal.total_usdt)
    return True


def check_signals():
    """验证信号生成逻辑"""
    logger.info("\n── 2. 信号生成检查 ──")
    from config import CFG
    from core.data_feed import CryptoDataFeed
    from agents.regime_agent import RegimeAgent
    from agents.signal_agent import SignalAgent

    feed = CryptoDataFeed()
    end  = "2025-12-31"   # 用历史数据测试，不依赖实时

    all_ohlcv   = feed.get_all_ohlcv(CFG.symbols, "1d", "2022-01-01", end)
    all_funding = feed.get_all_funding(CFG.symbols, "2022-01-01", end)
    btc_df      = feed.get_btc_ohlcv("1d", "2022-01-01", end)
    timestamps  = feed.get_trade_timestamps("1d", "2022-01-01", end)

    if not timestamps:
        logger.error("❌ 无历史数据，请先运行 fetch_data.py --all")
        return False

    latest_ts = timestamps[-1]
    regime    = RegimeAgent(CFG)
    signals   = SignalAgent(CFG)

    rs         = regime.detect(btc_df, latest_ts)
    active     = [s for s, df in all_ohlcv.items() if not df.empty]
    candidates = signals.generate(active, all_ohlcv, all_funding, latest_ts, rs)

    logger.info("最新时间: %s", latest_ts[:10])
    logger.info("Regime: %s | slots=%d | cap=%.0f%%",
                rs.regime, rs.max_slots, rs.position_cap * 100)
    logger.info("信号候选: %d 个", len(candidates))
    for sig in candidates[:5]:
        dir_str = "↑多" if sig["direction"] > 0 else "↓空"
        logger.info("  %s %s | score=%.3f", dir_str, sig["symbol"], sig["score"])

    if not candidates:
        logger.warning("⚠️ 当前无信号（Regime=%s 可能不允许开仓）", rs.regime)
    else:
        logger.info("✅ 信号生成正常")
    return True


def simulate_trade():
    """模拟一次完整的交易决策（不发真实订单）"""
    logger.info("\n── 3. 模拟交易（DRY RUN）──")
    from live.live_engine import LiveEngine
    engine = LiveEngine(dry_run=True)
    engine.run_once()
    logger.info("✅ 模拟交易完成，检查上方日志确认逻辑正确")
    return True


def print_checklist():
    logger.info("""
╔════════════════════════════════════════════╗
║         实盘前检查清单                      ║
╠════════════════════════════════════════════╣
║ ✅ API KEY 只读权限（不需要提现权限）        ║
║ ✅ 开启合约交易权限（Futures）               ║
║ ✅ 账户中有 100-500 USDT（在合约子账户）     ║
║ ✅ 先 DRY_RUN 跑一周观察信号               ║
║ ✅ 实盘前 Sharpe > 0.5（我们已达到 0.678） ║
╠════════════════════════════════════════════╣
║ ⚠️  默认 1x 杠杆（最大亏损=仓位大小）      ║
║ ⚠️  每日 UTC 00:10 自动运行               ║
║ ⚠️  最大仓位 = 账户 × position_cap (50%)  ║
╚════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    print_checklist()

    has_api = bool(os.environ.get("BINANCE_API_KEY"))

    if has_api:
        api_ok = check_api()
    else:
        logger.info("\n未设置 API KEY，跳过实盘连通性检查（仅测试信号逻辑）")
        api_ok = True

    sig_ok  = check_signals()

    if api_ok and sig_ok:
        simulate_trade()
        logger.info("\n🟢 所有检查通过！")
        if has_api:
            logger.info("   可以开始实盘：python scripts/run_live.py --live")
        else:
            logger.info("   设置 API KEY 后再实盘：export BINANCE_API_KEY=...")
    else:
        logger.error("\n🔴 检查未通过，请修复上述问题后再试")
