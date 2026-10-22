from dataclasses import replace
from datetime import datetime, timezone
import json

import pandas as pd

from live.exchange import Balance, LivePosition

NOW = datetime(2026, 10, 22, 0, 15, tzinfo=timezone.utc)
BAR = "2026-10-21T00:00:00Z"


class FakeExchange:
    """In-memory exchange: no SDK clients, sockets, or real orders."""
    account_fingerprint = "offline-account"

    def __init__(self):
        self.balance = Balance(1000.0, 1000.0, 0.0)
        self.positions = {}
        self.calls = []
        self.position_error = None
        self.open_unconfirmed = False
        self.close_unconfirmed = False
        self.hedged_mode = False
        self.orders = {}
        self.order_status = "closed"
        self.filled_contracts = None

    def is_hedged_mode(self):
        return self.hedged_mode

    def get_balance(self):
        return self.balance

    def get_positions(self):
        if self.position_error:
            raise self.position_error
        return [replace(position) for position in self.positions.values()]

    def get_price(self, symbol):
        return 100.0

    def set_leverage(self, symbol, leverage):
        self.calls.append(("leverage", symbol, leverage))

    def entry_contracts(self, symbol, amount):
        return amount / 100.0

    def get_order(self, symbol, client_order_id):
        return self.orders[client_order_id].copy()

    def _open(self, symbol, amount, side, client_order_id=None, contracts=None):
        self.calls.append(("open", symbol, side, amount))
        contracts = amount / 100.0 if contracts is None else contracts
        self.orders[client_order_id] = {
            "clientOrderId": client_order_id, "symbol": symbol,
            "side": "buy" if side == "long" else "sell", "status": self.order_status,
            "amount": contracts, "filled": contracts if self.filled_contracts is None else self.filled_contracts}
        if not self.open_unconfirmed:
            self.positions[symbol] = make_position(symbol, side, amount)
        return True

    def open_long(self, symbol, amount, **kwargs):
        return self._open(symbol, amount, "long", **kwargs)

    def open_short(self, symbol, amount, **kwargs):
        return self._open(symbol, amount, "short", **kwargs)

    def close_position(self, symbol, side, client_order_id=None, contracts=None):
        self.calls.append(("close", symbol, side))
        contracts = self.positions[symbol].contracts
        self.orders[client_order_id] = {
            "clientOrderId": client_order_id, "symbol": symbol,
            "side": "sell" if side == "long" else "buy", "status": "closed",
            "amount": contracts, "filled": contracts}
        if not self.close_unconfirmed:
            self.positions.pop(symbol, None)
        return not self.close_unconfirmed


def make_position(symbol="ETH/USDT", side="long", size=600.0):
    return LivePosition(symbol, side, size, 100.0, 100.0, 0.0, contracts=size / 100.0)


def history(close=100.0):
    index = pd.date_range(end="2026-10-21", periods=262, tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    frame = pd.DataFrame({"open": 100.0, "high": 150.0, "low": 50.0,
                          "close": 100.0, "volume": 1000.0}, index=index)
    frame.loc[BAR, "close"] = close
    return frame


def seed_state(path, position=None, opened="2026-10-01T00:15:00Z", high=100.0, last_bar=None):
    positions = {}
    if position:
        positions[position.symbol] = {
            "side": position.side, "entry": position.entry_price,
            "contracts": getattr(position, "contracts", 0.0),
            "high": high, "open_time": opened,
        }
    state = {"version": 1, "account": "offline-account", "positions": positions,
             "trades": [], "pending": None, "last_decision_bar": last_bar}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return state
