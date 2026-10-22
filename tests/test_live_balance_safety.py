"""Offline checks: failed account reads must prevent the trading loop."""
from dataclasses import replace
from pathlib import Path
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import ccxt
from config import CFG
from live.exchange import BinanceExchange
from live.live_engine import LiveEngine


def balance_payload(total):
    return {
        "info": {}, "timestamp": None, "datetime": None,
        "USDT": {"free": total, "used": 0.0, "total": total},
        "free": {"USDT": total}, "used": {"USDT": 0.0},
        "total": {"USDT": total},
    }


class LiveBalanceSafetyTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(name="offline_binance_client")
        self.client.create_order.side_effect = AssertionError("Orders are forbidden in offline tests")
        self.config = replace(CFG, cash=10000.0)
        self.env = patch.dict(os.environ, {
            "BINANCE_API_KEY": "offline-test-key",
            "BINANCE_API_SECRET": "offline-test-secret",
            "PROXY_URL": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.factory = patch("live.exchange.ccxt.binanceusdm", return_value=self.client)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def test_authentication_failure_is_not_reported_as_zero_balance(self):
        self.client.fetch_balance.side_effect = ccxt.AuthenticationError("-2015 rejected")
        exchange = BinanceExchange(dry_run=False)
        with self.assertLogs("live.exchange", level="ERROR"):
            with self.assertRaises(ccxt.AuthenticationError):
                exchange.get_balance()

    def test_position_authentication_failure_is_not_reported_as_no_positions(self):
        self.client.fetch_positions.side_effect = ccxt.AuthenticationError("-2015 rejected")
        exchange = BinanceExchange(dry_run=False)
        with self.assertLogs("live.exchange", level="ERROR"):
            with self.assertRaises(ccxt.AuthenticationError):
                exchange.get_positions()

    def test_invalid_live_balance_cannot_fall_back_to_backtest_cash(self):
        for total in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(total=total):
                self.client.fetch_balance.return_value = balance_payload(total)
                with self.assertRaises(ValueError):
                    LiveEngine(cfg=self.config, dry_run=False)

    def test_actual_live_balance_is_used_even_below_ten_usdt(self):
        for total in (6.0, 200.0):
            with self.subTest(total=total):
                self.client.fetch_balance.return_value = balance_payload(total)
                engine = LiveEngine(cfg=self.config, dry_run=False)
                self.assertEqual(engine.portfolio_value, total)
                self.assertEqual(engine.risk_ag.cfg.cash, total)

    def test_cli_exits_before_trading_loop_when_authentication_fails(self):
        # Importing this CLI normally configures the production log file.
        with patch("logging.FileHandler", return_value=logging.NullHandler()):
            with patch("logging.basicConfig"):
                from scripts import run_live

        self.client.fetch_balance.side_effect = ccxt.AuthenticationError("-2015 rejected")
        with tempfile.TemporaryDirectory() as temp, patch.object(run_live, "LIVE_LOCK_FILE", Path(temp) / "live.lock"), patch.object(sys, "argv", ["run_live.py", "--live"]):
            with patch.object(run_live, "logger"):
                with patch.object(LiveEngine, "run_once") as run_once:
                    with self.assertLogs("live.exchange", level="ERROR"):
                        with self.assertRaises(SystemExit) as stopped:
                            run_live.main()
                    self.assertEqual(stopped.exception.code, 1)
                    run_once.assert_not_called()


if __name__ == "__main__":
    unittest.main()
