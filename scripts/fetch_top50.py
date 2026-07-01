"""
Top 50 市值币数据采集脚本
从 Binance 拉取 OHLCV（现货）+ 资金费率（永续合约）

用法：
  python scripts/fetch_top50.py           # 仅采集新增币种
  python scripts/fetch_top50.py --all     # 全部重新采集
  python scripts/fetch_top50.py --check   # 仅检查覆盖情况

新增约 25 只币，目标 45 只总宇宙（+ BTC 仅用于 Regime 检测）
"""
import sys, sqlite3, time, argparse, logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import ccxt
from config import DB_PATH
from core.data_feed import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("fetch_top50")

# ── 目标宇宙 ────────────────────────────────────────────────────────────────
# 格式: (ccxt_symbol, 上市大约时间)，早于2022的均从2022-01-01开始拉
UNIVERSE = [
    # ─── 已有，用于验证数据完整性 ───────────────────────────────────────────
    ("ETH/USDT",   "2022-01-01"),
    ("SOL/USDT",   "2022-01-01"),
    ("BNB/USDT",   "2022-01-01"),
    ("XRP/USDT",   "2022-01-01"),
    ("ADA/USDT",   "2022-01-01"),
    ("AVAX/USDT",  "2022-01-01"),
    ("DOT/USDT",   "2022-01-01"),
    ("ATOM/USDT",  "2022-01-01"),
    ("TRX/USDT",   "2022-01-01"),
    ("DOGE/USDT",  "2022-01-01"),
    ("LINK/USDT",  "2022-01-01"),
    ("UNI/USDT",   "2022-01-01"),
    ("AAVE/USDT",  "2022-01-01"),
    ("NEAR/USDT",  "2022-01-01"),
    ("INJ/USDT",   "2022-01-01"),
    ("FET/USDT",   "2022-01-01"),
    ("LTC/USDT",   "2022-01-01"),
    ("ARB/USDT",   "2023-03-23"),
    ("OP/USDT",    "2022-06-01"),
    ("MATIC/USDT", "2022-01-01"),
    ("BTC/USDT",   "2022-01-01"),   # Regime 检测用

    # ─── 新增 Tier-1 L1/L2（大市值）────────────────────────────────────────
    ("SUI/USDT",   "2023-05-03"),   # Sui 主网上线
    ("APT/USDT",   "2022-10-17"),   # Aptos 主网上线
    ("TON/USDT",   "2023-06-01"),   # Telegram 生态
    ("ICP/USDT",   "2022-01-01"),   # Internet Computer
    ("ETC/USDT",   "2022-01-01"),   # Ethereum Classic

    # ─── 新增 AI / GPU 主题 ─────────────────────────────────────────────────
    ("RNDR/USDT",  "2022-01-01"),   # Render Network (GPU 算力)
    ("WLD/USDT",   "2023-07-24"),   # Worldcoin (Sam Altman)

    # ─── 新增 DeFi 蓝筹 ──────────────────────────────────────────────────────
    ("LDO/USDT",   "2022-01-01"),   # Lido DAO（流动性质押龙头）
    ("MKR/USDT",   "2022-01-01"),   # MakerDAO
    ("GRT/USDT",   "2022-01-01"),   # The Graph（索引协议）
    ("ENA/USDT",   "2024-04-02"),   # Ethena（合成美元收益）

    # ─── 新增 Meme 高波动 ──────────────────────────────────────────────────
    ("SHIB/USDT",  "2022-01-01"),   # Shiba Inu
    ("PEPE/USDT",  "2023-05-05"),   # Pepe
    ("WIF/USDT",   "2023-12-14"),   # Dogwifhat（Solana meme）
    ("BONK/USDT",  "2022-12-30"),   # Bonk（Solana meme）
    ("FLOKI/USDT", "2022-01-01"),   # Floki

    # ─── 新增 其他 L1 ────────────────────────────────────────────────────────
    ("XLM/USDT",   "2022-01-01"),   # Stellar（跨境支付）
    ("ALGO/USDT",  "2022-01-01"),   # Algorand
    ("HBAR/USDT",  "2022-01-01"),   # Hedera Hashgraph
    ("VET/USDT",   "2022-01-01"),   # VeChain（企业区块链）
    ("FIL/USDT",   "2022-01-01"),   # Filecoin（去中心化存储）
    ("STX/USDT",   "2022-01-01"),   # Stacks（Bitcoin L2）
    ("SEI/USDT",   "2023-08-15"),   # Sei Network
    ("TIA/USDT",   "2023-10-31"),   # Celestia（模块化区块链）

    # ─── 新增 Solana 生态 ────────────────────────────────────────────────────
    ("JTO/USDT",   "2023-12-07"),   # Jito（Solana MEV/质押）
    ("PYTH/USDT",  "2023-11-20"),   # Pyth Network（价格预言机）

    # ─── 新增 其他 ──────────────────────────────────────────────────────────
    ("CRO/USDT",   "2022-01-01"),   # Cronos（Crypto.com）
    ("EGLD/USDT",  "2022-01-01"),   # MultiversX（前 Elrond）
    ("SAND/USDT",  "2022-01-01"),   # The Sandbox（元宇宙）
    ("SNX/USDT",   "2022-01-01"),   # Synthetix
]

