"""Blender 可执行文件探测与选择（纯 Python，跨平台）。

Windows：注册表 Uninstall 键 + 常见安装目录 + PATH；
macOS：/Applications/Blender*.app；
Linux：shutil.which("blender")。

版本号从目录名/路径中的 "Blender x.y" 解析；解析失败按 0 处理。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass

_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class BlenderInstall:
    exe: str
    version: tuple[int, int, int] = (0, 0, 0)
    version_str: str = ""
    source: str = ""

    def __str__(self) -> str:  # pragma: no cover - 仅调试显示
        return f"Blender {self.version_str or '.'.join(map(str, self.version))} @ {self.exe}"


def parse_blender_version(text: str) -> tuple[int, int, int] | None:
    """从任意文本（路径/目录名/--version 输出）解析 Blender 版本。

    取文本中最后一个 "x.y(.z)" 形态的数字；"Blender 4.5" → (4,5,0)。
    """
    matches = list(_VER_RE.finditer(text or ""))
    if not matches:
        return None
    m = matches[-1]
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _registry_blender_entries() -> list[tuple[str, tuple[int, int, int] | None]]:
    """从 Windows 卸载表读取 Blender 安装目录及 DisplayVersion。

    返回 ``(InstallLocation, DisplayVersion 解析后的版本)``；DisplayVersion
    可能比目录名更精确（如目录是 ``Blender 5.2``，DisplayVersion 是 ``5.2.1``）。
    """
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return []
    entries: list[tuple[str, tuple[int, int, int] | None]] = []
    roots = [
        (winreg.HKEY_CURRENT_USER, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    ]
    uninstall_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for root, view in roots:
        try:
            with winreg.OpenKey(root, uninstall_path, 0, winreg.KEY_READ | view) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            display = ""
                            loc = ""
                            display_version = ""
                            try:
                                display = winreg.QueryValueEx(sub, "DisplayName")[0]
                            except OSError:
                                pass
                            try:
                                loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                            except OSError:
                                pass
                            try:
                                display_version = winreg.QueryValueEx(
                                    sub, "DisplayVersion")[0]
                            except OSError:
                                pass
                            if "blender" in (display or "").lower() and loc:
                                version = parse_blender_version(display_version)
                                entries.append((loc, version))
                    except OSError:
                        continue
        except OSError:
            continue
    return entries


def _registry_blender_dirs() -> list[str]:
    """从 Windows 卸载表读取 Blender 安装目录（含 32/64 位视图）。"""
    return [loc for loc, _ in _registry_blender_entries()]


def _registry_blender_version_map() -> dict[str, tuple[int, int, int]]:
    """把注册表安装目录规范化为 ``版本号`` 的映射。"""
    versions: dict[str, tuple[int, int, int]] = {}
    for loc, version in _registry_blender_entries():
        if version is None:
            continue
        key = os.path.normcase(os.path.normpath(os.path.abspath(loc)))
        versions[key] = version
    return versions


def discover_blender_exes() -> list[str]:
    """发现本机所有 Blender 可执行文件（去重保序）。"""
    found: list[str] = []
    candidates: list[str] = []

    if sys.platform == "win32":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            root = os.path.join(base, "Blender Foundation")
            if os.path.isdir(root):
                for name in sorted(os.listdir(root), reverse=True):
                    candidates.append(os.path.join(root, name))
        candidates.extend(_registry_blender_dirs())
    elif sys.platform == "darwin":
        apps = "/Applications"
        if os.path.isdir(apps):
            for name in sorted(os.listdir(apps), reverse=True):
                if name.lower().startswith("blender") and name.lower().endswith(".app"):
                    candidates.append(os.path.join(apps, name, "Contents", "MacOS", "Blender"))
    which = shutil.which("blender")
    if which:
        candidates.append(which)

    for cand in candidates:
        exe = cand
        if os.path.isdir(cand):
            probe = os.path.join(cand, "blender.exe") if sys.platform == "win32" else os.path.join(cand, "blender")
            if os.path.isfile(probe):
                exe = probe
            else:
                continue
        if os.path.isfile(exe) and exe not in found:
            found.append(exe)
    return found


def blender_installs(exes: list[str] | None = None) -> list[BlenderInstall]:
    """把可执行文件列表包装为 BlenderInstall（含解析版本），按版本降序。

    Windows 上优先使用注册表 ``DisplayVersion``，因为安装目录通常只写到
    ``Blender 5.2``，但实际补丁号可能是 ``5.2.1``。
    """
    registry_versions = _registry_blender_version_map()
    installs = []
    for exe in exes or discover_blender_exes():
        ver = parse_blender_version(os.path.dirname(exe) + os.sep + os.path.basename(exe))
        exe_dir = os.path.normcase(os.path.normpath(os.path.abspath(os.path.dirname(exe))))
        ver = registry_versions.get(exe_dir) or ver
        installs.append(
            BlenderInstall(
                exe=exe,
                version=ver or (0, 0, 0),
                version_str=".".join(map(str, ver)) if ver else "",
                source="override" if exes else "discovered",
            )
        )
    return sorted(installs, key=lambda i: i.version, reverse=True)


def pick_default(exes: list[str] | None = None) -> BlenderInstall | None:
    """选择版本最高的 Blender；无则返回 None。"""
    installs = blender_installs(exes)
    return installs[0] if installs else None
