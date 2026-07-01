"""
第二轮单变量测试：基于 Test A（移除BTC）继续优化
  D：进一步移除 LTC/USDT（-40% P&L, 17% 胜率的拖累项）
  E：移除 BTC+LTC+DOT（三个一致亏损标的）
  F：硬止损 -0.08 → -0.10（看是否减少噪音触发的假止损）
"""
import sys, copy, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from config import CFG
from backtest.engine import run

BASE_SYMBOLS_NO_BTC = [s for s in CFG.symbols if s != "BTC/USDT"]

def bt(label, **overrides):
    cfg = copy.deepcopy(CFG)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    run(cfg)

# A（对照组，上轮最佳）
bt("A（对照）: 移除BTC  Sharpe=0.630")

# D：移除 BTC + LTC
no_btc_ltc = [s for s in BASE_SYMBOLS_NO_BTC if s != "LTC/USDT"]
bt("Test D: 移除 BTC + LTC", symbols=no_btc_ltc)

# E：移除 BTC + LTC + DOT（3个最差）
no_btc_ltc_dot = [s for s in no_btc_ltc if s not in ("DOT/USDT",)]
bt("Test E: 移除 BTC + LTC + DOT", symbols=no_btc_ltc_dot)

# F：在A的基础上，硬止损 -8% → -10%
bt("Test F: 硬止损 -8% → -10%", symbols=BASE_SYMBOLS_NO_BTC, hard_stop=-0.10)
