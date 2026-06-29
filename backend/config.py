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
        # 核心大盘：趋势清晰 + OI最大（资金费率套利主战场）
        "BTC/USDT", "ETH/USDT",
        # L1竞争者：独立行情 + 强动量周期
        "SOL/USDT", "BNB/USDT", "AVAX/USDT",
        # DeFi基础设施：走势独立于BTC
        "LINK/USDT",
        # 移除：DOGE（纯情绪）、XRP（法律不稳）、ADA（无动量）
    ])
    timeframe: str = "4h"      # K线周期：1h / 4h / 1d
    spot_or_futures: str = "futures"   # spot / futures

    # ─── Regime 识别（币安四态）─────────────────────────────────────────────
    # 不用 ADX（A股教训：ADX滞后），改用BTC市场结构
    bull_threshold:     float = 0.05   # BTC 20日收益率 > 5% → 牛市
    bear_threshold:     float = -0.10  # BTC 20日收益率 < -10% → 熊市
    vol_crisis:         float = 0.80   # BTC 20日年化波动率 > 80% → 危机（加密市场正常波动高）
    regime_confirm_days: int  = 2

    # ─── Regime → 策略权重 ──────────────────────────────────────────────────
    # (momentum, funding_arb, mean_revert, defensive, max_slots, position_cap)
    # 加密特点：动量IC为正（与A股相反）
    regime_weights: dict = field(default_factory=lambda: {
        "bull":     (0.70, 0.20, 0.05, 0.05, 3, 0.80),  # 牛市：动量主导
        "ranging":  (0.20, 0.50, 0.20, 0.10, 2, 0.50),  # 震荡：资金费率套利
        "bear":     (0.10, 0.30, 0.00, 0.60, 1, 0.20),  # 熊市：谨慎，可做空
        "crisis":   (0.00, 0.10, 0.00, 0.90, 0, 0.05),  # 危机：全防御
    })

    # ─── 动量策略参数 ────────────────────────────────────────────────────────
    mom_lookback:    int   = 20     # 动量计算窗口（K线数量）
    mom_top_n:       int   = 4      # 持仓品种数
    mom_vol_filter:  float = 0.5    # 量比 < 0.5 过滤死水
    mom_max_dd:      float = -0.25  # 买前最大回撤阈值（加密波动大，允许-25%）

    # ─── 资金费率套利参数 ────────────────────────────────────────────────────
    funding_long_threshold:  float = -0.0005  # 资金费率 < -0.05% → 做多（空头付费）
    funding_short_threshold: float =  0.0010  # 资金费率 >  0.10% → 做空（多头付费）
    funding_hold_periods:    int   = 3         # 持有3个资金费率结算周期（24小时）

    # ─── 均值回归参数 ────────────────────────────────────────────────────────
    mr_zscore_entry:  float = -2.0  # Z-score < -2 买入（极端超卖）
    mr_zscore_exit:   float =  0.0  # Z-score 回归0附近止盈
    mr_window:        int   = 20    # 均值计算窗口

    # ─── 仓位管理（第15课：半Kelly + ATR）──────────────────────────────────
    max_positions:   int   = 4      # 最大同时持仓
    max_pos_pct:     float = 0.25   # 单仓最大占总资产25%（初期保守）
    risk_per_trade:  float = 0.02   # 单笔风险预算2%（知识库：Kelly下限）
    leverage:        float = 1.0    # 默认不用杠杆（安全起见）
    max_leverage:    float = 3.0    # 最高杠杆

    # ─── Risk Agent 三层阈值 ─────────────────────────────────────────────────
    dd_warn:    float = 0.08   # 回撤8%警戒（加密波动大，比A股宽松）
    dd_stop:    float = 0.15   # 回撤15%停止新仓
    dd_circuit: float = 0.25   # 回撤25%熔断（加密市场正常大跌）
    circuit_cool_hours: int = 24  # 熔断冷静期（小时，不是天）

    # ─── 止损参数 ─────────────────────────────────────────────────────────
    hard_stop:           float = -0.08   # 硬止损-8%（加密波动大）
    trailing_stop_pct:   float = 0.12   # 追踪止损12%（从高点）
    trailing_stop_min:   float = 0.05   # 启动条件：盈利5%

    # ─── 交易成本 ──────────────────────────────────────────────────────────
    # 币安现货：maker 0.02%，taker 0.04%（远低于A股）
    # 币安合约：maker 0.02%，taker 0.05%
    comm_maker:   float = 0.0002
    comm_taker:   float = 0.0004
    slippage_pct: float = 0.0005   # 滑点估计（流动性好的币种很低）

    # ─── AlphaGPT 强化学习 ─────────────────────────────────────────────────
    alpha_weight: float = 0.0    # 0=不启用，需先训练后再开启


CFG = Config()
