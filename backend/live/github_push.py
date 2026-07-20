"""
GitHub API 文件推送（绕过 git protocol）
国内服务器访问 github.com 超时，但 api.github.com 可达
用 Contents API 直接更新文件

用法：
  from live.github_push import push_files_to_github
  push_files_to_github({
      "data/latest.json":   open("data/latest.json").read(),
      "data/sim_account.json": open("data/sim_account.json").read(),
  })
"""
from __future__ import annotations
import os
import base64
import logging
import requests
from typing import Optional

logger = logging.getLogger("live.github")

API_BASE = "https://api.github.com"
OWNER    = "wangCy021005"
REPO     = "binance_strategy"
BRANCH   = "main"


def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    if not token:
        # 从 ~/.git-credentials 读取
        cred_file = os.path.expanduser("~/.git-credentials")
        if os.path.exists(cred_file):
            content = open(cred_file).read()
            # 格式 https://user:token@github.com
            if "ghp_" in content:
                token = content.split("ghp_")[1].split("@")[0]
                token = "ghp_" + token
    return token


def _get_file_sha(path: str, token: str) -> Optional[str]:
    """获取文件当前 sha（更新文件需要）"""
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/contents/{path}"
    try:
        r = requests.get(url, headers={"Authorization": f"token {token}"},
                          params={"ref": BRANCH}, timeout=30)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception as e:
        logger.debug("get sha %s 失败: %s", path, e)
    return None


def push_file(path: str, content: str, commit_msg: str = "data update") -> bool:
    """推送单个文件到 GitHub"""
    token = _get_token()
    if not token:
        logger.warning("无 GitHub token，跳过")
        return False

    sha = _get_file_sha(path, token)
    url = f"{API_BASE}/repos/{OWNER}/{REPO}/contents/{path}"

    payload = {
        "message":    commit_msg,
        "content":     base64.b64encode(content.encode()).decode(),
        "branch":      BRANCH,
    }
    if sha:
        payload["sha"] = sha   # 更新已有文件需要 sha

    try:
        r = requests.put(url, headers={"Authorization": f"token {token}"},
                          json=payload, timeout=60)
        if r.status_code in (200, 201):
            logger.info("✅ GitHub push 成功: %s", path)
            return True
        else:
            logger.warning("GitHub push %s 失败: %s %s",
                           path, r.status_code, r.text[:200])
            return False
    except Exception as e:
        logger.error("GitHub push 异常 %s: %s", path, e)
        return False


def push_files_to_github(files: dict, commit_msg: str = "data: 自动更新") -> int:
    """
    批量推送文件
    files: {path: content}
    返回成功数
    """
    success = 0
    for path, content in files.items():
        if push_file(path, content, commit_msg):
            success += 1
    return success


def push_data_files(project_root) -> int:
    """推送 data/ 目录下的 JSON 文件"""
    from pathlib import Path
    data_dir = Path(project_root) / "data"
    files = {}
    for name in ["latest.json", "live_state.json", "live_signals.json", "sim_account.json"]:
        f = data_dir / name
        if f.exists():
            files[f"data/{name}"] = f.read_text()

    if not files:
        return 0

    from datetime import datetime, timezone
    msg = f"data: 模拟交易更新 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    return push_files_to_github(files, msg)
