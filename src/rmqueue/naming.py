"""输出路径/文件命名（应用层模板，纯逻辑可测试）。

模板占位符：
  {file}   .blend 文件名（去扩展名，可作子目录段，如 a/b）
  {scene}  场景名（可含 / 作为子目录分隔）
  {name}   快照名
  {index}  渲染队列中的序号（从 1 开始，UI 扁平顺序）
  {frame}  渲染帧号（渲染时才知道，命名时可省略或给默认 0）

安全语义：所有来自用户/场景的段都按文件名规则清洗（跨平台非法字符 →
下划线；空白 → 下划线；段为 .. / 空 / 绝对路径都逃不出去）；`/` 保留为
子目录分隔。模板不含任何动态占位符时回退默认模板，避免互相覆盖。
"""

from __future__ import annotations

import os
import re

DEFAULT_FILE_TEMPLATE = "{file}/{scene}/{name} {index}"

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_segment(name: str) -> str:
    """把单个路径段清洗成安全文件名（不含 / 与 \\）。"""
    cleaned = _INVALID_CHARS.sub("_", str(name))
    cleaned = re.sub(r"\s+", "_", cleaned)
    # 连续非法字符/空白折叠为单个下划线，避免 "e?\\"f" → "e__f"
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if cleaned in ("", ".", ".."):
        cleaned = "shot"
    return cleaned[:120]


def sanitize_relpath(path: str) -> str:
    """清洗整个相对路径；`\\` 归一化为 `/`；段级防穿越。

    `..` / `.` / 空段整体丢弃，杜绝逃出输出目录。
    """
    if not path:
        return "shot"
    normalized = str(path).replace("\\", "/")
    parts = []
    for part in normalized.split("/"):
        if part in ("", ".", ".."):
            continue
        clean = sanitize_segment(part)
        if clean not in ("", "."):
            parts.append(clean)
    if not parts:
        return "shot"
    return "/".join(parts)


def _format_int(value, spec: str | None) -> str:
    """把 index/frame 按格式说明（如 :02d）格式化；非法时回退原整数。"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    if spec:
        try:
            return format(value, spec)
        except ValueError:
            pass
    return str(value)


def _apply(template: str, file_key: str, scene: str, name: str,
           index: int | str, frame: int | str) -> str:
    index_part = re.sub(r"\{index:([^}]*)\}", "", template)
    # 分别用普通/带格式两种方式尝试，保证 {index:02d} 等也能命中
    # 简单起见：先把所有占位符按无格式展开一次，有格式的留在原地再处理。
    raw = template
    raw = raw.replace("{file}", file_key)
    raw = raw.replace("{scene}", scene)
    raw = raw.replace("{name}", name)

    def _idx_repl(m: re.Match) -> str:
        return _format_int(index, m.group(1))

    def _frm_repl(m: re.Match) -> str:
        return _format_int(frame, m.group(1))

    raw = re.sub(r"\{index:([^}]*)\}", _idx_repl, raw)
    raw = re.sub(r"\{frame:([^}]*)\}", _frm_repl, raw)
    raw = raw.replace("{index}", str(index))
    raw = raw.replace("{frame}", str(frame))
    return raw


def format_output_relpath(
    template: str,
    blend_file: str,
    scene: str,
    shot_name: str,
    index: int = 1,
    frame: int | None = None,
) -> str:
    """按模板生成安全的输出相对路径（/ 分隔，可含子目录）。

    frame 为 None 时（渲染前预览/碰撞检测）帧号按 0 处理。
    """
    tpl = (template or DEFAULT_FILE_TEMPLATE).strip()
    if not any(token in tpl for token in ("{file}", "{scene}", "{name}", "{index}", "{frame}")):
        tpl = DEFAULT_FILE_TEMPLATE
    base = os.path.basename(str(blend_file) or "")
    if base.lower().endswith(".blend"):
        base = base[: -len(".blend")]
    file_key = sanitize_segment(base) or "file"
    raw = _apply(tpl, file_key, sanitize_segment(scene),
                 sanitize_relpath(shot_name), index, 0 if frame is None else frame)
    return sanitize_relpath(raw)


def build_abs_output_path(outdir: str, relpath: str, ext: str) -> str:
    """拼接输出目录 + 相对路径 + 扩展名（绝对、规范化）。"""
    ext = (ext or "png").lstrip(".").lower()
    return os.path.normpath(os.path.join(outdir, relpath + "." + ext))


def collision_pairs(relpaths: list[str]) -> list[tuple[int, int]]:
    """检测输出相对路径重复的索引对（索引即扁平队列位置）。

    模板含 {frame} 时最终帧号各异，这里无法预知，跳过检测（返回空）。
    """
    if not relpaths:
        return []
    pairs = []
    seen: dict[str, int] = {}
    for i, p in enumerate(relpaths):
        if p in seen:
            pairs.append((seen[p], i))
        else:
            seen[p] = i
    return pairs
