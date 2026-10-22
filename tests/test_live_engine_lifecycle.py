from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from config import CFG
from live.live_engine import LiveEngine
from live_test_helpers import BAR, NOW, FakeExchange, history, make_position, seed_state


class LiveEngineLifecycleTests(unittest.TestCase):
    def run_cycle(self, exchange, state_path, candidates, close=100.0, configure=None):
        with patch("live.exchange.BinanceExchange", return_value=exchange):
            engine = LiveEngine(cfg=replace(CFG, symbols=["ETH/USDT"],
                                           top_k_signals=1, solo_pos_pct=0.60), dry_run=False)
        engine.feed = Mock()
        engine.feed.get_all_ohlcv.return_value = {"ETH/USDT": history(close)}
        funding_index = pd.date_range(end=BAR, periods=9, freq="8h").strftime("%Y-%m-%dT%H:%M:%SZ")
        engine.feed.get_all_funding.return_value = {
            "ETH/USDT": pd.Series(0.0001, index=funding_index)}
        engine.feed.get_btc_ohlcv.return_value = history()
        engine.feed.get_trade_timestamps.return_value = list(history().index)
        engine._update_data = Mock()
        engine._get_realtime_prices = Mock(return_value={"ETH/USDT": 100.0,
                                                       "SOL/USDT": 100.0, "BNB/USDT": 100.0})
        engine._save_state = Mock()
        engine._push_to_github = Mock()
        engine.signals = Mock()
        engine.signals.generate.return_value = candidates
        if configure:
            configure(engine)
        with patch("live.live_engine.LIVE_ACCOUNT_STATE_FILE", state_path, create=True):
            with patch("live.live_engine.datetime") as clock:
                clock.now.return_value = NOW
                engine.run_once()
        return engine

    def test_live_entries_follow_top_one_and_configured_size(self):
        exchange = FakeExchange()
        candidates = [{"symbol": symbol, "direction": 1} for symbol in
                      ("ETH/USDT", "SOL/USDT", "BNB/USDT")]
        with tempfile.TemporaryDirectory() as temp:
            self.run_cycle(exchange, Path(temp) / "live.json", candidates)
        self.assertEqual([call for call in exchange.calls if call[0] == "open"],
                         [("open", "ETH/USDT", "long", 600.0)])

    def test_live_daily_cycle_checks_existing_position_before_new_entries(self):
        exchange = FakeExchange()
        position = make_position()
        exchange.positions[position.symbol] = position
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "live-account.json"
            seed_state(state_path, position)
            self.run_cycle(exchange, state_path, [], close=91.0)
            self.assertIn(("close", "ETH/USDT", "long"), exchange.calls)
            self.assertFalse(exchange.positions)

    def test_stale_or_missing_inputs_prevent_any_live_order(self):
        for case in ("asset_bar", "btc_bar", "funding", "quote", "momentum_lookback"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                exchange = FakeExchange()

                def configure(engine):
                    if case == "asset_bar":
                        engine.feed.get_all_ohlcv.return_value = {"ETH/USDT": history().iloc[:-1]}
                    elif case == "btc_bar":
                        engine.feed.get_btc_ohlcv.return_value = history().iloc[:-1]
                    elif case == "funding":
                        engine.feed.get_all_funding.return_value = {}
                    elif case == "momentum_lookback":
                        engine.feed.get_all_ohlcv.return_value = {"ETH/USDT": history().iloc[-252:]}
                    else:
                        engine._get_realtime_prices.return_value = {}

                with self.assertRaises(RuntimeError):
                    self.run_cycle(exchange, Path(temp) / "live.json",
                                   [{"symbol": "ETH/USDT", "direction": 1}], configure=configure)
                self.assertFalse(exchange.calls)

    def test_live_data_update_failure_is_not_downgraded_to_success(self):
        with patch("live.exchange.BinanceExchange", return_value=FakeExchange()):
            engine = LiveEngine(cfg=CFG, dry_run=False)
        with patch("subprocess.run", return_value=Mock(returncode=1, stderr="offline fetch failure")):
            with self.assertRaises(RuntimeError):
                engine._update_data()

    def test_funding_must_be_fresh_and_complete_at_strategy_cutoff(self):
        cases = {
            "fresh_tail_but_stale_as_of": pd.Series([0.0001, 0.0002], index=[
                "2026-09-01T00:00:00Z", "2026-10-21T16:00:00Z"]),
            "invalid_as_of": pd.Series([float("nan"), 0.0002], index=[
                BAR, "2026-10-21T16:00:00Z"]),
            "insufficient_lookback": pd.Series([0.0001], index=[BAR]),
        }
        for name, series in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temp:
                exchange = FakeExchange()
                def configure(engine):
                    engine.feed.get_all_funding.return_value = {"ETH/USDT": series}
                with self.assertRaises(RuntimeError):
                    self.run_cycle(exchange, Path(temp) / "live.json", [], configure=configure)
                self.assertFalse(exchange.calls)


if __name__ == "__main__":
    unittest.main()
