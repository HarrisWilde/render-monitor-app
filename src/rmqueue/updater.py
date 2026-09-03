"""GitHub Release 自动更新检查（纯逻辑 + 标准库 HTTP，不依赖 Qt）。

- 请求 GitHub `releases/latest`，与当前应用版本比较；
- 只做“检测 + 下载地址定位”，实际安装仍由用户运行安装包。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

GITHUB_REPO = "HarrisWilde/render-monitor-app"
GITHUB_API = "https://api.github.com/repos"
USER_AGENT = "RenderMonitorQueue-Updater/0.2"


class UpdateCheckError(RuntimeError):
    """更新检查失败（网络/API/解析等）。"""


def parse_version(text: str) -> tuple[int, ...]:
    """把 'v0.1.1'、'0.1.1' 等版本号解析为可比较整数元组。

    只比较数字点分部分；后缀（如 -beta1）暂不影响大小判断。
    """
    raw = str(text or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", raw.split("-", 1)[0].split("+", 1)[0])
    if not parts:
        raise ValueError(f"无法解析版本号: {text!r}")
    return tuple(int(p) for p in parts)


def is_newer(latest_tag: str, current_version: str) -> bool:
    """latest_tag 是否比 current_version 新。"""
    return parse_version(latest_tag) > parse_version(current_version)


def fetch_latest_release(
    repo: str = GITHUB_REPO,
    timeout: float = 8.0,
) -> dict:
    """获取 GitHub 最新正式 Release 的 JSON 数据。"""
    url = f"{GITHUB_API}/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(f"GitHub 返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"无法连接 GitHub：{exc.reason}") from exc
    except (TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(f"读取更新信息失败：{exc}") from exc


def find_setup_asset(release: dict) -> dict | None:
    """从 Release assets 中挑选 Windows 安装包。"""
    target = "Setup-"
    for asset in release.get("assets", []) or []:
        name = str(asset.get("name") or "")
        if name.endswith(".exe") and target in name:
            return asset
    return None


def check_latest_release(
    current_version: str,
    repo: str = GITHUB_REPO,
    timeout: float = 8.0,
) -> dict:
    """执行一次完整检查。

    返回结构：
    {
        "ok": True,
        "current_version": ...,
        "latest_tag": ...,
        "latest_version": ...,
        "update_available": bool,
        "html_url": ...,
        "asset": dict | None,
        "published_at": ...,
    }
    网络/API 失败时抛出 UpdateCheckError。
    """
    release = fetch_latest_release(repo, timeout=timeout)
    tag = str(release.get("tag_name") or release.get("name") or "")
    latest_version = ".".join(str(p) for p in parse_version(tag))
    return {
        "ok": True,
        "current_version": current_version,
        "latest_tag": tag,
        "latest_version": latest_version,
        "update_available": is_newer(tag, current_version),
        "html_url": str(release.get("html_url") or release.get("url") or ""),
        "asset": find_setup_asset(release),
        "published_at": str(release.get("published_at") or ""),
    }
