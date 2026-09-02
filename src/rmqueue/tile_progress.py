"""单张渲染进度 = 已完成块像素权重 + 当前块按采样比例插值（与插件 rm_job 一致）。

设计要点（对齐插件历史修复）：
- 多分块时若只按“当前块采样/总采样”计算会卡在第一块，这里对每个分块按
  Cycles 行优先顺序累加真实像素权重（边缘块更小，权重也随之更小）；
- 块完成瞬间 stats 的 Sample 残留上一块满值而 Rendered X/Y 已 +1：此时
  必须跳过插值（cur == total），否则同一块被重复计入导致进度跳变；
- 返回的新进度只允许单调不减，调用方若收到 None 则不更新。
"""

from __future__ import annotations


def shot_progress(
    cur: int,
    samples_total: int,
    tiles_done: int,
    tiles_total: int,
    weights: list[float],
    prev: float,
) -> float | None:
    """返回更新后的进度（0..1）；不需要更新时返回 None。

    参数含义与 render_stats 对应：cur=当前采样、samples_total=当前块总采样、
    tiles_done/tiles_total=已完成块数/总块数、weights=各块像素权重（和为 1）。
    """
    ttl = samples_total
    td = tiles_done
    tt = tiles_total
    if ttl > 0 and cur < ttl:
        # 当前块仍在采样：正常插值
        if len(weights) == tt and tt > 1:
            done_w = sum(weights[:td])
            cur_w = weights[td] if td < len(weights) else 0.0
            prog = done_w + cur_w * (cur / ttl)
        elif tt > 1:
            prog = (td + cur / ttl) / tt
        else:
            prog = cur / ttl
        return min(max(prog, 0.0), 1.0) if prog > prev else None
    if tt > 1 and td and not ttl:
        # 无采样信息（非 Cycles / 统计缺失）：按块等权近似
        prog = td / tt
        return min(max(prog, 0.0), 1.0) if prog > prev else None
    return None
