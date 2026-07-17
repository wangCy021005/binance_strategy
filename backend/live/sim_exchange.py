"""
模拟交易所 — 真实跟踪持仓盈亏
替代 DRY RUN 模式写死的 1000 USDT

核心功能：
  1. 持仓持久化到 data/sim_account.json
  2. 每天拉实时价格更新盈亏
  3. 信号触发开仓 / 止损触发平仓
  4. 记录净值曲线（Dashboard 可展示）
  5. 计入手续费 + 资金费率成本

不用真实 API Key，只用 ccxt 拉公共行情。
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import ccxt

logger = logging.getLogger("live.sim")

STATE_FILE = Path(__file__).parent.parent.parent / "data" / "sim_account.json"

# 模拟交易成本
COMM_RATE   = 0.0004   # 0.04% taker 手续费
FUNDING_8H = 0.0001    # 资金费率均值（每8h，简化为固定）


class SimExchange:
    """模拟交易所，持久化持仓和净值"""

    def __init__(self, initial_cash: float = 1000.0):
        self._ex = ccxt.binance({"enableRateLimit": True,
                                  "options": {"fetchMarkets": ["spot"]}})
        self.initial = initial_cash
        self.state = self._load()

    # ── 状态持久化 ─────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        # 首次运行：初始化
        return {
            "cash":           self.initial,
            "initial_cash":   self.initial,
            "positions":      {},          # {symbol: {side, qty, entry, high, open_time}}
            "trades":         [],
            "equity_history": [],          # [{time, nav, cash, positions_value}]
            "last_update":    "",
        }

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))

    # ── 实时行情 ───────────────────────────────────────────────────────────
    def get_price(self, symbol: str) -> float:
        try:
            t = self._ex.fetch_ticker(symbol)
            return float(t["last"])
        except Exception as e:
            logger.warning("get_price(%s) 失败: %s", symbol, e)
            return 0.0

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        prices = {}
        for s in symbols:
            p = self.get_price(s)
            if p > 0:
                prices[s] = p
        return prices

    # ── 账户查询 ───────────────────────────────────────────────────────────
    def get_balance(self, prices: dict = None):
        """返回 {cash, positions_pnl, total}
        total = cash（未占用）+ 每个持仓的（保证金 + 浮盈亏）
        prices 为空时用 entry 作 fallback（P&L≈0，但保证金算对）
        """
        cash = self.state["cash"]
        pos_pnl = 0.0
        pos_margin = 0.0
        prices = prices or {}
        for sym, pos in self.state["positions"].items():
            price = prices.get(sym) or pos["entry"]
            margin = pos["qty"] * pos["entry"]
            pos_margin += margin
            if pos["side"] == "long":
                pos_pnl += pos["qty"] * (price - pos["entry"])
            else:
                pos_pnl += pos["qty"] * (pos["entry"] - price)
        total = cash + pos_margin + pos_pnl
        return {"cash": cash, "positions_pnl": pos_pnl, "total": total}

    def get_positions(self) -> list[dict]:
        """返回当前持仓列表"""
        result = []
        for sym, pos in self.state["positions"].items():
            result.append({
                "symbol":      sym,
                "side":        pos["side"],
                "qty":         pos["qty"],
                "entry_price": pos["entry"],
                "high":        pos.get("high", pos["entry"]),
                "open_time":   pos.get("open_time", ""),
                "strategy":    pos.get("strategy", ""),
            })
        return result

    # ── 开仓 ───────────────────────────────────────────────────────────────
    def open_position(self, symbol: str, side: str, usdt_size: float,
                       price: float, strategy: str = "") -> bool:
        """开仓（扣手续费）"""
        if price <= 0:
            return False
        if symbol in self.state["positions"]:
            logger.info("[SIM] %s 已有持仓，跳过", symbol)
            return False

        # 手续费
        fee = usdt_size * COMM_RATE
        cost = usdt_size + fee
        if cost > self.state["cash"]:
            logger.warning("[SIM] 资金不足: 需要 %.2f, 可用 %.2f", cost, self.state["cash"])
            return False

        self.state["cash"] -= cost
        qty = usdt_size / price
        self.state["positions"][symbol] = {
            "side":      side,
            "qty":       qty,
            "entry":     price,
            "high":      price,
            "open_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "strategy":  strategy,
        }
        logger.info("[SIM] 开%s %s | qty=%.4f @ %.4f | 手续费 %.2f",
                    side, symbol, qty, price, fee)
        self._save()
        return True

    def open_long(self, symbol, usdt, price=None):
        p = price or self.get_price(symbol)
        return self.open_position(symbol, "long", usdt, p)

    def open_short(self, symbol, usdt, price=None):
        p = price or self.get_price(symbol)
        return self.open_position(symbol, "short", usdt, p)

    # ── 平仓 ───────────────────────────────────────────────────────────────
    def close_position(self, symbol: str, price: float = None,
                        reason: str = "") -> bool:
        """平仓，记录交易"""
        if symbol not in self.state["positions"]:
            return False
        p = price or self.get_price(symbol)
        if p <= 0:
            return False

        pos = self.state["positions"].pop(symbol)
        # 计算 P&L
        if pos["side"] == "long":
            pnl = pos["qty"] * (p - pos["entry"])
        else:
            pnl = pos["qty"] * (pos["entry"] - p)

        # 保证金返还 + P&L
        margin = pos["qty"] * pos["entry"]
        fee = margin * COMM_RATE
        self.state["cash"] += margin + pnl - fee

        # 记录交易
        pnl_pct = pnl / margin * 100 if margin else 0
        trade = {
            "time":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol":    symbol,
            "side":      f"close_{pos['side']}",
            "entry":     pos["entry"],
            "exit":      p,
            "pnl":       round(pnl, 4),
            "pnl_pct":   round(pnl_pct, 2),
            "reason":    reason or "signal",
            "strategy":  pos.get("strategy", ""),
        }
        self.state["trades"].append(trade)
        logger.info("[SIM] 平%s %s | P&L=%.2f USDT (%.1f%%) | %s",
                    pos["side"], symbol, pnl, pnl_pct, reason)
        self._save()
        return True

    # ── 止损检查 ───────────────────────────────────────────────────────────
    def check_stops(self, prices: dict, hard_stop: float = -0.08,
                    trailing_pct: float = 0.12,
                    trailing_min: float = 0.05) -> list[str]:
        """
        检查硬止损和追踪止损
        返回触发的 symbol 列表（已平仓）
        """
        closed = []
        for sym in list(self.state["positions"].keys()):
            pos = self.state["positions"][sym]
            price = prices.get(sym)
            if not price:
                continue

            # 更新最高价
            if pos["side"] == "long" and price > pos.get("high", pos["entry"]):
                pos["high"] = price
            elif pos["side"] == "short" and price < pos.get("high", pos["entry"]):
                pos["high"] = price

            # 价格变动%（相对开仓价）
            if pos["side"] == "long":
                price_pct = (price - pos["entry"]) / pos["entry"]
                high_pct  = (price - pos["high"]) / pos["high"]
            else:
                price_pct = (pos["entry"] - price) / pos["entry"]
                high_pct  = (pos["high"] - price) / pos["high"]

            # 硬止损
            if price_pct <= hard_stop:
                self.close_position(sym, price, f"硬止损 {price_pct*100:.1f}%")
                closed.append(sym)
                continue

            # 追踪止损（从高点回撤 trailing_pct）
            high_gain = abs(pos["high"] - pos["entry"]) / pos["entry"]
            if high_gain >= trailing_min and high_pct <= -trailing_pct:
                self.close_position(sym, price,
                                    f"追踪止损 {high_pct*100:.1f}%")
                closed.append(sym)
        return closed

    # ── 资金费率结算（持仓过夜成本）────────────────────────────────────────
    def settle_funding(self, prices: dict):
        """每天结算一次资金费率（简化：每仓扣 3 × FUNDING_8H）"""
        cost = 0.0
        for sym, pos in self.state["positions"].items():
            margin = pos["qty"] * pos["entry"]
            cost += margin * FUNDING_8H * 3   # 24h = 3次结算
        if cost > 0:
            self.state["cash"] -= cost
            logger.info("[SIM] 资金费率成本: %.2f USDT", cost)

    # ── 净值记录 ────────────────────────────────────────────────────────────
    def record_equity(self, prices: dict = None):
        """记录当日净值到历史（prices 为空时补拉实时价格）"""
        prices = prices or {}
        # 如果传进来的 prices 不全，补拉持仓的价格
        for sym in self.state["positions"]:
            if sym not in prices:
                p = self.get_price(sym)
                if p > 0:
                    prices[sym] = p

        bal = self.get_balance(prices)
        nav = bal["total"] / self.state["initial_cash"]
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.state["equity_history"].append({
            "time":  ts,
            "nav":   round(nav, 4),
            "cash":  round(bal["cash"], 2),
            "total": round(bal["total"], 2),
        })
        # 保留最近 500 天
        self.state["equity_history"] = self.state["equity_history"][-500:]
        self.state["last_update"] = ts
        self._save()
        return nav

    def get_stats(self):
        """返回模拟账户统计（给 Dashboard 用）"""
        hist = self.state.get("equity_history", [])
        trades = self.state.get("trades", [])
        if not hist:
            return {"nav": 1.0, "total_return": 0, "total_trades": 0}

        nav = hist[-1]["nav"]
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        return {
            "nav":          nav,
            "total_return": (nav - 1) * 100,
            "cash":         self.state["cash"],
            "positions":    len(self.state["positions"]),
            "total_trades": len(trades),
            "win_rate":     len(wins) / len(trades) if trades else 0,
        }
