"""
AlphaGPT 加密版训练引擎
REINFORCE 策略梯度 + 加密回测打分
"""
import json
from pathlib import Path

import torch
from torch.distributions import Categorical
from tqdm import tqdm

from .alphagpt import AlphaGPT
from .config import AlphaConfig
from .data_loader import CryptoDataLoader
from .factors import FEATURE_NAMES, NUM_FEATURES
from .vm import StackVM

try:
    from .vocab import FORMULA_VOCAB
except ImportError:
    # 如果原版 vocab 不兼容，用简单版
    class _V:
        operator_offset = NUM_FEATURES
        feature_count   = NUM_FEATURES
        token_names     = list(FEATURE_NAMES) + [f"OP{i}" for i in range(20)]
    FORMULA_VOCAB = _V()

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data"


def formula_to_str(tokens):
    names = FORMULA_VOCAB.token_names
    return " ".join(names[t] if t < len(names) else "?" for t in tokens)


class CryptoAlphaEngine:
    """加密 AlphaGPT：用资金费率 + OI 等特征挖掘 Alpha"""

    def __init__(self, symbols: list[str], timeframe: str,
                 start: str, end: str,
                 train_steps: int = AlphaConfig.TRAIN_STEPS):
        self.train_steps = train_steps
        self.loader = CryptoDataLoader(symbols, timeframe, start, end)
        self.loader.load_data()

        self.model = AlphaGPT().to(AlphaConfig.DEVICE)
        self.opt   = torch.optim.AdamW(self.model.parameters(), lr=1e-3)
        self.vm    = StackVM()
        self.best_score   = -float("inf")
        self.best_formula = None

    def _backtest_score(self, factors: torch.Tensor) -> torch.Tensor:
        """
        简化回测打分：因子对未来收益的 Rank IC
        加密版：考虑做空，不限制方向
        """
        target = self.loader.target_ret   # [N, T]
        N, T   = target.shape

        # Rank IC：因子与未来收益的截面相关系数
        score_list = []
        for t in range(1, T):
            f = factors[:, t]
            r = target[:, t]
            if f.std() < 1e-6 or r.std() < 1e-6:
                continue
            ic = torch.corrcoef(torch.stack([f, r]))[0, 1]
            score_list.append(ic)

        if not score_list:
            return torch.tensor(-1.0, device=AlphaConfig.DEVICE)

        ic_mean = torch.stack(score_list).mean()
        ic_std  = torch.stack(score_list).std() + 1e-8
        icir    = ic_mean / ic_std   # ICIR（比 IC 更稳定的评价指标）
        return icir

    def train(self, early_stop_steps: int = 500):
        dev = AlphaConfig.DEVICE
        bs  = AlphaConfig.BATCH_SIZE
        steps_since_best = 0

        pbar = tqdm(range(self.train_steps), desc="CryptoAlphaGPT")

        for step in pbar:
            inp = torch.zeros((bs, 1), dtype=torch.long, device=dev)
            log_probs, tokens_list = [], []

            for _ in range(AlphaConfig.MAX_FORMULA_LEN):
                logits, _, _ = self.model(inp)
                dist   = Categorical(logits=logits)
                action = dist.sample()
                log_probs.append(dist.log_prob(action))
                tokens_list.append(action)
                inp = torch.cat([inp, action.unsqueeze(1)], dim=1)

            seqs    = torch.stack(tokens_list, dim=1)
            rewards = torch.zeros(bs, device=dev)

            for i in range(bs):
                formula = seqs[i].tolist()
                res = self.vm.execute(formula, self.loader.feat_tensor)
                if res is None or res.std() < 1e-4:
                    rewards[i] = -1.0
                    continue
                icir = self._backtest_score(res)
                rewards[i] = icir

                if icir.item() > self.best_score:
                    self.best_score   = icir.item()
                    self.best_formula = formula
                    steps_since_best  = 0
                    tqdm.write(f"[✓] ICIR={icir:.4f}  {formula_to_str(formula)}")
                    # 立即保存
                    OUTPUT_DIR.mkdir(exist_ok=True)
                    with open(OUTPUT_DIR / "alpha_formula.json", "w") as f:
                        json.dump({
                            "formula":  formula,
                            "icir":     self.best_score,
                            "readable": formula_to_str(formula),
                            "features": list(FEATURE_NAMES),
                        }, f, indent=2)

            adv  = (rewards - rewards.mean()) / (rewards.std() + 1e-5)
            loss = sum(-lp * adv for lp in log_probs)
            loss = loss.mean()
            self.opt.zero_grad(); loss.backward(); self.opt.step()

            steps_since_best += 1
            pbar.set_postfix({"ICIR": f"{rewards.mean():.4f}",
                              "Best": f"{self.best_score:.4f}",
                              "NoImp": steps_since_best})

            if steps_since_best >= early_stop_steps:
                tqdm.write(f"\n⏹ 早停：{early_stop_steps}步无改善，Best ICIR={self.best_score:.4f}")
                break

        return self.best_formula
