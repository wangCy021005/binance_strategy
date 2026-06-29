"""
从 Binance 获取历史数据并缓存到 SQLite
用法：
  python scripts/fetch_data.py --symbol BTCUSDT --start 2022-01-01
  python scripts/fetch_data.py --all --start 2022-01-01  # 获取所有配置币种
  python scripts/fetch_data.py --update                   # 补全到最新

数据类型：
  1. OHLCV K线（4h 默认）
  2. 资金费率（每8小时）
  3. 未平仓合约（每小时）
"""
import sys
import sqlite3
import time
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import ccxt
import pandas as pd

from config import CFG, DB_PATH
from core.data_feed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("fetch")


def get_exchange():
    """初始化 Binance 交易所（公共 API，无需密钥）"""
    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "future"},   # 合约数据（有资金费率）
    })
    return exchange


def fetch_ohlcv(exchange, symbol: str, timeframe: str,
                start: str, end: str = None):
    """
    获取 OHLCV K线并存入 SQLite
    symbol: 如 "BTC/USDT"
    """
    sym_db = symbol.replace("/", "")
    since_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(end, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000) if end else None

    logger.info("获取 %s %s OHLCV from %s", symbol, timeframe, start)
    all_bars = []

    while True:
        bars = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1500)
        if not bars:
            break
        all_bars.extend(bars)
        last_ts = bars[-1][0]
        since_ms = last_ts + exchange.parse_timeframe(timeframe) * 1000

        if end_ms and since_ms > end_ms:
            break
        if len(bars) < 1500:
            break
        time.sleep(0.2)

    if not all_bars:
        logger.warning("%s 无数据", symbol)
        return

    # 过滤结束时间
    if end_ms:
        all_bars = [b for b in all_bars if b[0] <= end_ms]

    # 存入 SQLite
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = [(sym_db, timeframe,
             datetime.fromtimestamp(b[0]/1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             b[1], b[2], b[3], b[4], b[5]) for b in all_bars]
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv (symbol,timeframe,open_time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?)", data
    )
    conn.commit()
    conn.close()
    logger.info("  → 保存 %d 条K线", len(data))


def fetch_funding_rate(exchange, symbol: str, start: str, end: str = None):
    """获取资金费率历史"""
    sym_db = symbol.replace("/", "")
    since_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(end, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000) if end else None

    logger.info("获取 %s 资金费率 from %s", symbol, start)
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
        since_ms = last_ts + 8 * 3600 * 1000  # 资金费率每8小时

        if end_ms and since_ms > end_ms:
            break
        if len(rates) < 1000:
            break
        time.sleep(0.2)

    if not all_rates:
        return

    if end_ms:
        all_rates = [r for r in all_rates if r["timestamp"] <= end_ms]

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = [(sym_db,
             datetime.fromtimestamp(r["timestamp"]/1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             float(r["fundingRate"])) for r in all_rates]
    conn.executemany(
        "INSERT OR REPLACE INTO funding_rate (symbol,funding_time,funding_rate) VALUES (?,?,?)",
        data
    )
    conn.commit()
    conn.close()
    logger.info("  → 保存 %d 条资金费率", len(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="如 BTCUSDT 或 BTC/USDT")
    parser.add_argument("--all",   action="store_true", help="获取 config 中所有币种")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end",   default=None, help="默认到今天")
    parser.add_argument("--timeframe", default=CFG.timeframe)
    parser.add_argument("--update", action="store_true", help="只补全最新数据")
    args = parser.parse_args()

    # 初始化数据库
    init_db()

    exchange = get_exchange()
    end = args.end or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # 确定要获取的币种
    if args.all:
        symbols = CFG.symbols
    elif args.symbol:
        s = args.symbol.replace("USDT", "/USDT") if "USDT" in args.symbol else args.symbol
        symbols = [s]
    else:
        symbols = CFG.symbols

    logger.info("目标币种: %s", symbols)
    logger.info("时间范围: %s ~ %s", args.start, end)

    for symbol in symbols:
        fetch_ohlcv(exchange, symbol, args.timeframe, args.start, end)
        if CFG.spot_or_futures == "futures":
            fetch_funding_rate(exchange, symbol, args.start, end)
        time.sleep(0.5)

    logger.info("数据获取完成！")


if __name__ == "__main__":
    main()
