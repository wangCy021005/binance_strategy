"""Persistent state for the daily live branch; exchange I/O is injected."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import uuid

logger = logging.getLogger("live.positions")


def utc_time(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("实盘状态中的时间戳必须包含时区")
    return result.astimezone(timezone.utc)


@contextmanager
def exclusive_live_run(path: Path):
    """An abandoned lock blocks execution until an operator checks the process."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"实盘运行锁已存在：{path}；请先核对是否有运行中的实例") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid()}, stream)
        yield
    finally:
        path.unlink(missing_ok=True)


class LivePositionManager:
    def __init__(self, exchange, cfg, path: Path):
        if cfg.timeframe != "1d":
            raise ValueError("当前实盘持仓管理只支持交接文档中的日线收盘确认模式")
        self.exchange, self.cfg, self.path = exchange, cfg, Path(path)
        self.account = exchange.account_fingerprint
        self.state = self._load()
        self.positions = {}
        self.prepared_bar = None
        self.repeated_bar = False

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "account": self.account, "positions": {},
                    "trades": [], "pending": None, "last_decision_bar": None}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (state.get("version") != 1 or state.get("account") != self.account
                or not isinstance(state.get("positions"), dict)
                or not isinstance(state.get("trades"), list)):
            raise ValueError("实盘本地状态损坏或 API 账户标识不一致，禁止自动覆盖")
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.state, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read_positions(self):
        positions = {}
        for position in self.exchange.get_positions():
            if position.symbol in positions or getattr(position, "hedged", False):
                raise RuntimeError("检测到双向持仓；当前实盘分支只支持单向持仓")
            if position.side not in ("long", "short"):
                raise ValueError("交易所返回了未知持仓方向")
            for value in (position.entry_price, position.current_price, position.size, position.contracts):
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("交易所返回的持仓价格、数量或名义金额无效")
            positions[position.symbol] = position
        return positions

    def _balance(self):
        balance = self.exchange.get_balance()
        if (not math.isfinite(balance.total_usdt) or balance.total_usdt <= 0
                or not math.isfinite(balance.available) or balance.available < 0):
            raise ValueError("无法确认有效的实盘账户余额")
        return balance

    def _accept_open(self, position, intent):
        if position.side != intent["side"]:
            raise RuntimeError("成交后的持仓方向与待确认开仓不一致")
        self.state["positions"][position.symbol] = {
            "side": position.side, "entry": position.entry_price,
            "contracts": position.contracts, "high": position.entry_price,
            "open_time": intent["time"], "strategy": intent.get("strategy", ""),
        }
        self.state["pending"] = None
        self._save()

    def _accept_close(self, symbol, intent):
        previous = self.state["positions"].pop(symbol)
        self.state["trades"].append({"symbol": symbol, "side": "close_" + previous["side"],
                                      "time": intent["time"], "reason": intent["reason"]})
        self.state["trades"] = self.state["trades"][-1000:]
        self.state["pending"] = None
        self._save()

    def _settle_pending(self):
        intent = self.state["pending"]
        if not intent.get("client_order_id") or not intent.get("contracts"):
            raise RuntimeError("待确认订单缺少订单标识或数量，请人工核对；不会自动接管")
        symbol = intent["symbol"]
        order = self.exchange.get_order(symbol, intent["client_order_id"])
        side = ("buy" if intent["side"] == "long" else "sell")
        if intent["action"] == "close":
            side = "sell" if intent["side"] == "long" else "buy"
        amount, filled = float(order.get("amount") or 0), float(order.get("filled") or 0)
        if (order.get("clientOrderId") != intent["client_order_id"]
                or order.get("symbol", "").removesuffix(":USDT") != symbol
                or order.get("side") != side
                or not all(math.isfinite(value) and value > 0 for value in (amount, filled))
                or not math.isclose(amount, intent["contracts"], rel_tol=1e-7)
                or filled > amount * (1 + 1e-7)):
            raise RuntimeError("订单标识、方向或成交数量未核实，保留 pending；不会重发")
        if order.get("status") not in ("closed", "canceled", "expired", "rejected"):
            raise RuntimeError("订单尚未结束（可能部分成交），保留 pending；不会重发")
        if order["status"] == "closed" and not math.isclose(filled, amount, rel_tol=1e-7):
            raise RuntimeError("订单完成状态与成交数量不一致，保留 pending")
        actual = self._read_positions()
        if intent["action"] == "open":
            position = actual.get(symbol)
            if position is None or not math.isclose(position.contracts, filled, rel_tol=1e-7):
                raise RuntimeError("订单成交数量与账户持仓尚未对齐，保留 pending")
            self._accept_open(position, intent)
        elif intent["action"] == "close":
            if symbol in actual or not math.isclose(filled, amount, rel_tol=1e-7):
                raise RuntimeError("平仓未全部确认，保留 pending 并停止后续开仓")
            self._accept_close(symbol, intent)
        else:
            raise ValueError("未知的待确认订单操作")
        return actual

    def reconcile(self, now):
        """Account reads must succeed; an unknown position never means 'flat'."""
        if self.exchange.is_hedged_mode():
            raise RuntimeError("当前实盘分支只支持单向持仓模式，不自动修改账户模式")
        pending = self.state.get("pending")
        actual = self._settle_pending() if pending else self._read_positions()
        for symbol, meta in list(self.state["positions"].items()):
            utc_time(meta["open_time"])
            if not math.isfinite(meta["high"]) or meta["high"] <= 0:
                raise ValueError("实盘追踪止损基准无效")
            if symbol not in actual:
                self._accept_close(symbol, {"time": now.isoformat(), "reason": "外部平仓/持仓已消失"})
                continue
            position = actual[symbol]
            if (position.side != meta["side"]
                    or not math.isclose(position.entry_price, meta["entry"], rel_tol=1e-7)
                    or not math.isclose(position.contracts, meta["contracts"], rel_tol=1e-7)):
                raise RuntimeError(f"{symbol} 持仓与本地记录不一致，请人工核对")
        unknown = set(actual) - self.state["positions"].keys()
        if unknown:
            raise RuntimeError(f"发现未登记的持仓 {sorted(unknown)}，不会自动接管或追加开仓")
        self.positions = actual

    def check_exits(self, histories, decision_bar, now):
        self.prepared_bar = decision_bar
        self.repeated_bar = self.state.get("last_decision_bar") == decision_bar
        if self.repeated_bar:
            logger.info("[LIVE] %s 已处理，跳过重复交易决策", decision_bar)
            return []
        closed = []
        end = utc_time(decision_bar) + timedelta(days=1)
        for symbol, position in list(self.positions.items()):
            meta = self.state["positions"][symbol]
            opened = utc_time(meta["open_time"])
            if opened > now:
                raise ValueError("持仓开仓时间晚于当前时间")
            if opened >= end:
                continue  # The most recent completed bar predates this entry.
            frame = histories.get(symbol)
            if frame is None or decision_bar not in frame.index:
                raise RuntimeError(f"{symbol} 缺少最新已收盘日线，停止交易")
            closes = [float(value) for timestamp, value in frame["close"].items()
                      if utc_time(timestamp) <= utc_time(decision_bar)
                      and utc_time(timestamp) + timedelta(days=1) > opened]
            if not closes or any(not math.isfinite(price) or price <= 0 for price in closes):
                raise ValueError(f"{symbol} 已收盘价格无效")
            price = closes[-1]
            meta["high"] = (max([meta["high"], *closes]) if position.side == "long"
                            else min([meta["high"], *closes]))
            entry, peak = meta["entry"], meta["high"]
            pnl = ((price - entry) / entry if position.side == "long" else (entry - price) / entry)
            retreat = ((price - peak) / peak if position.side == "long" else (peak - price) / peak)
            reason = ""
            if pnl <= self.cfg.hard_stop:
                reason = "硬止损"
            elif abs(peak - entry) / entry >= self.cfg.trailing_stop_min and retreat <= -self.cfg.trailing_stop_pct:
                reason = "追踪止损"
            elif self.cfg.max_hold_days and (now.date() - opened.date()).days >= self.cfg.max_hold_days:
                reason = "超时平仓"
            if reason:
                intent = {"action": "close", "symbol": symbol, "side": position.side,
                          "time": now.isoformat(), "reason": reason,
                          "contracts": position.contracts, "client_order_id": "qs-" + uuid.uuid4().hex}
                self.state["pending"] = intent
                self._save()
                self.exchange.close_position(symbol, position.side, client_order_id=intent["client_order_id"],
                                             contracts=intent["contracts"])
                self.positions = self._settle_pending()
                closed.append(symbol)
                logger.info("[LIVE] 已确认平仓 %s | %s", symbol, reason)
        self._save()
        return closed

    def open_entries(self, candidates, prices, regime, now):
        if self.prepared_bar is None:
            raise RuntimeError("开仓前必须先完成持仓对账与平仓检查")
        if self.repeated_bar or regime.max_slots <= 0:
            return []
        slots = min(regime.max_slots, self.cfg.max_positions)
        size_pct = min(regime.position_cap / slots, self.cfg.max_pos_pct)
        if self.cfg.top_k_signals:
            slots = min(slots, self.cfg.top_k_signals)
            size_pct = self.cfg.solo_pos_pct
        if not math.isfinite(size_pct) or not 0 < size_pct <= 1:
            raise ValueError("配置中的实盘单仓比例无效")
        opened = []
        for signal in candidates[:slots]:
            if len(self.positions) >= slots:
                break
            symbol = signal["symbol"]
            if symbol in self.positions:
                continue
            previous = next((trade for trade in reversed(self.state["trades"])
                             if trade["symbol"] == symbol), None)
            if (previous and "止损" in previous["reason"] and self.cfg.cooldown_days
                    and (now.date() - utc_time(previous["time"]).date()).days <= self.cfg.cooldown_days):
                logger.info("[LIVE] %s 止损冷静期内，跳过", symbol)
                continue
            price = prices.get(symbol, 0.0)
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"{symbol} 缺少有效实时价格")
            balance = self._balance()
            size = balance.total_usdt * size_pct
            if size * (1 + self.cfg.comm_taker) > balance.available:
                logger.warning("[LIVE] 可用保证金不足，跳过 %s", symbol)
                continue
            direction = signal.get("direction")
            if direction not in (-1, 1):
                raise ValueError("开仓信号方向必须为 1 或 -1")
            side = "long" if direction == 1 else "short"
            self.exchange.set_leverage(symbol, 1)
            intent = {"action": "open", "symbol": symbol, "side": side,
                      "time": now.isoformat(), "strategy": signal.get("strategy", ""),
                      "contracts": self.exchange.entry_contracts(symbol, size),
                      "client_order_id": "qs-" + uuid.uuid4().hex}
            self.state["pending"] = intent
            self._save()
            operation = self.exchange.open_long if side == "long" else self.exchange.open_short
            operation(symbol, size, client_order_id=intent["client_order_id"], contracts=intent["contracts"])
            self.positions = self._settle_pending()
            opened.append(symbol)
        return opened

    def complete(self):
        if self.prepared_bar is None or self.state.get("pending"):
            raise RuntimeError("实盘决策尚未完成确认")
        self.state["last_decision_bar"] = self.prepared_bar
        self._save()
