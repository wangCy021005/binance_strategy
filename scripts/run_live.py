"""
实盘运行入口
建议每天 UTC 00:10 运行（日线收盘5分钟后）

用法：
  # 模拟模式（不发真实订单，安全测试）
  python scripts/run_live.py --dry-run

  # 实盘模式（需要设置 API KEY）
  export BINANCE_API_KEY=your_key
  export BINANCE_API_SECRET=your_secret
  python scripts/run_live.py

  # 设置定时任务（每天 UTC 00:10 自动运行）
  crontab -e
  10 0 * * * cd /Users/wangcy/binance_strategy && /path/to/python scripts/run_live.py >> logs/live.log 2>&1

注意：
  - 首次运行前务必用 --dry-run 验证逻辑正确
  - 初期建议只用 100-500 USDT 测试（在 Binance 账户中单独划一个小合约账户）
  - 默认1x杠杆，最大亏损 = 单笔仓位大小（不会爆仓）
"""
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# 设置日志
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "live.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("run_live")


def main():
    parser = argparse.ArgumentParser(description="币安量化实盘交易")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="模拟模式（默认）：不发真实订单")
    parser.add_argument("--live", action="store_true",
                        help="实盘模式（需要 API KEY）")
    args = parser.parse_args()

    dry_run = not args.live
    if dry_run:
        logger.info("🟡 DRY_RUN 模式 — 不会发出真实订单")
        logger.info("   实盘模式请加 --live 参数（并确保已设置 API KEY）")
    else:
        logger.info("🔴 实盘模式 — 会发出真实订单！")
        # 确认提示
        import os
        if not os.environ.get("BINANCE_API_KEY"):
            logger.error("缺少 BINANCE_API_KEY 环境变量，退出")
            sys.exit(1)

    try:
        from live.live_engine import LiveEngine
        engine = LiveEngine(dry_run=dry_run)
        engine.run_once()
        logger.info("✅ 本次运行完成")
    except Exception as e:
        logger.exception("❌ 运行出错: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
