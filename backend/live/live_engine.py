"""
实盘/模拟主引擎
每日运行一次（UTC 00:10，日线收盘后10分钟）

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
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("live.engine")

STATE_FILE     = Path(__file__).parent.parent.parent / "data" / "live_state.json"
SIGNALS_FILE   = Path(__file__).parent.parent.parent / "data" / "live_signals.json"
PROJECT_ROOT   = Path(__file__).parent.parent.parent
LIVE_ACCOUNT_STATE_FILE = PROJECT_ROOT / ".runtime" / "live-account.json"


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
        self.live_manager = None
        self.closed = []

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
            if not math.isfinite(bal.total_usdt) or bal.total_usdt <= 0:
                raise ValueError("币安合约账户总资产无效或为零，停止实盘初始化")
            live_cash = bal.total_usdt
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
            if not self.dry_run:
                raise RuntimeError("本地没有可用行情，停止实盘")
            logger.error("无数据！")
            return
        latest_ts = timestamps[-1]

        # ── Step 2.5: 数据新鲜度自检（防静默停跑）────────────────────────────
        try:
            data_date = latest_ts[:10]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            from datetime import date as _date
            lag_days = (_date.fromisoformat(today) - _date.fromisoformat(data_date)).days
            if lag_days >= 3:
                logger.warning(
                    "⚠️ 数据滞后 %d 天（最新K线 %s，今天 %s）— 数据链路可能中断，"
                    "请检查 fetch_data / crontab / 网络连通性", lag_days, data_date, today)
                # 写入 live_state 供 Dashboard 展示告警
                (SIGNALS_FILE.parent / "data_staleness_alert.json").write_text(json.dumps({
                    "alert": "数据滞后",
                    "lag_days": lag_days,
                    "latest_data": data_date,
                    "checked_at": ts,
                }, ensure_ascii=False))
            else:
                stale_file = SIGNALS_FILE.parent / "data_staleness_alert.json"
                if stale_file.exists():
                    stale_file.unlink()
        except Exception as e:
            logger.warning("数据新鲜度检查失败: %s", e)

        if self.exchange:
            self._validate_live_data(all_ohlcv, all_funding, btc_df, latest_ts, now)
            from live.position_manager import LivePositionManager
            self.live_manager = LivePositionManager(self.exchange, self.cfg, LIVE_ACCOUNT_STATE_FILE)
            self.live_manager.reconcile(now)
            for symbol in self.live_manager.positions:
                if symbol not in all_ohlcv:
                    all_ohlcv[symbol] = self.feed.get_ohlcv(symbol, "1d", start_date, end_date)

        # ── Step 3: 拉实时价格（用于持仓盈亏和新仓滑点）────────────────────
        active = [s for s in self.cfg.symbols if not all_ohlcv[s].empty]
        quote_symbols = list(dict.fromkeys(active + (list(self.live_manager.positions) if self.live_manager else [])))
        prices = self._get_realtime_prices(quote_symbols)
        if self.exchange and any(not math.isfinite(prices.get(symbol, 0)) or prices.get(symbol, 0) <= 0
                                 for symbol in quote_symbols):
            raise RuntimeError("部分实时价格缺失，停止本次实盘决策")

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
            # 持仓超时平仓（动量衰减）
            if getattr(self.cfg, "max_hold_days", 0):
                from datetime import date as _d
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                for sym in list(self.sim.state["positions"].keys()):
                    pos = self.sim.state["positions"][sym]
                    ot = str(pos.get("open_time", ""))[:10]
                    try:
                        if ot and (_d.fromisoformat(today) - _d.fromisoformat(ot)).days >= self.cfg.max_hold_days:
                            p = prices.get(sym, 0)
                            if p > 0:
                                self.sim.close_position(sym, p, "超时平仓")
                                logger.info("[SIM] 超时平仓: %s（持有 %d 天）",
                                            sym, (_d.fromisoformat(today) - _d.fromisoformat(ot)).days)
                    except ValueError:
                        pass
            # 资金费率结算（持仓过夜成本）
            self.sim.settle_funding(prices)
        elif self.live_manager:
            self.closed = self.live_manager.check_exits(all_ohlcv, latest_ts, now)

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
            opened = self._open_live_positions(candidates, prices, rs, now)
            self.live_manager.complete()
            self.portfolio_value = self.live_manager._balance().total_usdt

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
        """模拟开仓（集中持仓策略：top-K 信号 + 冷静期 + 单仓比例）"""
        if not candidates:
            return []
        n_slots  = max(rs.max_slots, 1)
        size_pct = min(rs.position_cap / n_slots, self.cfg.max_pos_pct)
        if getattr(self.cfg, "top_k_signals", 0):
            n_slots = min(n_slots, self.cfg.top_k_signals)
            size_pct = self.cfg.solo_pos_pct
        total_val = self.sim.get_balance(prices)["total"]
        opened = []
        for sig in candidates[:n_slots]:
            sym = sig["symbol"]
            if sym in self.sim.state["positions"]:
                continue
            # 冷静期：该币最近一笔止损在 cooldown_days 天内则跳过
            if getattr(self.cfg, "cooldown_days", 0):
                last_trade = None
                for t in reversed(self.sim.state["trades"]):
                    if t["symbol"] == sym:
                        last_trade = t
                        break
                if last_trade and "止损" in last_trade.get("reason", ""):
                    lt = last_trade["time"][:10]
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    try:
                        from datetime import date as _d
                        if (_d.fromisoformat(today) - _d.fromisoformat(lt)).days <= self.cfg.cooldown_days:
                            logger.info("[SIM] %s 冷静期内，跳过", sym)
                            continue
                    except ValueError:
                        pass
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

    def _open_live_positions(self, candidates, prices, rs, now=None) -> list[str]:
        """实盘与模拟沿用同一配置，实际成交及冷静期由本地状态管理器确认。"""
        if self.live_manager is None:
            raise RuntimeError("尚未完成实盘持仓检查")
        return self.live_manager.open_entries(candidates, prices, rs, now or datetime.now(timezone.utc))

    def _validate_live_data(self, ohlcv, funding, btc_df, latest_ts, now):
        from live.position_manager import utc_time
        required_bars = max(252, self.cfg.mom_long_bars + 10)
        expected = [(now - timedelta(days=day)).strftime("%Y-%m-%dT00:00:00Z")
                    for day in range(1, required_bars + 1)]
        if self.cfg.timeframe != "1d" or latest_ts != expected[0]:
            raise RuntimeError("实盘需要最新已收盘的 UTC 日线")
        for symbol, frame in [("BTC/USDT", btc_df), *ohlcv.items()]:
            if frame is None or frame.empty or not frame.index.is_unique or not set(expected).issubset(frame.index):
                raise RuntimeError(f"{symbol} 缺少连续 {required_bars} 根已收盘日线，停止实盘")
            if any(not math.isfinite(float(value)) or float(value) <= 0
                   for value in frame.loc[expected, "close"]):
                raise RuntimeError(f"{symbol} 收盘价格无效")
        for symbol in self.cfg.symbols:
            series = funding.get(symbol)
            if (series is None or series.empty or not series.index.is_unique
                    or not series.index.is_monotonic_increasing):
                raise RuntimeError(f"{symbol} 资金费率缺失")
            # Match momentum/funding_arb's as-of cutoff and nine-period average.
            recent = series[series.index <= latest_ts].iloc[-9:]
            times = [utc_time(timestamp) for timestamp in recent.index]
            if (len(recent) < 9 or utc_time(series.index[-1]) > now
                    or utc_time(latest_ts) - times[-1] > timedelta(hours=8)
                    or any(later - earlier > timedelta(hours=8) for earlier, later in zip(times, times[1:]))
                    or any(not math.isfinite(float(value)) for value in recent)):
                raise RuntimeError(f"{symbol} 策略截止时间的资金费率过期、不完整或无效")

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
            positions = [{"symbol": p.symbol, "side": p.side, "qty": p.contracts,
                          "entry": p.entry_price, "current": prices.get(p.symbol, p.current_price),
                          "pnl_pct": self._pos_pnl_pct({"side": p.side, "entry_price": p.entry_price},
                                                       prices.get(p.symbol, p.current_price))}
                         for p in self.live_manager.positions.values()]

        state = {
            "timestamp":    ts,
            "dry_run":      self.dry_run,
            "regime":       rs.regime,
            "portfolio":    round(portfolio_value, 2),
            "nav":          round(portfolio_value / (self.sim.initial if self.sim else self.portfolio_value), 4) if self.sim else 1.0,
            "positions":    positions,
            "opened":       opened,
            "closed":       self.closed,
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
        """推送数据到 GitHub（用 API，绕过 git protocol）
        国内服务器访问 github.com 超时，改用 api.github.com
        双轨模式：实盘机器设 SKIP_GITHUB_PUSH=1 跳过推送（数据推送只留给模拟盘服务器，避免互相覆盖）
        """
        import os
        if not self.dry_run or os.environ.get("SKIP_GITHUB_PUSH", "") == "1":
            logger.info("SKIP_GITHUB_PUSH=1，跳过数据推送（实盘节点不推数据）")
            return
        try:
            from live.github_push import push_data_files
            n = push_data_files(PROJECT_ROOT)
            if n > 0:
                logger.info("✅ 推送 %d 个文件到 GitHub", n)
            else:
                logger.info("无数据文件需要推送")
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
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                if not self.dry_run:
                    raise RuntimeError(f"行情更新失败：{result.stderr[:200]}")
                logger.warning("数据更新失败: %s", result.stderr[:200])
            else:
                logger.info("数据更新成功")
        except Exception as e:
            if not self.dry_run:
                raise
            logger.warning("数据更新异常: %s", e)
