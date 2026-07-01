"""
LSTM Regime Predictor
用历史市场特征序列预测"当前应该多积极"的连续得分 [0, 1]

突破规则法局限：
  规则法无法区分"2023初 BTC 17k 时5%涨幅=复苏" vs "2024末 100k 时5%=高位震荡"
  LSTM 通过30天历史特征序列，学习市场结构和上下文

积极度分数映射：
  0.0  → crisis / 全仓现金
  0.3  → ranging / 保守（50%仓）
  0.6  → soft_bull / 中等积极（70%仓）
  0.9+ → bull / 满仓（90%仓）
"""
from __future__ import annotations
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

MODEL_PATH = Path(__file__).parent.parent.parent / "data" / "regime_lstm.pt"
SEQ_LEN    = 30     # 30 天历史窗口
N_FEATURES = 9      # 特征数量（见 build_features）


class RegimeLSTM(nn.Module):
    """2层 LSTM + 线性输出，预测积极度得分"""

    def __init__(self, n_features: int = N_FEATURES,
                 hidden_size: int = 32, n_layers: int = 2,
                 dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=n_layers,
            batch_first=True,
            dropout=dropout if n_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden_size, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),   # 输出在 [0, 1]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq_len, features) → (batch,) score"""
        out, _ = self.lstm(x)
        last    = out[:, -1, :]          # 取最后一步
        return self.head(last).squeeze(-1)


def build_features(btc_close: np.ndarray,
                   alt_returns: np.ndarray | None = None) -> np.ndarray:
    """
    构建特征矩阵，每行是一个时间点的9维特征。

    btc_close : shape (T,) BTC 收盘价序列
    alt_returns: shape (T, K) 山寨币各自20日收益（可选）
    返回      : shape (T, 9) 特征矩阵（前 max_lookback 行为 NaN）

    特征说明：
      0: BTC 5日收益
      1: BTC 20日收益
      2: BTC 60日收益
      3: BTC 90日收益
      4: BTC 20日年化波动率
      5: BTC 相对120日均线偏离（close/SMA120 - 1）
      6: 动量加速度（5日收益 - 前5日的5日收益）
      7: 从最近60日高点最大回撤
      8: 山寨币平均20日收益（无则用 BTC 20日收益代替）
    """
    T = len(btc_close)
    X = np.full((T, 9), np.nan)

    for i in range(120, T):   # 需要至少120天数据
        c = btc_close
        # 基础收益
        r5  = (c[i] - c[i-5])  / c[i-5]   if i >= 5  else 0.0
        r20 = (c[i] - c[i-20]) / c[i-20]  if i >= 20 else 0.0
        r60 = (c[i] - c[i-60]) / c[i-60]  if i >= 60 else 0.0
        r90 = (c[i] - c[i-90]) / c[i-90]  if i >= 90 else 0.0

        # 20日年化波动率
        rets_20 = np.diff(np.log(c[max(0,i-20):i+1]))
        vol20   = float(np.std(rets_20) * np.sqrt(365)) if len(rets_20) >= 5 else 0.15

        # 相对120日均线
        sma120  = float(np.mean(c[i-120:i]))
        sma_rel = (c[i] - sma120) / sma120

        # 动量加速度（近5日 vs 上一个5日）
        r5_prev = (c[i-5] - c[i-10]) / c[i-10] if i >= 10 else 0.0
        accel   = r5 - r5_prev

        # 从60日高点最大回撤
        high60  = np.max(c[max(0,i-60):i+1])
        dd60    = (c[i] - high60) / high60

        # 山寨币平均20日收益
        if alt_returns is not None and i < len(alt_returns):
            alt_r20 = float(np.nanmean(alt_returns[i]))
        else:
            alt_r20 = r20   # fallback: BTC 本身

        X[i] = [r5, r20, r60, r90, vol20, sma_rel, accel, dd60, alt_r20]

    # 归一化（Robust: 减中位数、除IQR，截断到±3）
    valid = ~np.any(np.isnan(X), axis=1)
    if valid.sum() > 10:
        med = np.nanmedian(X[valid], axis=0)
        iqr = np.nanpercentile(X[valid], 75, axis=0) - np.nanpercentile(X[valid], 25, axis=0)
        iqr = np.where(iqr < 1e-6, 1.0, iqr)
        X   = (X - med) / iqr
        X   = np.clip(X, -3, 3)
    return X.astype(np.float32)


def score_to_regime_params(score: float) -> dict:
    """
    将 LSTM 积极度得分 [0,1] 转换为 Regime 参数。
    代替规则法的硬阈值判断。
    """
    if score < 0.15:    # crisis
        return dict(regime="crisis",   max_slots=0, position_cap=0.05,
                    mom_weight=0.00, funding_weight=0.05)
    elif score < 0.35:  # bear/defensive
        return dict(regime="bear",     max_slots=2, position_cap=0.30,
                    mom_weight=0.10, funding_weight=0.30)
    elif score < 0.55:  # ranging
        return dict(regime="ranging",  max_slots=3, position_cap=0.50,
                    mom_weight=0.30, funding_weight=0.50)
    elif score < 0.75:  # soft bull（规则法没有这个档）
        return dict(regime="trending", max_slots=3, position_cap=0.70,
                    mom_weight=0.60, funding_weight=0.25)
    else:               # strong bull
        return dict(regime="bull",     max_slots=4, position_cap=0.90,
                    mom_weight=0.85, funding_weight=0.10)


def load_model(device: str = "cpu") -> RegimeLSTM | None:
    """加载已训练模型，不存在则返回 None"""
    if not MODEL_PATH.exists():
        return None
    try:
        m = RegimeLSTM()
        m.load_state_dict(torch.load(MODEL_PATH, map_location=device))
        m.eval()
        return m
    except Exception as e:
        print(f"[regime_predictor] 模型加载失败: {e}")
        return None


def predict_score(model: RegimeLSTM, features: np.ndarray,
                  device: str = "cpu") -> float:
    """
    对单个时间点预测积极度分数。
    features: shape (T, 9) 历史特征序列（当前时刻是最后一行）
    """
    if features.shape[0] < SEQ_LEN:
        return 0.5   # 数据不足，返回中性

    seq = features[-SEQ_LEN:]              # 取最近30天
    if np.any(np.isnan(seq)):
        return 0.5

    x = torch.tensor(seq, dtype=torch.float32).unsqueeze(0).to(device)
    with torch.no_grad():
        score = model(x).item()
    return float(score)
