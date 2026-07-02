"""
实盘主引擎
每日运行一次（建议 UTC 00:10，日线收盘后5分钟）

工作流程：
  1. 更新本地 SQLite 缓存（最新K线 + 资金费率）
  2. 运行信号生成（复用回测信号逻辑）
  3. 与当前实际持仓对比，计算需要开/平的仓位
  4. 执行订单
  5. 记录日志
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("live.engine")

STATE_FILE = Path(__file__).parent.parent.parent / "data" / "live_state.json"


class LiveEngine:
    """实盘交易引擎"""

    def __init__(self, cfg=None, dry_run: bool = True):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from config import CFG
        from live.exchange import BinanceExchange
        from agents.regime_agent import RegimeAgent
        from agents.risk_agent import RiskAgent
        from agents.signal_agent import SignalAgent
        from core.data_feed import CryptoDataFeed

        self.cfg      = cfg or CFG
        self.dry_run  = dry_run
        self.exchange = BinanceExchange(dry_run=dry_run, leverage=1)
        self.feed     = CryptoDataFeed()
        self.regime   = RegimeAgent(self.cfg)
        self.signals  = SignalAgent(self.cfg)

        # ── RiskAgent 以实际账户余额为起点（避免误判熔断）──────────────────
        # 不使用 cfg.cash（回测初始资金 10000 USDT），而是用实盘账户余额
        import dataclasses
        bal       = self.exchange.get_balance()
        live_cash = bal.total_usdt if bal.total_usdt > 10 else self.cfg.cash
        live_cfg  = dataclasses.replace(self.cfg, cash=live_cash)
        self.risk_ag = RiskAgent(live_cfg)

        logger.info("LiveEngine 初始化 | dry_run=%s", dry_run)

    def run_once(self):
        """运行一次完整的交易决策流程"""
        now = datetime.now(timezone.utc)
        ts  = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("=" * 60)
        logger.info("实盘运行 | %s | dry_run=%s", ts, self.dry_run)

        # ── Step 1: 更新数据 ──────────────────────────────────────────────
        self._update_data()

        # ── Step 2: 加载最新数据 ──────────────────────────────────────────
        end_date = now.strftime("%Y-%m-%d")
        start_date = "2022-01-01"   # 需要完整历史计算动量

        all_ohlcv   = self.feed.get_all_ohlcv(self.cfg.symbols, "1d", start_date, end_date)
        all_funding = self.feed.get_all_funding(self.cfg.symbols, start_date, end_date)
        btc_df      = self.feed.get_btc_ohlcv("1d", start_date, end_date)

        # 找到最新的时间戳（日线收盘时间戳）
        timestamps = self.feed.get_trade_timestamps("1d", start_date, end_date)
        if not timestamps:
            logger.error("无数据！请先运行 fetch_data.py")
            return

        latest_ts = timestamps[-1]
        logger.info("最新数据时间点: %s", latest_ts)

        # ── Step 3: Regime 识别 ───────────────────────────────────────────
        rs = self.regime.detect(btc_df, latest_ts)
        logger.info("Regime: %s | slots=%d | cap=%.0f%%",
                    rs.regime, rs.max_slots, rs.position_cap * 100)

        # ── Step 4: 风控等级 ──────────────────────────────────────────────
        bal      = self.exchange.get_balance()
        portfolio_value = bal.total_usdt
        level    = self.risk_ag.get_level(portfolio_value)
        logger.info("账户: %.2f USDT | 风控=%s", portfolio_value, level)

        # ── Step 5: 生成信号 ──────────────────────────────────────────────
        active  = [s for s, df in all_ohlcv.items() if not df.empty]
        targets = []   # 理论上应该持有的仓位列表

        if rs.max_slots > 0 and level not in ("CIRCUIT", "STOP"):
            candidates = self.signals.generate(
                active, all_ohlcv, all_funding, latest_ts, rs
            )

            n_slots  = max(rs.max_slots, 1)
            size_pct = min(rs.position_cap / n_slots, self.cfg.max_pos_pct)

            for sig in candidates[:n_slots]:
                targets.append({
                    "symbol":    sig["symbol"],
                    "direction": sig["direction"],
                    "size_usdt": portfolio_value * size_pct,
                    "score":     sig["score"],
                    "strategy":  sig["strategy"],
                })

        logger.info("信号: %d 个目标仓位", len(targets))
        for t in targets:
            dir_str = "做多↑" if t["direction"] > 0 else "做空↓"
            logger.info("  %s %s | %.0f USDT | score=%.3f",
                        dir_str, t["symbol"], t["size_usdt"], t["score"])

        # ── Step 6: 对比实际持仓，计算差值 ───────────────────────────────
        actual_positions = self.exchange.get_positions()
        actual_syms = {p.symbol: p for p in actual_positions}
        target_syms = {t["symbol"] for t in targets}

        # 应该平仓的（实际有仓但信号不再选）
        to_close = [p for sym, p in actual_syms.items() if sym not in target_syms]
        # 应该开仓的（信号选但实际没仓）
        to_open  = [t for t in targets if t["symbol"] not in actual_syms]

        logger.info("操作: 平仓 %d | 开仓 %d", len(to_close), len(to_open))

        # ── Step 7: 执行 ─────────────────────────────────────────────────
        # 先平仓，再开仓（释放资金）
        for pos in to_close:
            logger.info("平仓: %s (%s)", pos.symbol, pos.side)
            self.exchange.close_position(pos.symbol, pos.side)

        for t in to_open:
            sym  = t["symbol"]
            size = t["size_usdt"]
            self.exchange.set_leverage(sym, 1)  # 确保1x杠杆
            if t["direction"] > 0:
                self.exchange.open_long(sym, size)
            else:
                self.exchange.open_short(sym, size)

        # ── Step 8: 记录状态 ──────────────────────────────────────────────
        state = {
            "timestamp":    ts,
            "dry_run":      self.dry_run,
            "regime":       rs.regime,
            "risk_level":   level,
            "portfolio":    portfolio_value,
            "targets":      targets,
            "closed":       [p.symbol for p in to_close],
            "opened":       [t["symbol"] for t in to_open],
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.info("状态已保存: %s", STATE_FILE)
        logger.info("=" * 60)

    def _update_data(self):
        """增量更新本地 SQLite 缓存（只拉最新N条）"""
        logger.info("更新本地数据缓存...")
        try:
            import subprocess, sys
            python = sys.executable
            script = str(Path(__file__).parent.parent.parent / "scripts" / "fetch_data.py")
            # 只拉最近30天的增量数据
            from datetime import timedelta
            start = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
            result = subprocess.run(
                [python, script, "--all", "--start", start],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.warning("数据更新失败: %s", result.stderr[:200])
            else:
                logger.info("数据更新成功")
        except Exception as e:
            logger.warning("数据更新异常（继续使用缓存）: %s", e)
