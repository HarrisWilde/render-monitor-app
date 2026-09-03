"""GitHub Release 自动更新检查（纯逻辑 + 标准库 HTTP，不依赖 Qt）。

- 默认走系统代理：有系统代理/环境代理就用代理，没有就直连；
- 优先用 GitHub 网页 `releases/latest` 的重定向地址识别最新 tag，
  避免 GitHub API 未认证 60 次/小时/IP 的 403 限流；
- 只做“检测 + Release 页面地址定位”，实际安装仍由用户运行安装包。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

GITHUB_REPO = "HarrisWilde/render-monitor-app"
GITHUB_API = "https://api.github.com/repos"
GITHUB_WEB = "https://github.com"
USER_AGENT = "RenderMonitorQueue-Updater/0.2.1"


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


def _build_opener():
    """按系统/环境代理构建 opener；没有代理则直连。"""
    proxies = urllib.request.getproxies()
    if proxies:
        return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(url: str, timeout: float):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _release_tag_from_url(url: str) -> str:
    """从 GitHub release 页面 URL 中提取 tag，如 .../releases/tag/v0.2.0。"""
    marker = "/releases/tag/"
    if marker in url:
        tag = url.split(marker, 1)[1].split("?", 1)[0].strip("/")
        if tag:
            return tag
    raise UpdateCheckError(f"无法从 GitHub 页面识别最新版本：{url}")


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    """尽量读出 HTTPError 响应体，便于向用户展示 403 等真实原因。"""
    try:
        raw = exc.read().decode("utf-8", errors="replace").strip()
        if not raw:
            return "无响应内容"
        # 只保留第一行/最关键的 message，避免一长串 HTML 刷屏
        line = raw.splitlines()[0].strip()
        return line[:300]
    except Exception:  # noqa: BLE001
        return "无响应内容"


def fetch_latest_release_page(
    repo: str = GITHUB_REPO,
    timeout: float = 8.0,
) -> dict:
    """通过 GitHub 网页 releases/latest 重定向获取最新 Release 信息。

    这个入口不依赖 GitHub API，不会触发未认证 API 的 60 次/小时限流。
    返回 {"tag_name": ..., "html_url": ...}。
    """
    url = f"{GITHUB_WEB}/{repo}/releases/latest"
    opener = _build_opener()
    try:
        with opener.open(_request(url, timeout), timeout=timeout) as resp:
            final_url = str(resp.geturl())
        tag = _release_tag_from_url(final_url)
        return {"tag_name": tag, "html_url": final_url}
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(
            f"GitHub 返回 HTTP {exc.code}：{_http_error_body(exc)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"无法连接 GitHub：{exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"读取更新信息失败：{exc}") from exc


def fetch_latest_release(
    repo: str = GITHUB_REPO,
    timeout: float = 8.0,
) -> dict:
    """获取 GitHub 最新正式 Release 的 JSON 数据。"""
    url = f"{GITHUB_API}/{repo}/releases/latest"
    opener = _build_opener()
    try:
        with opener.open(_request(url, timeout), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(
            f"GitHub 返回 HTTP {exc.code}：{_http_error_body(exc)}"
        ) from exc
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
    release = fetch_latest_release_page(repo, timeout=timeout)
    tag = str(release.get("tag_name") or "")
    latest_version = ".".join(str(p) for p in parse_version(tag))
    return {
        "ok": True,
        "current_version": current_version,
        "latest_tag": tag,
        "latest_version": latest_version,
        "update_available": is_newer(tag, current_version),
        "html_url": str(release.get("html_url") or ""),
        "asset": None,  # 网页入口只负责检测；下载统一从 Release 页面进入
        "published_at": "",
    }
