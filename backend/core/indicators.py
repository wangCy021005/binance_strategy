"""
加密货币技术指标 + 币安特有指标

A股教训：
  - ADX 在加密市场依然滞后，但可用于确认
  - RSI 在加密强趋势中可持续超买/超卖（与A股类似）
  - 加密特有：资金费率、OI变化是更强的 Alpha 来源

知识库第09课：IC > 0.03 才算有效因子
加密市场动量IC = +0.04~0.08（正值！与A股相反，趋势跟随有效）
"""
import numpy as np
import pandas as pd


def calc_returns(df: pd.DataFrame, periods: int = 1) -> pd.Series:
    """对数收益率"""
    return np.log(df["close"] / df["close"].shift(periods))


def calc_momentum(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """动量因子（过去N根K线收益率）"""
    return df["close"].pct_change(window)


def calc_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """平均真实波幅（用于仓位计算和止损）"""
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def calc_rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """RSI 动量指标"""
    delta  = df["close"].astype(float).diff()
    gain   = delta.clip(lower=0).rolling(window).mean()
    loss   = (-delta.clip(upper=0)).rolling(window).mean()
    rs     = gain / (loss + 1e-9)
    return 100 - 100 / (1 + rs)


def calc_bollinger(df: pd.DataFrame, window: int = 20,
                   num_std: float = 2.0) -> pd.DataFrame:
    """布林带（均值回归用）"""
    ma    = df["close"].rolling(window).mean()
    std   = df["close"].rolling(window).std()
    return pd.DataFrame({
        "upper": ma + num_std * std,
        "mid":   ma,
        "lower": ma - num_std * std,
        "zscore": (df["close"] - ma) / (std + 1e-9),
    }, index=df.index)


def calc_volume_ratio(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """量比（今日成交量 / N日均量）"""
    avg_vol = df["volume"].rolling(window).mean()
    return df["volume"] / (avg_vol + 1e-9)


def calc_funding_cumulative(funding: pd.Series,
                             ohlcv_index: pd.Index) -> pd.Series:
    """
    将8小时资金费率对齐到 OHLCV 时间序列，计算累计资金费率。
    用于：持仓成本计算 + 趋势信号

    资金费率 > 0：多头持续付费 → 看空（空头套利）
    资金费率 < 0：空头持续付费 → 看多（多头套利）
    """
    if funding.empty:
        return pd.Series(0.0, index=ohlcv_index)

    # 重采样到 OHLCV 频率（前向填充）
    aligned = funding.reindex(ohlcv_index, method="ffill").fillna(0)
    return aligned


def calc_oi_change(oi: pd.Series, window: int = 20) -> pd.Series:
    """
    未平仓合约变化率（OI动量）
    OI增加 + 价格上涨 = 趋势强化
    OI增加 + 价格下跌 = 多头被套（空头陷阱）
    """
    if oi.empty:
        return pd.Series(dtype=float)
    return oi.pct_change(window).fillna(0)


def calc_market_regime_score(btc_df: pd.DataFrame) -> pd.Series:
    """
    BTC 市场情绪综合评分 (-1 到 +1)
    正值 = 风险偏好，负值 = 风险规避

    用于 Regime 的辅助信号
    """
    mom_20 = btc_df["close"].pct_change(20)  # 20根K线动量
    rsi    = calc_rsi(btc_df)
    vol    = btc_df["close"].pct_change().rolling(20).std() * np.sqrt(365 * 6)  # 年化

    # 归一化各信号
    mom_score = np.tanh(mom_20 * 5)          # ±1
    rsi_score = (rsi - 50) / 50              # ±1
    vol_score = -np.tanh(vol - 0.5)          # 高波动=负分

    return (0.5 * mom_score + 0.3 * rsi_score + 0.2 * vol_score).fillna(0)