# ── 数据获取函数 ─────────────────────────────────────────────────────────────
def get_spot_ex():
    return ccxt.binance({"enableRateLimit": True, "options": {"fetchMarkets": ["spot"]}})

def get_futures_ex():
    return ccxt.binanceusdm({"enableRateLimit": True})

def fetch_ohlcv(symbol: str, start: str, timeframe: str = "1d"):
    """拉取现货日线 OHLCV，存入 SQLite"""
    sym_db = symbol.replace("/", "")
    exchange = get_spot_ex()
    since_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_bars = []
    while True:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
        except Exception as e:
            logger.warning("  OHLCV 失败 %s: %s", symbol, e)
            return 0
        if not bars:
            break
        all_bars.extend(bars)
        since_ms = bars[-1][0] + exchange.parse_timeframe(timeframe) * 1000
        if len(bars) < 1000:
            break
        time.sleep(0.3)

    if not all_bars:
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = []
    for b in all_bars:
        ts = datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data.append((sym_db, timeframe, ts, float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])))
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv (symbol,timeframe,open_time,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
        data
    )
    conn.commit(); conn.close()
    return len(data)


def fetch_funding(symbol: str, start: str):
    """拉取永续合约资金费率，存入 SQLite"""
    sym_db = symbol.replace("/", "")
    exchange = get_futures_ex()
    since_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_rates = []
    while True:
        try:
            rates = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=1000)
        except Exception as e:
            logger.warning("  资金费率失败 %s: %s", symbol, e)
            return 0
        if not rates:
            break
        all_rates.extend(rates)
        since_ms = rates[-1]["timestamp"] + 1
        if len(rates) < 1000:
            break
        time.sleep(0.3)

    if not all_rates:
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    data = []
    for r in all_rates:
        ts = datetime.fromtimestamp(r["timestamp"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data.append((sym_db, ts, float(r.get("fundingRate", 0) or 0)))
    conn.executemany(
        "INSERT OR REPLACE INTO funding_rate (symbol, funding_time, funding_rate) VALUES (?,?,?)",
        data
    )
    conn.commit(); conn.close()
    return len(data)


def check_coverage():
    """打印当前数据库覆盖情况"""
    conn = sqlite3.connect(str(DB_PATH))
    ohlcv = {r[0]: r[1] for r in conn.execute(
        "SELECT symbol, COUNT(*) FROM ohlcv WHERE timeframe='1d' GROUP BY symbol"
    ).fetchall()}
    funding = {r[0]: r[1] for r in conn.execute(
        "SELECT symbol, COUNT(*) FROM funding_rate GROUP BY symbol"
    ).fetchall()}
    conn.close()

    target_syms = [sym.replace("/", "") for sym, _ in UNIVERSE]
    print(f"\n覆盖检查 ({len(target_syms)} 个目标品种):")
    missing_ohlcv = []
    missing_fund  = []
    for s in target_syms:
        o = ohlcv.get(s, 0)
        f = funding.get(s, 0)
        status = "✅" if o >= 200 else "⚠️"
        fund_status = "✅" if f >= 100 else "❌"
        if o < 200: missing_ohlcv.append(s)
        if f < 100: missing_fund.append(s)
        print(f"  {status} {s:<12} OHLCV={o:4d}根  资金费率={fund_status}{f:4d}条")
    print(f"\n缺少 OHLCV: {len(missing_ohlcv)} 个")
    print(f"缺少资金费率: {len(missing_fund)} 个")
    return missing_ohlcv, missing_fund


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all",   action="store_true", help="全量重新采集")
    parser.add_argument("--check", action="store_true", help="仅检查覆盖情况")
    parser.add_argument("--ohlcv-only", action="store_true", help="仅采集 OHLCV")
    args = parser.parse_args()

    init_db()

    if args.check:
        check_coverage()
        return

    missing_ohlcv, missing_fund = check_coverage()

    if args.all:
        # 全量采集
        targets = UNIVERSE
    else:
        # 仅采集缺失的
        existing_ohlcv = {sym.replace("/", "") for sym, _ in UNIVERSE} - set(missing_ohlcv)
        targets = [(sym, start) for sym, start in UNIVERSE
                   if sym.replace("/", "") in missing_ohlcv or sym.replace("/", "") in missing_fund]
        if not targets:
            logger.info("所有数据已完整，无需采集！")
            check_coverage()
            return

    logger.info("开始采集 %d 个品种...", len(targets))
    total_ohlcv = total_fund = 0

    for symbol, start in targets:
        sym_db = symbol.replace("/", "")
        logger.info("── %s (from %s) ──", symbol, start)

        # OHLCV
        n = fetch_ohlcv(symbol, start)
        logger.info("  OHLCV: %d 根", n)
        total_ohlcv += n
        time.sleep(0.5)

        # 资金费率（永续合约才有）
        if not args.ohlcv_only:
            n = fetch_funding(symbol, start)
            logger.info("  资金费率: %d 条", n)
            total_fund += n
            time.sleep(0.5)

    logger.info("\n完成！OHLCV=%d根  资金费率=%d条", total_ohlcv, total_fund)
    check_coverage()


if __name__ == "__main__":
    main()
