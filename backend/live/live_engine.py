"""
实盘/模拟主引擎
每日运行一次（UTC 00:10，日线收盘后5分钟）

工作流程：
  1. 更新本地 SQLite 缓存（最新K线 + 资金费率）
  2. 拉实时价格
  3. 检查止损（追踪止损/硬止损）→ 平仓
  4. 结算资金费率（持仓成本）
  5. Regime 识别 + 信号生成
  6. 开新仓（模拟或实盘）
  7. 记录净值 → push GitHub → Dashboard 更新
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("live.engine")

STATE_FILE     = Path(__file__).parent.parent.parent / "data" / "live_state.json"
SIGNALS_FILE   = Path(__file__).parent.parent.parent / "data" / "live_signals.json"
PROJECT_ROOT   = Path(__file__).parent.parent.parent


class LiveEngine:
    """实盘/模拟交易引擎"""

    def __init__(self, cfg=None, dry_run: bool = True, initial_cash: float = 1000.0):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from config import CFG
        from agents.regime_agent import RegimeAgent
        from agents.signal_agent import SignalAgent
        from core.data_feed import CryptoDataFeed

        self.cfg      = cfg or CFG
        self.dry_run  = dry_run
        self.feed     = CryptoDataFeed()
        self.regime   = RegimeAgent(self.cfg)
        self.signals  = SignalAgent(self.cfg)

        if dry_run:
            # ── 模拟模式：用 SimExchange 跟踪真实盈亏 ──────────────────────
            from live.sim_exchange import SimExchange
            self.sim = SimExchange(initial_cash=initial_cash)
            self.exchange = None   # 不用真实交易所
            self.portfolio_value = self.sim.get_balance()["total"]
        else:
            # ── 实盘模式：连接真实 Binance ──────────────────────────────────
            from live.exchange import BinanceExchange
            from agents.risk_agent import RiskAgent
            self.exchange = BinanceExchange(dry_run=False, leverage=1)
            self.sim = None
            import dataclasses
            bal = self.exchange.get_balance()
            live_cash = bal.total_usdt if bal.total_usdt > 10 else self.cfg.cash
            self.risk_ag = RiskAgent(dataclasses.replace(self.cfg, cash=live_cash))
            self.portfolio_value = live_cash

        logger.info("LiveEngine 初始化 | mode=%s | portfolio=%.2f",
                    "SIM" if dry_run else "LIVE", self.portfolio_value)

    def run_once(self):
        """运行一次完整的交易决策流程"""
        now = datetime.now(timezone.utc)
        ts  = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("=" * 60)
        logger.info("运行 | %s | mode=%s", ts, "SIM" if self.dry_run else "LIVE")

        # ── Step 1: 更新数据缓存 ────────────────────────────────────────────
        self._update_data()

        # ── Step 2: 加载历史数据 + 找最新时间戳 ────────────────────────────
        end_date   = now.strftime("%Y-%m-%d")
        start_date = "2022-01-01"
        all_ohlcv   = self.feed.get_all_ohlcv(self.cfg.symbols, "1d", start_date, end_date)
        all_funding = self.feed.get_all_funding(self.cfg.symbols, start_date, end_date)
        btc_df      = self.feed.get_btc_ohlcv("1d", start_date, end_date)
        timestamps  = self.feed.get_trade_timestamps("1d", start_date, end_date)
        if not timestamps:
            logger.error("无数据！")
            return
        latest_ts = timestamps[-1]

        # ── Step 3: 拉实时价格（用于持仓盈亏和新仓滑点）────────────────────
        active = [s for s, df in all_ohlcv.items() if not df.empty]
        prices = self._get_realtime_prices(active)

        # ── Step 4: 止损检查（模拟模式）────────────────────────────────────
        if self.sim:
            closed = self.sim.check_stops(
                prices,
                hard_stop=self.cfg.hard_stop,
                trailing_pct=self.cfg.trailing_stop_pct,
                trailing_min=self.cfg.trailing_stop_min,
            )
            if closed:
                logger.info("止损平仓: %s", closed)
            # 资金费率结算（持仓过夜成本）
            self.sim.settle_funding(prices)

        # ── Step 5: Regime 识别 ─────────────────────────────────────────────
        rs = self.regime.detect(btc_df, latest_ts)

        # ── Step 6: 生成信号 ───────────────────────────────────────────────
        candidates = []
        if rs.max_slots > 0:
            candidates = self.signals.generate(
                active, all_ohlcv, all_funding, latest_ts, rs
            )

        # ── Step 7: 开仓决策 ───────────────────────────────────────────────
        opened = []
        if self.sim:
            opened = self._open_sim_positions(candidates, prices, rs)
        elif self.exchange:
            opened = self._open_live_positions(candidates, prices, rs)

        # ── Step 8: 记录净值 + 保存状态 ────────────────────────────────────
        if self.sim:
            nav = self.sim.record_equity(prices)
            stats = self.sim.get_stats()
            logger.info("模拟净值: %.4f | 收益 %.2f%% | 持仓 %d | 累计交易 %d",
                        nav, (nav-1)*100, stats["positions"], stats["total_trades"])

        # ── Step 9: 保存状态文件（给 Dashboard 用）─────────────────────────
        self._save_state(ts, rs, candidates, opened, prices)

        # ── Step 10: push GitHub ────────────────────────────────────────────
        self._push_to_github()

        logger.info("=" * 60)

    def _get_realtime_prices(self, symbols: list[str]) -> dict[str, float]:
        """拉实时价格（ccxt 公共行情，不需要 API Key）"""
        prices = {}
        if self.sim:
            # 模拟模式：用 SimExchange 的 ccxt
            prices = self.sim.get_prices(symbols)
        elif self.exchange:
            for s in symbols:
                p = self.exchange.get_price(s)
                if p > 0:
                    prices[s] = p
        return prices

    def _open_sim_positions(self, candidates, prices, rs) -> list[str]:
        """模拟开仓"""
        if not candidates:
            return []
        n_slots  = max(rs.max_slots, 1)
        size_pct = min(rs.position_cap / n_slots, self.cfg.max_pos_pct)
        total_val = self.sim.get_balance(prices)["total"]
        opened = []
        for sig in candidates[:n_slots]:
            sym = sig["symbol"]
            if sym in self.sim.state["positions"]:
                continue
            size = total_val * size_pct
            price = prices.get(sym, 0)
            if price <= 0:
                continue
            ok = self.sim.open_position(
                sym, "long" if sig["direction"] > 0 else "short",
                size, price, sig.get("strategy", "")
            )
            if ok:
                opened.append(sym)
        return opened

    def _open_live_positions(self, candidates, prices, rs) -> list[str]:
        """实盘开仓"""
        opened = []
        n_slots  = max(rs.max_slots, 1)
        size_pct = min(rs.position_cap / n_slots, self.cfg.max_pos_pct)
        total_val = self.portfolio_value
        for sig in candidates[:n_slots]:
            sym = sig["symbol"]
            size = total_val * size_pct
            self.exchange.set_leverage(sym, 1)
            if sig["direction"] > 0:
                if self.exchange.open_long(sym, size):
                    opened.append(sym)
            else:
                if self.exchange.open_short(sym, size):
                    opened.append(sym)
        return opened

    def _save_state(self, ts, rs, candidates, opened, prices):
        """保存状态 + 信号文件 + 更新 latest.json 给 Dashboard"""
        # live_state.json
        if self.sim:
            bal = self.sim.get_balance(prices)
            portfolio_value = bal["total"]
            positions = [
                {
                    "symbol":   p["symbol"],
                    "side":     p["side"],
                    "qty":      round(p["qty"], 6),
                    "entry":    p["entry_price"],
                    "current":  prices.get(p["symbol"], p["entry_price"]),
                    "pnl_pct":  self._pos_pnl_pct(p, prices.get(p["symbol"], p["entry_price"])),
                }
                for p in self.sim.get_positions()
            ]
        else:
            portfolio_value = self.portfolio_value
            positions = []

        state = {
            "timestamp":    ts,
            "dry_run":      self.dry_run,
            "regime":       rs.regime,
            "portfolio":    round(portfolio_value, 2),
            "nav":          round(portfolio_value / (self.sim.initial if self.sim else self.portfolio_value), 4) if self.sim else 1.0,
            "positions":    positions,
            "opened":       opened,
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

        # live_signals.json
        signals_data = {
            "as_of":   latest_ts if 'latest_ts' in locals() else ts[:10],
            "regime":  rs.regime,
            "slots":   rs.max_slots,
            "cap_pct": int(rs.position_cap * 100),
            "signals": [
                {
                    "symbol":    s["symbol"],
                    "direction": "long" if s["direction"] > 0 else "short",
                    "score":     round(s["score"], 3),
                    "momentum":  round(s.get("momentum", 0) * 100, 1),
                    "strategy":  s.get("strategy", ""),
                }
                for s in candidates
            ],
        }
        (SIGNALS_FILE.parent / "live_signals.json").write_text(
            json.dumps(signals_data, indent=2, ensure_ascii=False))

        # 更新 latest.json 的 equity（给 Dashboard 显示模拟净值曲线）
        if self.sim:
            self._update_latest_equity()

    def _pos_pnl_pct(self, pos, current):
        if current <= 0:
            return 0
        if pos["side"] == "long":
            return round((current - pos["entry_price"]) / pos["entry_price"] * 100, 2)
        return round((pos["entry_price"] - current) / pos["entry_price"] * 100, 2)

    def _update_latest_equity(self):
        """把模拟净值历史合并进 latest.json，Dashboard 可显示真实模拟曲线"""
        latest_path = PROJECT_ROOT / "data" / "latest.json"
        if not latest_path.exists():
            return
        try:
            data = json.loads(latest_path.read_text())
            data["sim_equity"] = self.sim.state.get("equity_history", [])
            data["sim_trades"] = self.sim.state.get("trades", [])[-50:]
            data["sim_stats"]  = self.sim.get_stats()
            latest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning("更新 latest.json 失败: %s", e)

    def _push_to_github(self):
        """推送数据到 GitHub（Dashboard 自动更新）"""
        try:
            import subprocess
            files = ["data/latest.json", "data/live_state.json",
                     "data/live_signals.json", "data/sim_account.json"]
            existing = [f for f in files if (PROJECT_ROOT / f).exists()]
            if not existing:
                return
            subprocess.run(["git", "add"] + existing, cwd=str(PROJECT_ROOT),
                           check=True, capture_output=True)
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"], cwd=str(PROJECT_ROOT),
                capture_output=True
            )
            if result.returncode == 0:
                logger.info("数据无变化，跳过 push")
                return
            msg = f"data: 模拟交易更新 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", msg], cwd=str(PROJECT_ROOT),
                           check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_ROOT),
                           check=True, capture_output=True)
            logger.info("✅ 数据已推送到 GitHub")
        except Exception as e:
            logger.warning("GitHub push 失败: %s", e)

    def _update_data(self):
        """增量更新本地 SQLite 缓存"""
        logger.info("更新本地数据缓存...")
        try:
            import subprocess, sys
            python = sys.executable
            script = str(PROJECT_ROOT / "scripts" / "fetch_data.py")
            from datetime import timedelta
            start = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
            result = subprocess.run(
                [python, script, "--all", "--start", start],
                capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                logger.warning("数据更新失败: %s", result.stderr[:200])
            else:
                logger.info("数据更新成功")
        except Exception as e:
            logger.warning("数据更新异常: %s", e)
