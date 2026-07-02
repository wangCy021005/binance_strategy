"""
启动 Dashboard Web 服务

用法：
  python scripts/serve_web.py          # http://localhost:5555
  python scripts/serve_web.py --port 8080
"""
import sys, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

parser = argparse.ArgumentParser()
parser.add_argument("--port",  type=int, default=5555)
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()

from live.api_server import run
print(f"\n🌐 Dashboard 已启动: http://localhost:{args.port}")
print("   Ctrl+C 停止\n")
run(port=args.port, debug=args.debug)
