"""
从 Binance 获取历史数据并缓存到 SQLite
用法：
  python scripts/fetch_data.py --all --start 2022-01-01
  python scripts/fetch_data.py --symbol BTCUSDT --start 2022-01-01

两个接口：
  - ccxt.binance       → 现货 OHLCV（spot API）
  - ccxt.binanceusdm   → USDT本位永续合约资金费率（fapi API，不用dapi）
"""
import sys
import sqlite3
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import ccxt
from config import CFG, DB_PATH
from core.data_feed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fetch")


def get_spot_exchange():
    """现货 K 线（只加载 spot 市场，跳过 coin-M 期货避免 dapi 被拦）
    国内服务器覆盖 public 域名为 binance.vision（公共数据，免代理可达）
    """
    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"fetchMarkets": ["spot"]},
    })
    # 用 dict 方式覆盖 public endpoint（避免 sandbox 检测错误）
    ex.urls['api']['public'] = 'https://data-api.binance.vision/api/v3'
    return ex


def get_futures_exchange():
    """USDT 本位永续合约（fapi.binance.com，不是 dapi）"""
    return ccxt.binanceusdm({"enableRateLimit": True})


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str = None):
    """获取现货 OHLCV K线"""
    sym_db = symbol.replace("/", "")
    exchange = get_spot_exchange()

    since_ms = int(datetime.strptime(start, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = (int(datetime.strptime(end, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp() * 1000)
              if end else None)

    logger.info("获取 %s %s OHLCV from %s", symbol, timeframe, start)
    all_bars = []

    while True:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        except Exception as e:
            logger.error("OHLCV 获取失败: %s", e)
            break

        if not bars:
            break
        all_bars.extend(bars)
        last_ts = bars[-1][0]
        since_ms = last_ts + exchange.parse_timeframe(timeframe) * 1000

        if end_ms and since_ms > end_ms:
            break
        if len(bars) < 1000:
            break
        time.sleep(0.3)

    if not all_bars:
        logger.warning("  %s 无数据", symbol)
        return 0

    if end_ms:
        all_bars = [b for b in all_bars if b[0] <= end_ms]

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = [
        (sym_db, timeframe,
         datetime.fromtimestamp(b[0]/1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         b[1], b[2], b[3], b[4], b[5])
        for b in all_bars
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv (symbol,timeframe,open_time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?)", data
    )
    conn.commit()
    conn.close()
    logger.info("  → %d 根K线", len(data))
    return len(data)


def fetch_funding_rate(symbol: str, start: str, end: str = None):
    """获取 USDT 本位永续合约资金费率（用 binanceusdm）"""
    sym_db = symbol.replace("/", "")
    exchange = get_futures_exchange()

    since_ms = int(datetime.strptime(start, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = (int(datetime.strptime(end, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp() * 1000)
              if end else None)

    logger.info("获取 %s 资金费率", symbol)
    all_rates = []

    while True:
        try:
            rates = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=1000)
        except Exception as e:
            logger.warning("资金费率获取失败: %s", e)
            break

        if not rates:
            break
        all_rates.extend(rates)
        last_ts = rates[-1]["timestamp"]
        since_ms = last_ts + 8 * 3600 * 1000

        if end_ms and since_ms > end_ms:
            break
        if len(rates) < 1000:
            break
        time.sleep(0.3)

    if not all_rates:
        return 0

    if end_ms:
        all_rates = [r for r in all_rates if r["timestamp"] <= end_ms]

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = [
        (sym_db,
         datetime.fromtimestamp(r["timestamp"]/1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         float(r["fundingRate"]))
        for r in all_rates
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO funding_rate (symbol,funding_time,funding_rate) VALUES (?,?,?)",
        data
    )
    conn.commit()
    conn.close()
    logger.info("  → %d 条资金费率", len(data))
    return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--all",    action="store_true")
    parser.add_argument("--start",  default="2022-01-01")
    parser.add_argument("--end",    default=None)
    parser.add_argument("--timeframe", default=CFG.timeframe)
    parser.add_argument("--no-funding", action="store_true", help="跳过资金费率")
    args = parser.parse_args()

    init_db()

    end = args.end or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    if args.all:
        symbols = CFG.symbols
    elif args.symbol:
        s = args.symbol
        if "USDT" in s and "/" not in s:
            s = s.replace("USDT", "/USDT")
        symbols = [s]
    else:
        symbols = CFG.symbols

    logger.info("目标: %d 个品种  %s ~ %s  周期=%s",
                len(symbols), args.start, end, args.timeframe)

    total_bars    = 0
    total_funding = 0

    for symbol in symbols:
        # K线
        n = fetch_ohlcv(symbol, args.timeframe, args.start, end)
        total_bars += n

        # 资金费率（合约）
        if not args.no_funding and CFG.spot_or_futures == "futures":
            m = fetch_funding_rate(symbol, args.start, end)
            total_funding += m

        time.sleep(0.5)

    logger.info("\n完成！共 %d 根K线，%d 条资金费率", total_bars, total_funding)
    logger.info("数据库: %s", DB_PATH)


if __name__ == "__main__":
    main()
