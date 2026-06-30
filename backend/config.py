"""
币安量化交易系统 — 全局参数配置
知识库依据：第15课（仓位管理）、第12课（Regime识别）、第21课（架构）
"""
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent
PROJECT_ROOT = BACKEND_ROOT.parent
DB_PATH      = PROJECT_ROOT / "cache_db" / "crypto_data.db"
DASH_DIR     = PROJECT_ROOT / "data"
LOGS_DIR     = PROJECT_ROOT / "logs"

for _d in [DASH_DIR, LOGS_DIR, DB_PATH.parent]:
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    # ─── 回测区间 ────────────────────────────────────────────────────────────
    start: str = "2022-01-01"
    end:   str = "2025-12-31"
    cash:  float = 10_000.0    # USDT 初始资金

    # ─── 交易品种 ────────────────────────────────────────────────────────────
    symbols: list = field(default_factory=lambda: [
        # 核心大盘
        "BTC/USDT", "ETH/USDT",
        # 高Beta L1：牛市弹性最强
        "SOL/USDT", "AVAX/USDT",
        # L2代币：生态扩张期高Beta
        "ARB/USDT", "OP/USDT",
        # DeFi/基础设施
        "LINK/USDT", "NEAR/USDT",
        # 保留BNB（资金费率套利）
        "BNB/USDT",
    ])
    timeframe: str = "4h"      # K线周期：1h / 4h / 1d
    spot_or_futures: str = "futures"   # spot / futures

    # ─── Regime 识别（币安四态）─────────────────────────────────────────────
    # 不用 ADX（A股教训：ADX滞后），改用BTC市场结构
    bull_threshold:     float = 0.08   # fix-004: 提高到8%（减少假牛市信号）
    bear_threshold:     float = -0.15  # fix-004: 降低到-15%（减少假熊市信号）
    vol_crisis:         float = 1.00   # fix-004: 提到100%（加密正常波动60-80%年化）
    regime_confirm_days: int  = 18   # fix-004: 3天×6根=18根4h（原2根=8小时太短）

    # ─── Regime → 策略权重路由（含杠杆）────────────────────────────────────
    # (momentum, funding_arb, mean_revert, defensive, max_slots, pos_cap, leverage)
    # pos_cap: 实际仓位上限（资产%，不含杠杆）
    # leverage: 该状态下允许的最大杠杆倍数（用户要求不超过10x）
    regime_weights: dict = field(default_factory=lambda: {
        # 牛市：满仓+中等杠杆，动量策略主导
        "bull":     (0.85, 0.10, 0.00, 0.05, 4, 0.40, 1.0),
        # 震荡：半仓+低杠杆，资金费率套利为主
        "ranging":  (0.30, 0.50, 0.10, 0.10, 3, 0.25, 1.0),
        # 熊市：轻仓做空+中等杠杆
        "bear":     (0.10, 0.30, 0.00, 0.60, 2, 0.15, 1.0),
        # 危机：全防御，不开新仓
        "crisis":   (0.00, 0.05, 0.00, 0.95, 0, 0.05, 1.0),
    })

    # ─── 动量策略参数 ────────────────────────────────────────────────────────
    mom_lookback:    int   = 20     # 动量计算窗口（K线数量，实际用mom_*_bars）
    mom_short_bars:  int   = 42    # fix-003: 短期动量（7天×6根/天）
    mom_mid_bars:    int   = 126   # fix-003: 中期动量（21天）
    mom_long_bars:   int   = 252   # fix-003: 长期动量（42天）
    mom_top_n:       int   = 4      # 持仓品种数
    mom_vol_filter:  float = 0.3    # fix-003: 量比过滤（修复硬编码，同步到代码）
    mom_max_dd:      float = -0.25  # 买前最大回撤阈值（加密波动大，允许-25%）

    # ─── 资金费率套利参数 ────────────────────────────────────────────────────
    funding_long_threshold:  float = -0.0005  # 资金费率 < -0.05% → 做多（空头付费）
    funding_short_threshold: float =  0.0010  # 资金费率 >  0.10% → 做空（多头付费）
    funding_hold_periods:    int   = 3         # 持有3个资金费率结算周期（24小时）

    # ─── 均值回归参数 ────────────────────────────────────────────────────────
    mr_zscore_entry:  float = -2.0  # Z-score < -2 买入（极端超卖）
    mr_zscore_exit:   float =  0.0  # Z-score 回归0附近止盈
    mr_window:        int   = 20    # 均值计算窗口

    # ─── 仓位管理（动态杠杆，用户要求：满仓+最高10x）────────────────────────
    max_positions:   int   = 4      # 最大同时持仓
    max_pos_pct:     float = 0.08   # fix-002: 半Kelly上限（胜率39%对应7-8%）
    risk_per_trade:  float = 0.02   # 单笔风险预算2%（知识库：Kelly下限）
    max_leverage:    float = 10.0   # 全局杠杆上限（用户设定）
    # 杠杆止损：杠杆越高止损越紧（防止爆仓）
    # 实际止损 = hard_stop / leverage，保证损失不超过本金的 hard_stop%
    leverage_liq_buffer: float = 0.80  # 强平缓冲（保留80%保证金时止损）

    # ─── Risk Agent 三层阈值 ─────────────────────────────────────────────────
    dd_warn:    float = 0.08   # 回撤8%警戒（加密波动大，比A股宽松）
    dd_stop:    float = 0.15   # 回撤15%停止新仓
    dd_circuit: float = 0.25   # 回撤25%熔断（加密市场正常大跌）
    circuit_cool_hours: int = 24  # 熔断冷静期（小时，不是天）

    # ─── 止损参数 ─────────────────────────────────────────────────────────
    hard_stop:           float = -0.08   # 硬止损-8%（加密波动大）
    trailing_stop_pct:   float = 0.20   # fix-005: 放宽到20%（加密正常回调15-20%）
    trailing_stop_min:   float = 0.10   # fix-005: 提高到10%（避免过早锁定利润）

    # ─── 交易成本 ──────────────────────────────────────────────────────────
    # 币安现货：maker 0.02%，taker 0.04%（远低于A股）
    # 币安合约：maker 0.02%，taker 0.05%
    comm_maker:   float = 0.0002
    comm_taker:   float = 0.0004
    slippage_pct: float = 0.0005   # 滑点估计（流动性好的币种很低）

    # ─── AlphaGPT 因子 ────────────────────────────────────────────────────
    # 公式：HL_RANGE GATE MAX3 MIN3×4 ABS VOL_RATIO GATE MUL MAX3
    # 含义：放量大波动因子（振幅×量比的门控乘积），ICIR=3.53
    alpha_factor_weight: float = 0.30   # Alpha因子权重（0=不启用，0.30=推荐）

    # ─── AlphaGPT 强化学习 ─────────────────────────────────────────────────
    alpha_weight: float = 0.0    # 0=不启用，需先训练后再开启


CFG = Config()
