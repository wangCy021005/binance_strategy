"""
LSTM Regime Predictor 训练脚本

用法：
  python scripts/train_regime.py
  python scripts/train_regime.py --epochs 200 --lr 0.001

训练策略：
  - 数据: 2022-2025 BTC 日线 + 20只山寨币日线
  - 标签: 未来20日BTC收益 → sigmoid变换到[0,1]（积极度得分）
  - 训练: 2022-2023（730天）
  - 验证: 2024-01~06（180天）
  - 测试: 2024-07~2025-12（550天）

Walk-forward 防过拟合：训练集不能看到验证/测试数据
"""
import sys, argparse, sqlite3, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model_core.regime_predictor import (
    RegimeLSTM, build_features, MODEL_PATH, SEQ_LEN, N_FEATURES
)
from config import DB_PATH, CFG

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("train_regime")


def load_data():
    """从 SQLite 读取 BTC 和山寨币日线收盘价"""
    conn = sqlite3.connect(str(DB_PATH))
    btc = pd.read_sql(
        "SELECT open_time, close FROM ohlcv WHERE symbol='BTCUSDT' AND timeframe='1d' ORDER BY open_time",
        conn
    ).set_index('open_time')['close'].astype(float)

    # 读取20只山寨币（计算各自20日收益率）
    alts = {}
    for sym in CFG.symbols:
        sym_db = sym.replace("/", "")
        df = pd.read_sql(
            f"SELECT open_time, close FROM ohlcv WHERE symbol='{sym_db}' AND timeframe='1d' ORDER BY open_time",
            conn
        ).set_index('open_time')['close'].astype(float)
        alts[sym] = df
    conn.close()
    return btc, alts


def compute_alt_r20(btc_index: pd.Index, alts: dict) -> np.ndarray:
    """
    在 BTC 每个时间点，计算所有山寨币的平均20日收益。
    返回 shape (T, K) 的数组（对齐 BTC 时间戳）。
    """
    T = len(btc_index)
    result = np.full((T, len(alts)), np.nan)

    for j, (sym, ser) in enumerate(alts.items()):
        for i, ts in enumerate(btc_index):
            if ts in ser.index:
                loc = ser.index.get_loc(ts)
                if loc >= 20:
                    r20 = (ser.iloc[loc] - ser.iloc[loc-20]) / ser.iloc[loc-20]
                    result[i, j] = r20
    return result


def make_dataset(btc: pd.Series, alt_r20: np.ndarray,
                 start: str, end: str):
    """
    构建 LSTM 训练/验证/测试集。

    标签: 未来20日BTC收益 → sigmoid(x * 10) 变换到 [0, 1]
    样本: 每个时间点取前30天特征序列，预测接下来20天的积极度标签
    """
    mask  = (btc.index >= start) & (btc.index <= end)
    dates = btc.index[mask]

    btc_arr   = btc.values
    all_dates = btc.index

    # 构建全局特征矩阵
    alt_means = np.nanmean(alt_r20, axis=1)  # 山寨币平均20日收益
    feat_mat  = build_features(btc_arr, alt_r20)  # (T, 9)

    X_list, y_list = [], []

    for ts in dates:
        i = all_dates.get_loc(ts)

        # 需要足够的前后数据
        if i < SEQ_LEN + 120:
            continue
        if i + 20 >= len(btc_arr):
            continue
        if np.any(np.isnan(feat_mat[i-SEQ_LEN+1:i+1])):
            continue

        # 特征序列：[i-SEQ_LEN+1, ..., i]
        seq = feat_mat[i-SEQ_LEN+1:i+1]      # (30, 9)

        # 标签：未来20日BTC收益
        fwd_20 = (btc_arr[i+20] - btc_arr[i]) / btc_arr[i]
        # sigmoid变换：0% → 0.5, +15% → 0.82, -15% → 0.18, +40% → 0.98
        y = float(1 / (1 + np.exp(-fwd_20 * 10)))

        X_list.append(seq)
        y_list.append(y)

    if not X_list:
        return None, None

    X = np.array(X_list, dtype=np.float32)   # (N, 30, 9)
    y = np.array(y_list, dtype=np.float32)   # (N,)
    return X, y


