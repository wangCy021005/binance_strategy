"""
美股历史数据采集脚本（yfinance）
存入 SQLite ohlcv 表，与加密数据共用同一结构。

用法：
  python scripts/fetch_stocks.py --all --start 2022-01-01
  python scripts/fetch_stocks.py --symbol NVDA --start 2020-01-01

时区：交易日日期（ET，无时间部分），格式 YYYY-MM-DDT00:00:00Z
     与加密日线对齐（加密日线也以 UTC 00:00 为时间戳）
"""
import sys, sqlite3, time, argparse, logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import yfinance as yf
from config import CFG, DB_PATH
from core.data_feed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("fetch_stocks")


def fetch_stock(ticker: str, start: str, end: str = None):
    """
    下载单只美股日线数据并存入 SQLite。
    ticker: 如 'NVDA'
    """
    end_dt = end or datetime.now().strftime("%Y-%m-%d")

    logger.info("获取 %s  %s ~ %s", ticker, start, end_dt)

    for attempt in range(3):
        try:
            df = yf.download(ticker, start=start, end=end_dt,
                             progress=False, auto_adjust=True)
            break
        except Exception as e:
            logger.warning("  尝试 %d/3 失败: %s", attempt+1, e)
            time.sleep(5 * (attempt + 1))
    else:
        logger.error("  %s 获取失败", ticker)
        return 0

    if df.empty:
        logger.warning("  %s 无数据", ticker)
        return 0

    # 统一列名
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"}) if "adj close" in df.columns else df

    # 存入 SQLite（symbol = "NVDA_STOCK" 以区分加密）
    sym_db = f"{ticker}_STOCK"
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    data = []
    for ts, row in df.iterrows():
        # 用交易日日期作为时间戳（00:00:00Z）
        date_str = ts.strftime("%Y-%m-%dT00:00:00Z")
        data.append((
            sym_db, "1d", date_str,
            float(row.get("open", row.get("close", 0))),
            float(row.get("high", row.get("close", 0))),
            float(row.get("low",  row.get("close", 0))),
            float(row.get("close", 0)),
            float(row.get("volume", 0)),
        ))

    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv "
        "(symbol,timeframe,open_time,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?,?)", data
    )
    conn.commit()
    conn.close()
    logger.info("  → %d 根日线", len(data))
    return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="单只股票，如 NVDA")
    parser.add_argument("--all",    action="store_true", help="获取 config 中所有美股")
    parser.add_argument("--start",  default="2022-01-01")
    parser.add_argument("--end",    default=None)
    args = parser.parse_args()

    init_db()

    tickers = CFG.us_stocks if args.all else ([args.symbol] if args.symbol else CFG.us_stocks)
    logger.info("目标: %d 只美股  %s ~ %s", len(tickers), args.start, args.end or "今天")

    total = 0
    for ticker in tickers:
        n = fetch_stock(ticker, args.start, args.end)
        total += n
        time.sleep(1.5)  # 限速，避免被 Yahoo Finance 封禁

    logger.info("\n完成！共 %d 根日线", total)


if __name__ == "__main__":
    main()
