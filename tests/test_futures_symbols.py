"""Offline adapter checks; the CCXT client never connects to an exchange."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import ccxt
from live.exchange import BinanceExchange


class FuturesSymbolTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()

        def ticker(symbol):
            if symbol != "ETH/USDT:USDT":
                raise ccxt.BadSymbol("Unknown futures market: " + symbol)
            return {"symbol": symbol, "last": 100.0}

        self.client.fetch_ticker.side_effect = ticker
        self.client.create_order.return_value = {"id": "offline-order"}
        self.client.fetch_positions.return_value = [{
            "info": {}, "symbol": "ETH/USDT:USDT", "side": "long",
            "contracts": 2.0, "contractSize": 1.0, "entryPrice": 100.0,
            "markPrice": 110.0, "notional": 220.0, "unrealizedPnl": 20.0,
        }]
        environment = patch.dict(os.environ, {
            "BINANCE_API_KEY": "offline-test-key",
            "BINANCE_API_SECRET": "offline-test-secret",
            "PROXY_URL": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        factory = patch("live.exchange.ccxt.binanceusdm", return_value=self.client)
        factory.start()
        self.addCleanup(factory.stop)
        logger = patch("live.exchange.logger")
        logger.start()
        self.addCleanup(logger.stop)
        self.exchange = BinanceExchange(dry_run=False)

    def test_strategy_and_qualified_symbols_both_fetch_futures_prices(self):
        for symbol in ("ETH/USDT", "ETH/USDT:USDT"):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.exchange.get_price(symbol), 100.0)

    def test_leverage_request_uses_futures_symbol(self):
        self.exchange.set_leverage("ETH/USDT", 1)
        self.client.set_leverage.assert_called_once_with(1, "ETH/USDT:USDT")

    def test_long_and_short_order_payloads_use_futures_symbol(self):
        for method, side in (("open_long", "buy"), ("open_short", "sell")):
            with self.subTest(method=method):
                self.client.create_order.reset_mock()
                self.assertTrue(getattr(self.exchange, method)("ETH/USDT", 100.0))
                self.client.create_order.assert_called_once_with(
                    "ETH/USDT:USDT", "market", side, 1.0, None, {},
                )

    def test_futures_positions_are_returned_in_strategy_symbol_format(self):
        positions = self.exchange.get_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].symbol, "ETH/USDT")

    def test_close_finds_position_and_preserves_reduce_only(self):
        for symbol in ("ETH/USDT", "ETH/USDT:USDT"):
            with self.subTest(symbol=symbol):
                self.client.create_order.reset_mock()
                self.assertTrue(self.exchange.close_position(symbol, "long"))
                self.client.create_order.assert_called_once_with(
                    "ETH/USDT:USDT", "market", "sell", 2.0, None,
                    {"reduceOnly": True},
                )

    def test_ambiguous_order_timeout_is_not_retried(self):
        self.client.create_order.side_effect = ccxt.RequestTimeout("offline: accepted response was lost")
        with patch("live.exchange.time.sleep"):
            self.assertFalse(self.exchange.open_long("ETH/USDT", 100.0))
        self.assertEqual(self.client.create_order.call_count, 1)

    def test_prepared_entry_quantity_and_client_id_reach_sdk_unchanged(self):
        self.client.amount_to_precision.return_value = "1.234"
        contracts = self.exchange.entry_contracts("ETH/USDT", 123.45)
        self.assertEqual(contracts, 1.234)
        self.exchange.open_long("ETH/USDT", 123.45, contracts=contracts, client_order_id="offline-client-id")
        self.client.create_order.assert_called_once_with(
            "ETH/USDT:USDT", "market", "buy", 1.234, None,
            {"newClientOrderId": "offline-client-id"})

    def test_pending_order_query_uses_client_id_without_order_creation(self):
        self.exchange.get_order("ETH/USDT", "offline-client-id")
        self.client.fetch_order.assert_called_once_with(
            None, "ETH/USDT:USDT", {"origClientOrderId": "offline-client-id"})
        self.client.create_order.assert_not_called()

    def test_close_quantity_change_does_not_submit_an_order(self):
        self.assertFalse(self.exchange.close_position("ETH/USDT", "long", contracts=1.0))
        self.client.create_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
