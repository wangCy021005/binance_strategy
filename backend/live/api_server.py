"""
轻量级 Flask API 服务
为前端 Dashboard 提供数据接口

用法：
  python scripts/serve_web.py          # 默认 http://localhost:5555
  python scripts/serve_web.py --port 8080

端点：
  GET /               → 返回 index.html
  GET /api/stats      → 回测统计 (Sharpe/收益/MaxDD)
  GET /api/equity     → 净值曲线
  GET /api/trades     → 近期交易记录
  GET /api/regime     → Regime 分布
  GET /api/live       → 实盘状态（live_state.json）
  GET /api/signals    → 当前信号（实时计算）
"""
from __future__ import annotations
import json
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, abort

logger = logging.getLogger("api_server")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR))


def _load_latest() -> dict:
    p = DATA_DIR / "latest.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _load_live_state() -> dict:
    p = DATA_DIR / "live_state.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


# ── 页面路由 ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(FRONTEND_DIR), filename)


# ── API 路由 ──────────────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    data = _load_latest()
    stats = data.get("stats", {})
    meta  = data.get("meta",  {})
    return jsonify({
        "annual_return":  stats.get("annual_return", 0),
        "total_return":   stats.get("total_return",  0),
        "sharpe":         stats.get("sharpe",         0),
        "max_drawdown":   stats.get("max_drawdown",   0),
        "total_trades":   stats.get("total_trades",   0),
        "win_rate":       stats.get("win_rate",       0),
        "start":          meta.get("start", ""),
        "end":            meta.get("end",   ""),
        "symbols_count":  len(meta.get("symbols", [])),
        "last_updated":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    })


@app.route("/api/equity")
def api_equity():
    data   = _load_latest()
    equity = data.get("equity", [])
    # 返回简化格式（时间 + NAV）
    return jsonify([
        {"t": e["time"][:10], "nav": round(e["nav"], 4)}
        for e in equity
    ])


@app.route("/api/trades")
def api_trades():
    data   = _load_latest()
    trades = data.get("trades", [])
    # 只返回有 pnl_pct 的平仓记录，最近 50 笔
    closed = [
        {
            "time":   t["time"][:10],
            "symbol": t.get("symbol", ""),
            "side":   t.get("side",   ""),
            "pnl":    round(t.get("pnl_pct", 0) * 100, 2),
            "reason": t.get("reason", "")[:30],
        }
        for t in trades if "pnl_pct" in t
    ]
    return jsonify(closed[-50:])


@app.route("/api/regime")
def api_regime():
    data = _load_latest()
    dist = data.get("regime_dist", {})
    return jsonify(dist)


@app.route("/api/live")
def api_live():
    state = _load_live_state()
    return jsonify({
        "timestamp":    state.get("timestamp", "—"),
        "dry_run":      state.get("dry_run", True),
        "regime":       state.get("regime", "—"),
        "risk_level":   state.get("risk_level", "—"),
        "portfolio":    state.get("portfolio", 0),
        "targets":      state.get("targets", []),
        "opened":       state.get("opened", []),
        "closed":       state.get("closed", []),
    })


@app.route("/api/signals")
def api_signals():
    """实时计算当前信号（用最新数据）"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "backend"))
        from config import CFG
        from core.data_feed import CryptoDataFeed
        from agents.regime_agent import RegimeAgent
        from agents.signal_agent import SignalAgent

        feed    = CryptoDataFeed()
        regime  = RegimeAgent(CFG)
        signals = SignalAgent(CFG)

        end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = "2022-01-01"

        all_ohlcv   = feed.get_all_ohlcv(CFG.symbols, "1d", start, end)
        all_funding = feed.get_all_funding(CFG.symbols, start, end)
        btc_df      = feed.get_btc_ohlcv("1d", start, end)
        timestamps  = feed.get_trade_timestamps("1d", start, end)

        if not timestamps:
            return jsonify({"error": "无数据"})

        latest_ts  = timestamps[-1]
        rs         = regime.detect(btc_df, latest_ts)
        active     = [s for s, df in all_ohlcv.items() if not df.empty]
        candidates = signals.generate(active, all_ohlcv, all_funding, latest_ts, rs)

        return jsonify({
            "as_of":    latest_ts[:10],
            "regime":   rs.regime,
            "slots":    rs.max_slots,
            "cap_pct":  round(rs.position_cap * 100),
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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run(port: int = 5555, debug: bool = False):
    logger.info("Dashboard: http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
