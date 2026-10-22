"""
Binance USDT-M 永续合约交易接口
封装 ccxt.binanceusdm；只读请求可重试，订单提交不盲目重试

安全设计：
  - API KEY 只从环境变量读取，不写死在代码里
  - DRY_RUN=True 时只打印指令，不发出真实订单
  - 默认1x杠杆（可配置，不超过 CFG.max_leverage）
"""
from __future__ import annotations
import os
import hashlib
import time
import logging
import math
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
    contracts: float = 0.0
    hedged: bool = False


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
        self.account_fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:16]

        if not dry_run and (not api_key or not api_secret):
            raise ValueError(
                "实盘模式需要环境变量 BINANCE_API_KEY 和 BINANCE_API_SECRET\n"
                "  export BINANCE_API_KEY=your_key\n"
                "  export BINANCE_API_SECRET=your_secret"
            )

        # 代理支持（国内网络走本地代理访问币安 API，.env 配 PROXY_URL 可选）
        proxy_url = os.environ.get("PROXY_URL", "")
        ex_config = {
            "apiKey":    api_key,
            "secret":    api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        if proxy_url:
            ex_config["proxies"] = {
                "http":  proxy_url,
                "https": proxy_url,
            }
            logger.info("使用代理: %s", proxy_url)

        self._ex = ccxt.binanceusdm(ex_config)

        mode = "🟡 DRY_RUN（模拟）" if dry_run else "🔴 实盘"
        logger.info("Exchange 初始化 | 模式=%s | 杠杆=%dx", mode, leverage)

    # ── 行情数据 ─────────────────────────────────────────────────────────
    def get_price(self, symbol: str) -> float:
        """获取最新成交价；日线止损另用已收盘价格确认。"""
        try:
            ticker = self._retry(self._ex.fetch_ticker, self._contract_symbol(symbol))
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
            raise

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
                sym   = p["symbol"].removesuffix(":USDT")
                side  = p["side"]
                size  = abs(float(p.get("notional", 0)))
                entry = float(p.get("entryPrice", 0))
                mark  = float(p.get("markPrice", entry))
                pnl_pct = (mark - entry) / entry if side == "long" else (entry - mark) / entry
                positions.append(LivePosition(
                    symbol=sym, side=side, size=size,
                    entry_price=entry, current_price=mark, pnl_pct=pnl_pct,
                    contracts=abs(float(p["contracts"])), hedged=bool(p.get("hedged", False)),
                ))
            return positions
        except Exception as e:
            logger.error("get_positions 失败: %s", e)
            raise

    def is_hedged_mode(self) -> bool:
        """只读查询账户持仓模式，不自动修改账户设置。"""
        if self.dry_run:
            return False
        mode = self._retry(self._ex.fetch_position_mode)
        if not isinstance(mode.get("hedged"), bool):
            raise ValueError("无法确认币安账户的持仓模式")
        return mode["hedged"]

    # ── 下单 ─────────────────────────────────────────────────────────────
    def set_leverage(self, symbol: str, leverage: int):
        """设置合约杠杆"""
        if self.dry_run:
            logger.info("[DRY] set_leverage %s → %dx", symbol, leverage)
            return
        try:
            self._ex.set_leverage(leverage, self._contract_symbol(symbol))
            logger.info("设置杠杆 %s = %dx", symbol, leverage)
        except Exception as e:
            logger.warning("set_leverage(%s) 失败: %s", symbol, e)
            raise

    def entry_contracts(self, symbol: str, usdt_size: float) -> float:
        """Resolve the exact SDK quantity before persisting an order intent."""
        price = self.get_price(symbol)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"{symbol} 开仓价格无效")
        contracts = float(self._ex.amount_to_precision(self._contract_symbol(symbol), usdt_size / price))
        if not math.isfinite(contracts) or contracts <= 0:
            raise ValueError(f"{symbol} 开仓数量低于精度限制或无效")
        return contracts

    def get_order(self, symbol: str, client_order_id: str) -> dict:
        """Read a persisted intent's order without creating or retrying a trade."""
        return self._retry(self._ex.fetch_order, None, self._contract_symbol(symbol),
                           {"origClientOrderId": client_order_id})

    def open_long(self, symbol: str, usdt_size: float, *,
                  client_order_id: Optional[str] = None, contracts: Optional[float] = None) -> bool:
        """做多开仓（市价单）"""
        price = self.get_price(symbol)
        if price <= 0:
            return False
        contracts = usdt_size / price if contracts is None else contracts
        logger.info("[%s] 开多 %s | %.2f USDT | 价格=%.4f | %.6f 张",
                    "DRY" if self.dry_run else "LIVE", symbol, usdt_size, price, contracts)
        if self.dry_run:
            return True
        return self._execute_order(symbol, "buy", contracts, client_order_id=client_order_id)

    def open_short(self, symbol: str, usdt_size: float, *,
                   client_order_id: Optional[str] = None, contracts: Optional[float] = None) -> bool:
        """做空开仓（市价单）"""
        price = self.get_price(symbol)
        if price <= 0:
            return False
        contracts = usdt_size / price if contracts is None else contracts
        logger.info("[%s] 开空 %s | %.2f USDT | 价格=%.4f | %.6f 张",
                    "DRY" if self.dry_run else "LIVE", symbol, usdt_size, price, contracts)
        if self.dry_run:
            return True
        return self._execute_order(symbol, "sell", contracts, client_order_id=client_order_id)

    def close_position(self, symbol: str, side: str, *, client_order_id: Optional[str] = None,
                       contracts: Optional[float] = None) -> bool:
        """平仓（市价单，需要知道当前持仓方向）"""
        symbol = symbol.removesuffix(":USDT")
        logger.info("[%s] 平仓 %s | 方向=%s",
                    "DRY" if self.dry_run else "LIVE", symbol, side)
        if self.dry_run:
            return True
        try:
            # reduceOnly=True 确保只平仓不开反向仓
            positions = self.get_positions()
            pos = next((p for p in positions if p.symbol == symbol and p.side == side), None)
            if pos is None:
                logger.warning("close_position: %s 无持仓", symbol)
                return False
            if contracts is not None and not math.isclose(pos.contracts, contracts, rel_tol=1e-7):
                raise RuntimeError("平仓前持仓数量发生变化，停止提交")

            side_order = "sell" if pos.side == "long" else "buy"
            return self._execute_order(symbol, side_order,
                                       pos.contracts,
                                       reduce_only=True, client_order_id=client_order_id)
        except Exception as e:
            logger.error("close_position(%s) 失败: %s", symbol, e)
            return False

    # ── 内部工具 ──────────────────────────────────────────────────────────
    @staticmethod
    def _contract_symbol(symbol: str) -> str:
        """策略/缓存使用 ETH/USDT，CCXT USDT 永续接口使用 ETH/USDT:USDT。"""
        return f"{symbol}:USDT" if symbol.endswith("/USDT") else symbol

    def _execute_order(self, symbol: str, side: str,
                       contracts: float, reduce_only: bool = False,
                       client_order_id: Optional[str] = None) -> bool:
        try:
            params = {"reduceOnly": reduce_only} if reduce_only else {}
            if client_order_id:
                params["newClientOrderId"] = client_order_id
            # A timeout may follow an accepted order. Reads can retry; writes cannot.
            order = self._ex.create_order(
                self._contract_symbol(symbol), "market", side, contracts, None, params
            )
            logger.info("订单已提交，待查询确认: %s", order.get("id", "?"))
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
