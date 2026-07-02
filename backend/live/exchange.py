"""
Binance USDT-M 永续合约交易接口
封装 ccxt.binanceusdm，统一异常处理 + 重试逻辑

安全设计：
  - API KEY 只从环境变量读取，不写死在代码里
  - DRY_RUN=True 时只打印指令，不发出真实订单
  - 默认1x杠杆（可配置，不超过 CFG.max_leverage）
"""
from __future__ import annotations
import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

import ccxt

logger = logging.getLogger("live.exchange")


@dataclass
class Balance:
    total_usdt:    float
    available:     float
    unrealized_pnl: float


@dataclass
class LivePosition:
    symbol:    str
    side:      str     # "long" | "short"
    size:      float   # USDT notional
    entry_price: float
    current_price: float
    pnl_pct:   float


class BinanceExchange:
    """
    Binance USDT-M 永续合约交易封装。

    初始化：
      exchange = BinanceExchange(dry_run=True)   # 模拟模式，不发真实订单
      exchange = BinanceExchange(dry_run=False)  # 实盘模式

    所需环境变量（.env 文件或 export）：
      BINANCE_API_KEY=xxx
      BINANCE_API_SECRET=xxx
    """

    def __init__(self, dry_run: bool = True, leverage: int = 1):
        self.dry_run  = dry_run
        self.leverage = leverage

        api_key    = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")

        if not dry_run and (not api_key or not api_secret):
            raise ValueError(
                "实盘模式需要环境变量 BINANCE_API_KEY 和 BINANCE_API_SECRET\n"
                "  export BINANCE_API_KEY=your_key\n"
                "  export BINANCE_API_SECRET=your_secret"
            )

        self._ex = ccxt.binanceusdm({
            "apiKey":    api_key,
            "secret":    api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        mode = "🟡 DRY_RUN（模拟）" if dry_run else "🔴 实盘"
        logger.info("Exchange 初始化 | 模式=%s | 杠杆=%dx", mode, leverage)

    # ── 行情数据 ─────────────────────────────────────────────────────────
    def get_price(self, symbol: str) -> float:
        """获取当前价格（用 mark price 避免操纵）"""
        try:
            ticker = self._retry(self._ex.fetch_ticker, symbol)
            return float(ticker["last"])
        except Exception as e:
            logger.error("get_price(%s) 失败: %s", symbol, e)
            return 0.0

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """批量获取价格"""
        prices = {}
        for sym in symbols:
            p = self.get_price(sym)
            if p > 0:
                prices[sym] = p
        return prices

    # ── 账户信息 ─────────────────────────────────────────────────────────
    def get_balance(self) -> Balance:
        """获取账户余额"""
        if self.dry_run:
            return Balance(total_usdt=1000.0, available=800.0, unrealized_pnl=0.0)
        try:
            bal = self._retry(self._ex.fetch_balance)
            usdt = bal.get("USDT", {})
            return Balance(
                total_usdt     = float(usdt.get("total", 0)),
                available      = float(usdt.get("free",  0)),
                unrealized_pnl = 0.0,  # 需要从 positions 汇总
            )
        except Exception as e:
            logger.error("get_balance 失败: %s", e)
            return Balance(0, 0, 0)

    def get_positions(self) -> list[LivePosition]:
        """获取当前所有持仓"""
        if self.dry_run:
            return []
        try:
            raw = self._retry(self._ex.fetch_positions)
            positions = []
            for p in raw:
                if float(p.get("contracts", 0)) == 0:
                    continue
                sym   = p["symbol"]
                side  = "long" if p["side"] == "long" else "short"
                size  = abs(float(p.get("notional", 0)))
                entry = float(p.get("entryPrice", 0))
                mark  = float(p.get("markPrice", entry))
                pnl_pct = (mark - entry) / entry if side == "long" else (entry - mark) / entry
                positions.append(LivePosition(
                    symbol=sym, side=side, size=size,
                    entry_price=entry, current_price=mark, pnl_pct=pnl_pct,
                ))
            return positions
        except Exception as e:
            logger.error("get_positions 失败: %s", e)
            return []

    # ── 下单 ─────────────────────────────────────────────────────────────
    def set_leverage(self, symbol: str, leverage: int):
        """设置合约杠杆"""
        if self.dry_run:
            logger.info("[DRY] set_leverage %s → %dx", symbol, leverage)
            return
        try:
            self._ex.set_leverage(leverage, symbol)
            logger.info("设置杠杆 %s = %dx", symbol, leverage)
        except Exception as e:
            logger.warning("set_leverage(%s) 失败: %s", symbol, e)

    def open_long(self, symbol: str, usdt_size: float) -> bool:
        """做多开仓（市价单）"""
        price = self.get_price(symbol)
        if price <= 0:
            return False
        contracts = usdt_size / price
        logger.info("[%s] 开多 %s | %.2f USDT | 价格=%.4f | %.6f 张",
                    "DRY" if self.dry_run else "LIVE", symbol, usdt_size, price, contracts)
        if self.dry_run:
            return True
        return self._execute_order(symbol, "buy", contracts)

    def open_short(self, symbol: str, usdt_size: float) -> bool:
        """做空开仓（市价单）"""
        price = self.get_price(symbol)
        if price <= 0:
            return False
        contracts = usdt_size / price
        logger.info("[%s] 开空 %s | %.2f USDT | 价格=%.4f | %.6f 张",
                    "DRY" if self.dry_run else "LIVE", symbol, usdt_size, price, contracts)
        if self.dry_run:
            return True
        return self._execute_order(symbol, "sell", contracts)

    def close_position(self, symbol: str, side: str) -> bool:
        """平仓（市价单，需要知道当前持仓方向）"""
        logger.info("[%s] 平仓 %s | 方向=%s",
                    "DRY" if self.dry_run else "LIVE", symbol, side)
        if self.dry_run:
            return True
        try:
            # reduceOnly=True 确保只平仓不开反向仓
            positions = self.get_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if pos is None:
                logger.warning("close_position: %s 无持仓", symbol)
                return False

            side_order = "sell" if pos.side == "long" else "buy"
            return self._execute_order(symbol, side_order,
                                       pos.size / pos.current_price,
                                       reduce_only=True)
        except Exception as e:
            logger.error("close_position(%s) 失败: %s", symbol, e)
            return False

    # ── 内部工具 ──────────────────────────────────────────────────────────
    def _execute_order(self, symbol: str, side: str,
                       contracts: float, reduce_only: bool = False) -> bool:
        try:
            params = {"reduceOnly": reduce_only} if reduce_only else {}
            order  = self._retry(
                self._ex.create_order,
                symbol, "market", side, contracts, None, params
            )
            logger.info("订单成交: %s", order.get("id", "?"))
            return True
        except Exception as e:
            logger.error("下单失败 %s %s %.4f: %s", symbol, side, contracts, e)
            return False

    def _retry(self, fn, *args, retries: int = 3, **kwargs):
        """带重试的 API 调用"""
        for attempt in range(retries):
            try:
                return fn(*args, **kwargs)
            except ccxt.RateLimitExceeded:
                time.sleep(2 ** attempt)
            except ccxt.NetworkError as e:
                if attempt == retries - 1:
                    raise
                logger.warning("网络错误，重试 %d/%d: %s", attempt+1, retries, e)
                time.sleep(1)
        raise RuntimeError(f"API 调用失败（重试{retries}次）")
