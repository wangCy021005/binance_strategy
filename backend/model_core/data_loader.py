"""
AlphaGPT 加密版数据加载器
从 SQLite 读取 OHLCV + 资金费率，构建训练张量
"""
import random
import sqlite3
from pathlib import Path

import pandas as pd
import torch

from .config import AlphaConfig
from .factors import compute_features

DB_PATH = Path(__file__).parent.parent.parent / "cache_db" / "crypto_data.db"


class CryptoDataLoader:
    def __init__(self, symbols: list[str], timeframe: str,
                 start: str, end: str):
        self.symbols   = symbols
        self.timeframe = timeframe
        self.start     = start
        self.end       = end
        self.feat_tensor    = None
        self.raw_data_cache = None
        self.target_ret     = None

    def load_data(self) -> "CryptoDataLoader":
        conn = sqlite3.connect(str(DB_PATH))

        # 读取 OHLCV
        syms_db = [s.replace("/", "") for s in self.symbols]
        ph = ",".join(["?" for _ in syms_db])
        df = pd.read_sql_query(
            f"SELECT symbol, open_time, open, high, low, close, volume "
            f"FROM ohlcv WHERE symbol IN ({ph}) "
            f"  AND timeframe=? AND open_time>=? AND open_time<=? "
            f"ORDER BY symbol, open_time",
            conn, params=syms_db + [self.timeframe, self.start, self.end]
        )

        # 读取资金费率（如有）
        try:
            fr_df = pd.read_sql_query(
                f"SELECT symbol, funding_time, funding_rate "
                f"FROM funding_rate WHERE symbol IN ({ph}) "
                f"  AND funding_time>=? AND funding_time<=? "
                f"ORDER BY symbol, funding_time",
                conn, params=syms_db + [self.start, self.end]
            )
        except Exception:
            fr_df = pd.DataFrame()

        conn.close()

        if df.empty:
            raise RuntimeError("数据库无数据，请先运行 fetch_data.py")

        # 对齐时间轴
        all_times = sorted(df["open_time"].unique())
        T = min(len(all_times), AlphaConfig.SEQ_LEN)
        all_times = all_times[-T:]

        raw = {}
        for field in ("open", "high", "low", "close", "volume"):
            pivot = (
                df.pivot(index="open_time", columns="symbol", values=field)
                  .reindex(index=all_times, columns=syms_db)
                  .ffill().fillna(method="bfill").fillna(1.0)
            )
            raw[field] = torch.tensor(
                pivot.values.T, dtype=torch.float32, device=AlphaConfig.DEVICE
            )

        # 资金费率对齐
        if not fr_df.empty:
            fr_pivot = (
                fr_df.pivot(index="funding_time", columns="symbol", values="funding_rate")
                     .reindex(index=all_times, columns=syms_db, method="ffill")
                     .fillna(0.0)
            )
            raw["funding"] = torch.tensor(
                fr_pivot.values.T, dtype=torch.float32, device=AlphaConfig.DEVICE
            )
        else:
            N = len(syms_db)
            raw["funding"] = torch.zeros(N, T, device=AlphaConfig.DEVICE)

        self.feat_tensor    = compute_features(raw)   # [N, 8, T]
        self.raw_data_cache = raw

        # 目标：未来1根K线的对数收益率
        close    = raw["close"]
        log_ret  = torch.zeros_like(close)
        log_ret[:, 1:] = torch.log((close[:, 1:]+1e-9) / (close[:, :-1]+1e-9))
        self.target_ret = torch.roll(log_ret, -1, dims=1)
        self.target_ret[:, -1] = 0.0

        print(f"[DataLoader] {len(syms_db)}个品种 × {T}根K线  "
              f"设备:{AlphaConfig.DEVICE}")
        return self
