from dataclasses import replace
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from config import CFG
from live.live_engine import LiveEngine
from live_test_helpers import NOW, history


class SimBranchRegressionTests(unittest.TestCase):
    def test_live_node_never_pushes_account_data_even_without_env_flag(self):
        engine = LiveEngine.__new__(LiveEngine)
        engine.dry_run = False
        with patch.dict(os.environ, {"SKIP_GITHUB_PUSH": ""}):
            with patch("live.github_push.push_data_files") as push:
                engine._push_to_github()
                push.assert_not_called()

    def test_sim_node_remains_the_data_publisher_when_skip_flag_is_unset(self):
        engine = LiveEngine.__new__(LiveEngine)
        engine.dry_run = True
        with patch.dict(os.environ, {"SKIP_GITHUB_PUSH": ""}):
            with patch("live.github_push.push_data_files", return_value=4) as push:
                engine._push_to_github()
                push.assert_called_once()

    def test_daily_simulation_never_initializes_live_exchange_or_runtime_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("live.sim_exchange.STATE_FILE", root / "sim_account.json"), \
                    patch("live.live_engine.STATE_FILE", root / "live_state.json"), \
                    patch("live.live_engine.SIGNALS_FILE", root / "signals.json"), \
                    patch("live.live_engine.PROJECT_ROOT", root), \
                    patch("live.exchange.BinanceExchange", side_effect=AssertionError("SIM initialized LIVE")):
                engine = LiveEngine(cfg=replace(CFG, symbols=["ETH/USDT"]), dry_run=True)
                engine.feed = Mock()
                engine.feed.get_all_ohlcv.return_value = {"ETH/USDT": history()}
                engine.feed.get_all_funding.return_value = {}
                engine.feed.get_btc_ohlcv.return_value = history()
                engine.feed.get_trade_timestamps.return_value = list(history().index)
                engine._update_data = Mock()
                engine._get_realtime_prices = Mock(return_value={"ETH/USDT": 100.0})
                engine._push_to_github = Mock()
                engine.signals = Mock()
                engine.signals.generate.return_value = []
                with patch("live.live_engine.datetime") as clock:
                    clock.now.return_value = NOW
                    engine.run_once()
            saved = json.loads((root / "live_state.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["dry_run"])
            self.assertEqual(saved["portfolio"], 1000.0)
            self.assertEqual(saved["positions"], [])
            self.assertTrue((root / "sim_account.json").exists())
            self.assertFalse((root / ".runtime").exists())


if __name__ == "__main__":
    unittest.main()
