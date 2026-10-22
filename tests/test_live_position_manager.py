from dataclasses import replace
from pathlib import Path
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from config import CFG
from live.exchange import Balance
from live.position_manager import LivePositionManager, exclusive_live_run
from live_test_helpers import BAR, NOW, FakeExchange, history, make_position, seed_state


class LivePositionManagerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "account.json"
        self.exchange = FakeExchange()
        self.cfg = replace(CFG, symbols=["ETH/USDT"], top_k_signals=1, solo_pos_pct=0.60)
        self.regime = SimpleNamespace(max_slots=3, position_cap=0.5)
        self.signals = [{"symbol": "ETH/USDT", "direction": 1}]

    def manager(self):
        manager = LivePositionManager(self.exchange, self.cfg, self.path)
        manager.reconcile(NOW)
        return manager

    def holding(self, side="long", high=100.0, opened="2026-10-20T00:15:00Z"):
        position = make_position(side=side)
        self.exchange.positions[position.symbol] = position
        seed_state(self.path, position, high=high, opened=opened)
        return self.manager()

    def entry_calls(self):
        return [call for call in self.exchange.calls if call[0] == "open"]

    def test_hard_stops_work_in_both_directions_and_record_cooldown(self):
        for side, price in (("long", 91.0), ("short", 109.0)):
            with self.subTest(side=side):
                self.exchange.positions.clear()
                manager = self.holding(side)
                self.assertEqual(manager.check_exits({"ETH/USDT": history(price)}, BAR, NOW), ["ETH/USDT"])
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.assertEqual(saved["trades"][-1]["reason"], "硬止损")
                self.assertFalse(saved["positions"])

    def test_trailing_stops_work_in_both_directions(self):
        for side, high, price in (("long", 150.0, 115.0), ("short", 70.0, 90.0)):
            with self.subTest(side=side):
                self.exchange.positions.clear()
                manager = self.holding(side, high)
                self.assertEqual(manager.check_exits({"ETH/USDT": history(price)}, BAR, NOW), ["ETH/USDT"])
                self.assertEqual(manager.state["trades"][-1]["reason"], "追踪止损")

    def test_intraday_high_and_low_do_not_trigger_close_confirmed_stop(self):
        manager = self.holding()
        self.assertEqual(manager.check_exits({"ETH/USDT": history()}, BAR, NOW), [])
        self.assertTrue(self.exchange.positions)

    def test_missing_daily_runs_recover_peak_from_closed_prices(self):
        manager = self.holding(opened="2026-10-19T00:15:00Z")
        frame = history(115.0)
        frame.loc["2026-10-20T00:00:00Z", "close"] = 150.0
        self.assertEqual(manager.check_exits({"ETH/USDT": frame}, BAR, NOW), ["ETH/USDT"])
        self.assertEqual(manager.state["trades"][-1]["reason"], "追踪止损")

    def test_twenty_day_holding_exits_without_a_stop_trigger(self):
        manager = self.holding(opened="2026-10-01T00:15:00Z")
        manager.check_exits({"ETH/USDT": history()}, BAR, NOW)
        self.assertEqual(manager.state["trades"][-1]["reason"], "超时平仓")

    def test_completed_bar_before_entry_is_not_used_as_a_stop(self):
        manager = self.holding(opened="2026-10-22T00:05:00Z")
        self.assertEqual(manager.check_exits({"ETH/USDT": history(80.0)}, BAR, NOW), [])
        self.assertFalse(self.exchange.calls)

    def test_stop_cooldown_survives_restart_and_blocks_same_symbol_entry(self):
        manager = self.holding()
        manager.check_exits({"ETH/USDT": history(91.0)}, BAR, NOW)
        restarted = self.manager()
        restarted.check_exits({"ETH/USDT": history()}, BAR, NOW)
        self.assertEqual(restarted.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW), [])
        self.assertFalse(self.entry_calls())

    def test_restart_does_not_open_a_second_position_on_the_same_bar(self):
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        self.assertEqual(manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW), ["ETH/USDT"])
        manager.complete()
        restarted = self.manager()
        restarted.check_exits({"ETH/USDT": history()}, BAR, NOW)
        self.assertEqual(restarted.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW), [])
        self.assertEqual(len(self.entry_calls()), 1)

    def test_existing_position_fills_single_slot(self):
        manager = self.holding()
        manager.check_exits({"ETH/USDT": history()}, BAR, NOW)
        self.assertEqual(manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW), [])
        self.assertFalse(self.entry_calls())

    def test_crisis_does_not_open_even_with_a_candidate(self):
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        self.assertEqual(manager.open_entries(self.signals, {"ETH/USDT": 100.0},
                                             SimpleNamespace(max_slots=0), NOW), [])
        self.assertFalse(self.exchange.calls)

    def test_insufficient_available_margin_does_not_resize_or_submit(self):
        self.exchange.balance = Balance(1000.0, 100.0, 0.0)
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        self.assertEqual(manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW), [])
        self.assertFalse(self.entry_calls())

    def test_unconfirmed_open_is_persisted_and_not_resubmitted(self):
        self.exchange.open_unconfirmed = True
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        with self.assertRaises(RuntimeError):
            manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW)
        self.assertEqual(json.loads(self.path.read_text())["pending"]["action"], "open")
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertEqual(len(self.entry_calls()), 1)

    def test_pending_open_is_recovered_from_confirmed_account_position(self):
        state = seed_state(self.path)
        state["pending"] = {"action": "open", "symbol": "ETH/USDT", "side": "long",
                            "time": NOW.isoformat(), "client_order_id": "offline-recovered", "contracts": 6.0}
        self.path.write_text(json.dumps(state))
        self.exchange.positions["ETH/USDT"] = make_position()
        self.exchange.orders = {"offline-recovered": {
            "clientOrderId": "offline-recovered", "symbol": "ETH/USDT", "side": "buy",
            "status": "closed", "amount": 6.0, "filled": 6.0}}
        manager = self.manager()
        self.assertIn("ETH/USDT", manager.state["positions"])
        self.assertIsNone(manager.state["pending"])
        self.assertFalse(self.exchange.calls)

    def test_visible_partial_fill_does_not_clear_pending_while_order_is_open(self):
        self.exchange.order_status = "open"
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        with self.assertRaises(RuntimeError):
            manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW)
        pending = json.loads(self.path.read_text())["pending"]
        self.assertTrue(pending["client_order_id"])
        self.assertEqual(pending["contracts"], 6.0)
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertEqual(len(self.entry_calls()), 1)

    def test_confirmed_quantity_must_match_position_before_clearing_pending(self):
        self.exchange.filled_contracts = 3.0
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        with self.assertRaises(RuntimeError):
            manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW)
        self.assertIsNotNone(json.loads(self.path.read_text())["pending"])

    def test_finalized_partial_entry_can_be_recovered_with_exact_filled_position(self):
        self.exchange.order_status = "canceled"
        self.exchange.filled_contracts = 3.0
        self.exchange.open_unconfirmed = True
        manager = self.manager()
        manager.check_exits({}, BAR, NOW)
        with self.assertRaises(RuntimeError):
            manager.open_entries(self.signals, {"ETH/USDT": 100.0}, self.regime, NOW)
        self.exchange.positions["ETH/USDT"] = make_position(size=300.0)
        recovered = self.manager()
        self.assertIsNone(recovered.state["pending"])
        self.assertEqual(recovered.state["positions"]["ETH/USDT"]["contracts"], 3.0)
        self.assertEqual(len(self.entry_calls()), 1)

    def test_unconfirmed_close_prevents_further_entries_and_is_not_repeated(self):
        manager = self.holding()
        self.exchange.close_unconfirmed = True
        with self.assertRaises(RuntimeError):
            manager.check_exits({"ETH/USDT": history(91.0)}, BAR, NOW)
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertEqual(self.exchange.calls, [("close", "ETH/USDT", "long")])

    def test_position_read_failure_does_not_become_an_empty_account(self):
        self.exchange.position_error = RuntimeError("offline API failure")
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertFalse(self.exchange.calls)

    def test_unknown_account_position_is_not_automatically_adopted(self):
        self.exchange.positions["ETH/USDT"] = make_position()
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertFalse(self.exchange.calls)

    def test_changed_account_key_does_not_overwrite_execution_state(self):
        seed_state(self.path)
        original = self.path.read_bytes()
        self.exchange.account_fingerprint = "different-offline-account"
        with self.assertRaises(ValueError):
            self.manager()
        self.assertEqual(self.path.read_bytes(), original)

    def test_changed_position_size_requires_review(self):
        self.holding()
        self.exchange.positions["ETH/USDT"].contracts *= 2
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertFalse(self.exchange.calls)

    def test_corrupt_state_does_not_silently_reset(self):
        self.path.write_text('{"broken":')
        with self.assertRaises(ValueError):
            self.manager()
        self.assertFalse(self.exchange.calls)

    def test_hedged_account_mode_is_rejected_even_when_no_positions_exist(self):
        self.exchange.hedged_mode = True
        with self.assertRaises(RuntimeError):
            self.manager()
        self.assertFalse(self.exchange.calls)

    def test_invalid_signal_direction_does_not_submit_an_order(self):
        for direction in (0, float("nan"), None, 2):
            with self.subTest(direction=direction):
                self.exchange = FakeExchange()
                self.path.unlink(missing_ok=True)
                manager = self.manager()
                manager.check_exits({}, BAR, NOW)
                with self.assertRaises(ValueError):
                    manager.open_entries([{"symbol": "ETH/USDT", "direction": direction}],
                                         {"ETH/USDT": 100.0}, self.regime, NOW)
                self.assertFalse(self.exchange.calls)

    def test_pending_close_is_recovered_when_account_is_confirmed_flat(self):
        manager = self.holding()
        self.exchange.close_unconfirmed = True
        with self.assertRaises(RuntimeError):
            manager.check_exits({"ETH/USDT": history(91.0)}, BAR, NOW)
        self.exchange.positions.clear()
        recovered = self.manager()
        self.assertIsNone(recovered.state["pending"])
        self.assertEqual(recovered.state["trades"][-1]["reason"], "硬止损")
        self.assertEqual(len(self.exchange.calls), 1)

    def test_missing_held_symbol_candle_prevents_trading(self):
        manager = self.holding()
        with self.assertRaises(RuntimeError):
            manager.check_exits({}, BAR, NOW)
        self.assertFalse(self.exchange.calls)


class LiveRunLockTests(unittest.TestCase):
    def test_concurrent_live_instance_is_rejected_and_lock_released_on_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "live.lock"
            with self.assertRaises(ValueError):
                with exclusive_live_run(path):
                    with self.assertRaises(RuntimeError):
                        with exclusive_live_run(path):
                            self.fail("A second live process acquired the lock")
                    raise ValueError("offline simulated failure")
            self.assertFalse(path.exists())
            with exclusive_live_run(path):
                self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
