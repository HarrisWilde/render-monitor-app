# AGENTS.md

本文件供后续人类/AI 开发者在修改本仓库前阅读。详细背景见 [README.md](README.md)。

## 项目是什么

Render Monitor Queue 渲染排队器：把 Blender-Render-Monitor 插件在 `.blend`
中创建好的“场景快照”拖入独立桌面应用，用后台 `blender -b` 子进程严格串行渲染。
技术栈：Python + PySide6 + Fluent-Widgets。

## 最关键的一条：上游插件同步

本仓库的 `vendor/render_monitor/` **不是独立维护的源码**，而是从上游仓库
**复制/同步**过来的 GPL 插件包：

- 上游仓库：https://github.com/HarrisWilde/Blender-Render-Monitor
- 同步说明与当前状态：见 [docs/upstream-sync.md](docs/upstream-sync.md)
- 当前状态：本地 vendor 代码版本为 **v1.5.7**；上游 master 已是 **v1.5.8**。

因此：

1. **上游更新逻辑后，这边必须同步**，不能只在本地“打补丁”式修改 vendor。
2. 不要直接大改 `vendor/render_monitor/` 内的文件。如果确需本地差异，
   必须记录到 `docs/upstream-sync.md` 的“本地补丁”清单，否则下次同步会被覆盖。
3. 上游同步不是简单复制文件。应用侧也复刻/依赖了上游的部分逻辑：
   - `src/rmqueue/render_session.py` 内嵌渲染脚本直接调用插件 API；
   - `src/rmqueue/progress.py`、`tile_progress.py`、`naming.py` 与上游
     `rm_job.py` / `utils.py` 的进度、分块、命名逻辑同源；
   - 快照字段、`data_json` 格式、状态机（PENDING/RENDERING/DONE/FAILED）、
     mmap 长度前缀协议若在上游改变，应用侧要一起核对。
4. 改动与渲染/快照/状态机/进度相关的代码前，先看 `docs/upstream-sync.md`，
   必要时对比上游最新代码。

## 常用命令

```powershell
.\.venv\Scripts\python -m pytest -q          # 纯逻辑单测
.\.venv\Scripts\python tests\ui_smoke.py     # UI offscreen smoke
.\.venv\Scripts\python tests\smoke_probe.py --all     # 需要真实 Blender 的枚举 E2E
.\.venv\Scripts\python tests\render_e2e.py --all      # 需要真实 Blender 的渲染 E2E
```

## 目录速览

- `src/rmqueue/`：应用本体（模型、Blender 子进程编排、Fluent UI）
- `vendor/render_monitor/`：上游插件 vendored 副本（同步对象）
- `docs/upstream-sync.md`：上游同步流程与当前漂移状态
- `tests/`：单测 / smoke / E2E
