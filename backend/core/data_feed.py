"""
Binance 数据层 — 通过 ccxt 获取 OHLCV + 资金费率 + 未平仓合约
本地缓存到 SQLite，回测期间零网络请求。
"""
from __future__ import annotations
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from config import DB_PATH

logger = logging.getLogger("crypto.data")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    """初始化数据库表结构"""
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol    TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            open_time TEXT NOT NULL,   -- UTC ISO8601
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            volume    REAL,
            PRIMARY KEY (symbol, timeframe, open_time)
        );
        CREATE TABLE IF NOT EXISTS funding_rate (
            symbol        TEXT NOT NULL,
            funding_time  TEXT NOT NULL,  -- UTC ISO8601
            funding_rate  REAL,
            PRIMARY KEY (symbol, funding_time)
        );
        CREATE TABLE IF NOT EXISTS open_interest (
            symbol    TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            oi_usdt   REAL,
            PRIMARY KEY (symbol, timestamp)
        );
        """)
    logger.info("数据库初始化完成: %s", DB_PATH)


class CryptoDataFeed:
    """统一数据入口，所有数据从 SQLite 读取（回测必须离线）"""

    def get_ohlcv(self, symbol: str, timeframe: str,
                  start: str, end: str) -> pd.DataFrame:
        """
        返回 OHLCV DataFrame，index=open_time(UTC字符串)
        columns: [open, high, low, close, volume]
        """
        sym_db = symbol.replace("/", "")  # BTC/USDT → BTCUSDT
        with _conn() as conn:
            df = pd.read_sql_query(
                "SELECT open_time, open, high, low, close, volume "
                "FROM ohlcv WHERE symbol=? AND timeframe=? "
                "  AND open_time >= ? AND open_time <= ? "
                "ORDER BY open_time",
                conn, params=(sym_db, timeframe, start, end)
            )
        if df.empty:
            return pd.DataFrame()
        return df.set_index("open_time").astype(float)

    def get_all_ohlcv(self, symbols: list[str], timeframe: str,
                      start: str, end: str) -> dict[str, pd.DataFrame]:
        """批量获取所有品种 OHLCV"""
        return {sym: self.get_ohlcv(sym, timeframe, start, end) for sym in symbols}

    def get_funding_rate(self, symbol: str,
                         start: str, end: str) -> pd.Series:
        """
        返回资金费率序列，index=funding_time(UTC), values=rate(小数)
        正值=多头付费给空头，负值=空头付费给多头
        """
        sym_db = symbol.replace("/", "")
        with _conn() as conn:
            df = pd.read_sql_query(
                "SELECT funding_time, funding_rate FROM funding_rate "
                "WHERE symbol=? AND funding_time >= ? AND funding_time <= ? "
                "ORDER BY funding_time",
                conn, params=(sym_db, start, end)
            )
        if df.empty:
            return pd.Series(dtype=float)
        return df.set_index("funding_time")["funding_rate"].astype(float)

    def get_all_funding(self, symbols: list[str],
                        start: str, end: str) -> dict[str, pd.Series]:
        return {sym: self.get_funding_rate(sym, start, end) for sym in symbols}

    def get_trade_timestamps(self, timeframe: str,
                             start: str, end: str) -> list[str]:
        """获取指定区间内所有唯一的 K 线时间戳（用于回测主循环）"""
        with _conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT open_time FROM ohlcv "
                "WHERE timeframe=? AND open_time >= ? AND open_time <= ? "
                "ORDER BY open_time",
                (timeframe, start, end)
            ).fetchall()
        return [r[0] for r in rows]

    def get_btc_ohlcv(self, timeframe: str,
                      start: str, end: str) -> pd.DataFrame:
        """BTC/USDT 作为市场基准"""
        return self.get_ohlcv("BTC/USDT", timeframe, start, end)