def train(epochs: int = 300, lr: float = 5e-4, batch_size: int = 32,
          hidden_size: int = 32, dropout: float = 0.3):

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    logger.info("设备: %s", device)

    # ── 加载数据 ──────────────────────────────────────────────────────────
    logger.info("加载 BTC + 山寨币数据...")
    btc, alts = load_data()
    alt_r20   = compute_alt_r20(btc.index, alts)

    # ── 构建数据集（walk-forward，不能泄漏）─────────────────────────────
    X_tr, y_tr = make_dataset(btc, alt_r20, "2022-01-01", "2023-12-31")
    X_vl, y_vl = make_dataset(btc, alt_r20, "2024-01-01", "2024-06-30")
    X_te, y_te = make_dataset(btc, alt_r20, "2024-07-01", "2025-12-31")

    logger.info("训练集: %d 样本 | 验证集: %d 样本 | 测试集: %d 样本",
                len(X_tr), len(X_vl) if X_vl is not None else 0,
                len(X_te) if X_te is not None else 0)

    # ── DataLoader ────────────────────────────────────────────────────────
    def to_loader(X, y, shuffle=True):
        ds = TensorDataset(torch.tensor(X), torch.tensor(y))
        return DataLoader(ds, batch_size=batch_size, shuffle=shuffle)

    tr_loader = to_loader(X_tr, y_tr, shuffle=True)
    vl_loader = to_loader(X_vl, y_vl, shuffle=False) if X_vl is not None else None

    # ── 模型 ──────────────────────────────────────────────────────────────
    model = RegimeLSTM(N_FEATURES, hidden_size=hidden_size, n_layers=2, dropout=dropout)
    model = model.to(device)
    opt   = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=20, factor=0.5)
    loss_fn = nn.MSELoss()

    # ── 训练循环 ──────────────────────────────────────────────────────────
    best_val_loss = float('inf')
    best_state    = None

    logger.info("开始训练 %d epochs...", epochs)
    for epoch in range(1, epochs + 1):
        # 训练
        model.train()
        tr_loss = 0.0
        for xb, yb in tr_loader:
            xb, yb = xb.to(device), yb.to(device)
            pred   = model(xb)
            loss   = loss_fn(pred, yb)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tr_loss += loss.item() * len(xb)
        tr_loss /= len(X_tr)

        # 验证
        if vl_loader is not None:
            model.eval()
            vl_loss = 0.0
            with torch.no_grad():
                for xb, yb in vl_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    vl_loss += loss_fn(model(xb), yb).item() * len(xb)
            vl_loss /= len(X_vl)
            sched.step(vl_loss)

            if vl_loss < best_val_loss:
                best_val_loss = vl_loss
                best_state    = {k: v.clone() for k, v in model.state_dict().items()}

            if epoch % 50 == 0:
                logger.info("Epoch %4d | tr=%.4f | val=%.4f | best=%.4f",
                            epoch, tr_loss, vl_loss, best_val_loss)
        else:
            if epoch % 50 == 0:
                logger.info("Epoch %4d | tr=%.4f", epoch, tr_loss)

    # ── 保存最优模型 ──────────────────────────────────────────────────────
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    torch.save(model.state_dict(), str(MODEL_PATH))
    logger.info("模型已保存: %s", MODEL_PATH)

    # ── 测试集评估 ────────────────────────────────────────────────────────
    if X_te is not None and len(X_te) > 0:
        evaluate(model, X_te, y_te, "测试集 (2024-07~2025-12)", btc, alt_r20, device)

    # ── 对比规则法 ────────────────────────────────────────────────────────
    compare_with_rule(model, btc, alt_r20, device)


def evaluate(model, X, y, name, btc, alt_r20, device):
    """计算 MSE、相关系数、分类准确率"""
    model.eval()
    with torch.no_grad():
        pred = model(torch.tensor(X).to(device)).cpu().numpy()

    y_np = y
    mse  = float(np.mean((pred - y_np)**2))
    corr = float(np.corrcoef(pred, y_np)[0, 1])

    # 分类准确率：预测>0.5 对应 实际>0.5（即预测是否应该积极）
    acc = float(np.mean((pred > 0.5) == (y_np > 0.5)))

    logger.info("%s: MSE=%.4f  Corr=%.3f  分类准确率=%.1f%%", name, mse, corr, acc*100)
    return corr


def compare_with_rule(model, btc: pd.Series, alt_r20: np.ndarray, device: str):
    """对比 ML 预测 vs 规则法在每年的积极度分布"""
    logger.info("\n── ML vs 规则法 积极度对比 ──")

    feat_mat = build_features(btc.values, alt_r20)
    model.eval()

    from model_core.regime_predictor import predict_score, score_to_regime_params

    by_year = {}
    for i, ts in enumerate(btc.index):
        if i < SEQ_LEN + 120:
            continue
        year = ts[:4]

        # ML 分数
        seq = feat_mat[i-SEQ_LEN+1:i+1]
        if np.any(np.isnan(seq)):
            continue
        ml_score = predict_score(model, feat_mat[:i+1], device)

        # 规则法分数（基于 BTC 20日收益）
        if i >= 20:
            r20 = (btc.values[i] - btc.values[i-20]) / btc.values[i-20]
            if r20 > 0.08:
                rule_score = 0.85
            elif r20 < -0.12:
                rule_score = 0.15
            else:
                rule_score = 0.45
        else:
            rule_score = 0.45

        by_year.setdefault(year, {'ml': [], 'rule': []})
        by_year[year]['ml'].append(ml_score)
        by_year[year]['rule'].append(rule_score)

    for y in sorted(by_year):
        ml_avg   = np.mean(by_year[y]['ml'])
        rule_avg = np.mean(by_year[y]['rule'])
        logger.info("  %s: ML=%.2f | 规则法=%.2f  （差值%.2f）",
                    y, ml_avg, rule_avg, ml_avg - rule_avg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs",      type=int,   default=300)
    parser.add_argument("--lr",          type=float, default=5e-4)
    parser.add_argument("--hidden",      type=int,   default=32)
    parser.add_argument("--dropout",     type=float, default=0.3)
    parser.add_argument("--batch_size",  type=int,   default=32)
    args = parser.parse_args()

    train(epochs=args.epochs, lr=args.lr,
          hidden_size=args.hidden, dropout=args.dropout,
          batch_size=args.batch_size)
