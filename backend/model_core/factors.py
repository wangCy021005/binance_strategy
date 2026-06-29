"""
AlphaGPT 加密版特征工程
基于原始 OHLCV + 资金费率 + 未平仓合约，生成因子张量。

特征集（8个，比原版Meme特征更适合 Binance 合约）：
  0. RET        — 对数收益率
  1. MOM20      — 20周期动量（加密IC+，与A股相反）
  2. PRESSURE   — 收盘价在高低价区间中的位置（买卖力度）
  3. VOL_RATIO  — 量比（今日/20日均量）
  4. HL_RANGE   — 振幅（高低价差/收盘价）
  5. FUNDING    — 资金费率（永续合约特有Alpha）
  6. RSI_NORM   — RSI归一化到(-1, +1)
  7. VOL_TREND  — 成交量趋势（今/昨量比）
"""
import torch


FEATURE_NAMES = ("RET", "MOM20", "PRESSURE", "VOL_RATIO",
                 "HL_RANGE", "FUNDING", "RSI_NORM", "VOL_TREND")
NUM_FEATURES = len(FEATURE_NAMES)


def _robust_norm(x: torch.Tensor) -> torch.Tensor:
    med = x.median(dim=-1, keepdim=True).values
    mad = (x - med).abs().median(dim=-1, keepdim=True).values
    return torch.clamp((x - med) / (mad + 1e-8), -5.0, 5.0)


def _rolling_mean(x: torch.Tensor, window: int) -> torch.Tensor:
    N, T = x.shape
    result = torch.zeros_like(x)
    for t in range(T):
        start = max(0, t - window + 1)
        result[:, t] = x[:, start:t+1].mean(dim=1)
    return result


def compute_features(raw: dict, device: str = "cpu") -> torch.Tensor:
    """
    raw: {
        'open': [N, T], 'high': [N, T], 'low': [N, T],
        'close': [N, T], 'volume': [N, T],
        'funding': [N, T],   # 资金费率（无则全0）
    }
    返回 [N, NUM_FEATURES, T]
    """
    close   = raw['close']
    open_   = raw['open']
    high    = raw['high']
    low     = raw['low']
    volume  = raw['volume']
    funding = raw.get('funding', torch.zeros_like(close))

    N, T = close.shape

    # ── 0. 对数收益率 ────────────────────────────────────────────────────
    ret = torch.zeros(N, T, device=close.device)
    ret[:, 1:] = torch.log((close[:, 1:] + 1e-9) / (close[:, :-1] + 1e-9))

    # ── 1. 20周期动量 ─────────────────────────────────────────────────────
    mom20 = torch.zeros(N, T, device=close.device)
    mom20[:, 20:] = torch.log((close[:, 20:] + 1e-9) / (close[:, :-20] + 1e-9))

    # ── 2. 买卖压力（收盘在高低区间的位置）────────────────────────────────
    pressure = (close - low) / (high - low + 1e-9) - 0.5   # -0.5到+0.5

    # ── 3. 量比 ──────────────────────────────────────────────────────────
    vol_ma20  = _rolling_mean(volume, 20)
    vol_ratio = volume / (vol_ma20 + 1e-9)

    # ── 4. 振幅 ──────────────────────────────────────────────────────────
    hl_range = (high - low) / (close + 1e-9)

    # ── 5. 资金费率（合约特有）──────────────────────────────────────────
    # 直接使用，单位为小数（如0.001=0.1%），有意义的量级
    # 已经是有量纲的数，不需要robust_norm，用tanh压缩
    funding_scaled = torch.tanh(funding * 100)  # 0.1% → tanh(10) ≈ 1.0

    # ── 6. RSI 归一化 ─────────────────────────────────────────────────────
    delta = ret
    gain  = torch.relu(delta)
    loss  = torch.relu(-delta)
    gain_ma = _rolling_mean(gain, 14)
    loss_ma = _rolling_mean(loss, 14)
    rs      = gain_ma / (loss_ma + 1e-9)
    rsi     = 100 - 100 / (1 + rs)
    rsi_norm = (rsi - 50) / 50   # -1到+1

    # ── 7. 成交量趋势 ────────────────────────────────────────────────────
    vol_trend = torch.zeros(N, T, device=close.device)
    vol_trend[:, 1:] = torch.log((volume[:, 1:] + 1e-9) / (volume[:, :-1] + 1e-9))

    # ── 组合并标准化 ─────────────────────────────────────────────────────
    feats = [ret, mom20, pressure, vol_ratio, hl_range,
             funding_scaled, rsi_norm, vol_trend]
    feats = [torch.nan_to_num(f, nan=0.0, posinf=0.0, neginf=0.0) for f in feats]

    feat_tensor = torch.stack(feats, dim=1)   # [N, 8, T]

    # robust_norm 对每个特征（跳过资金费率和RSI，已处理过）
    for i in [0, 1, 2, 3, 4, 7]:
        feat_tensor[:, i, :] = _robust_norm(feat_tensor[:, i, :])

    return feat_tensor
