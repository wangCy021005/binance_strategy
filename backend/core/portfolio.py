"""
投资组合管理 — 加密版
支持做多/做空（永续合约）
知识库第15课：ATR仓位 + 三层风控
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger("crypto.portfolio")


@dataclass
class Position:
    symbol:      str
    side:        str    # "long" | "short"
    qty:         float  # 合约数量（USDT计价）
    cost:        float  # 平均成本价（USDT）
    high:        float  # 持仓期间最高价（追踪止损用）
    open_time:   str
    strategy:    str
    hold_bars:   int   = 0
    atr_pct:     float = 0.03
    leverage:    float = 1.0   # 实际使用的杠杆倍数
    trail_pct:   float = 0.12  # 该仓位专属追踪止损%（开仓时按 Regime 设定）


class Portfolio:
    COMM = 0.0004  # taker 手续费

    def __init__(self, initial_usdt: float):
        self.initial_usdt = initial_usdt
        self.usdt         = initial_usdt
        self._pos:          dict[str, Position] = {}
        self._trades:       list[dict]          = []
        self._pending_stop: dict[str, str]      = {}

    # ── 开仓 ──────────────────────────────────────────────────────────────
    def open_position(self, symbol: str, side: str, price: float,
                      size_pct: float, total_value: float,
                      timestamp: str, strategy: str,
                      atr_pct: float = 0.03, leverage: float = 1.0,
                      trail_pct: float = 0.12):
        """
        side: "long"（做多）或 "short"（做空）
        size_pct: 占总资产的比例
        """
        notional = total_value * size_pct
        cost      = notional * (1 + self.COMM)
        if cost > self.usdt:
            notional = self.usdt / (1 + self.COMM)
            cost     = self.usdt
        if notional < 10:   # 最小10 USDT
            return

        self.usdt -= cost
        self._pos[symbol] = Position(
            symbol=symbol, side=side,
            qty=notional / price,
            cost=price, high=price,
            open_time=timestamp, strategy=strategy,
            atr_pct=atr_pct, leverage=leverage,
            trail_pct=trail_pct,
        )
        logger.info("【开仓】%s %s  %.4f USDT  价格=%.2f  策略=%s",
                    side, symbol, notional, price, strategy)
        self._trades.append({
            "time": timestamp, "symbol": symbol, "side": f"open_{side}",
            "price": price, "notional": notional, "strategy": strategy,
        })

    def close_position(self, symbol: str, price: float,
                       timestamp: str, reason: str = ""):
        """平仓，计算盈亏"""
        pos = self._pos.pop(symbol, None)
        if pos is None:
            return

        if pos.side == "long":
            price_pct = (price - pos.cost) / pos.cost
        else:  # short
            price_pct = (pos.cost - price) / pos.cost

        # 合约模型：P&L = 保证金 × 价格变化% × 杠杆
        margin   = pos.qty * pos.cost       # 实际占用资金（保证金）
        lev      = max(getattr(pos, 'leverage', 1.0), 1.0)
        pnl_pct  = price_pct * lev          # 杠杆放大后的收益率
        # 防止爆仓（P&L不超过保证金本身）
        pnl_pct  = max(pnl_pct, -1.0)

        fee      = margin * self.COMM * lev  # 手续费按合约面值
        pnl_usdt = margin * pnl_pct - fee
        self.usdt += margin + pnl_usdt       # 归还保证金 + 盈亏

        logger.info("【平仓】%s  %s  盈亏=%.2f%%  原因=%s",
                    pos.side, symbol, pnl_pct*100, reason)
        self._trades.append({
            "time": timestamp, "symbol": symbol,
            "side": f"close_{pos.side}",
            "price": price, "pnl_pct": pnl_pct,
            "pnl_usdt": pnl_usdt, "reason": reason,
        })
        self._pending_stop.pop(symbol, None)

    # ── 价格更新 ──────────────────────────────────────────────────────────
    def tick(self, prices: dict[str, float], timestamp: str):
        """更新最高价 + 持仓时间"""
        for symbol, pos in self._pos.items():
            p = prices.get(symbol, pos.cost)
            if pos.side == "long" and p > pos.high:
                pos.high = p
            elif pos.side == "short" and p < pos.high:
                pos.high = p
            pos.hold_bars += 1

    def check_stops(self, prices: dict[str, float],
                    timestamp: str, cfg) -> None:
        """检查止损条件"""
        for symbol in list(self._pos.keys()):
            pos = self._pos.get(symbol)
            if not pos or pos.hold_bars == 0:
                continue

            price = prices.get(symbol, pos.cost)

            lev = max(getattr(pos, 'leverage', 1.0), 1.0)

            if pos.side == "long":
                price_pct      = (price - pos.cost) / pos.cost
                high_price_pct = (price - pos.high) / pos.high
            else:
                price_pct      = (pos.cost - price) / pos.cost
                high_price_pct = (pos.high - price) / pos.high

            pnl_pct        = price_pct * lev         # 杠杆放大的实际盈亏
            gain_from_high = high_price_pct * lev     # 从最高点的杠杆回撤

            # 硬止损：按价格变动%（price_pct），不按杠杆后P&L
            # 这样5x杠杆下 -8%价格 = -40%保证金损失，符合高风险预期
            if price_pct <= cfg.hard_stop:
                self._pending_stop[symbol] = \
                    f"硬止损价格{price_pct*100:.1f}%(P&L={pnl_pct*100:.1f}%,杠杆{lev:.1f}x)"
                continue

            # 追踪止损：同样基于价格变动（而非杠杆P&L）
            if pos.high != pos.cost:
                high_gain_price = abs(pos.high - pos.cost) / pos.cost
                if high_gain_price >= cfg.trailing_stop_min:
                    if high_price_pct <= -cfg.trailing_stop_pct:
                        self._pending_stop[symbol] = \
                            f"追踪止损价格({high_price_pct*100:.1f}%)"

    def flush_stops(self, prices: dict[str, float], timestamp: str):
        """执行挂起的平仓"""
        for symbol, reason in list(self._pending_stop.items()):
            price = prices.get(symbol, self._pos.get(symbol, None) and self._pos[symbol].cost)
            if price:
                self.close_position(symbol, price, timestamp, reason)

    def value(self, prices: dict[str, float]) -> float:
        """当前总资产（USDT）= 现金 + 所有持仓的保证金 + 未实现盈亏"""
        pos_value = 0.0
        for sym, pos in self._pos.items():
            margin  = pos.qty * pos.cost
            lev     = max(getattr(pos, 'leverage', 1.0), 1.0)
            cur_p   = prices.get(sym, pos.cost)

            if pos.side == "long":
                price_pct = (cur_p - pos.cost) / pos.cost
            else:
                price_pct = (pos.cost - cur_p) / pos.cost

            unrealized = margin * price_pct * lev
            unrealized = max(unrealized, -margin)   # 最多亏完保证金
            pos_value += margin + unrealized

        return self.usdt + pos_value

    @property
    def positions(self) -> dict[str, Position]:
        return self._pos

    @property
    def trades(self) -> list[dict]:
        return self._trades
