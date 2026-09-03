# 上游同步指南：Blender-Render-Monitor → Render Monitor Queue

本仓库的 `vendor/render_monitor/` 是从
[HarrisWilde/Blender-Render-Monitor](https://github.com/HarrisWilde/Blender-Render-Monitor)
复制的 Blender 插件包。该插件继续演进时，本应用依赖的快照数据结构、渲染状态机、
进度协议、命名/清洗逻辑都可能变化，因此需要**有意识地同步**。

> 给 Agent 的硬规则：不要把 `vendor/render_monitor/` 当作本仓库独有的源码来改。
> 上游更新后应走下面的同步流程；应用侧同源逻辑也要一并检查。

## 当前同步状态（2026-09-03 检查）

| 项目 | 值 |
| --- | --- |
| 上游仓库 | https://github.com/HarrisWilde/Blender-Render-Monitor |
| 上游默认分支 | `master` |
| 上游最新 master 提交 | `284290623019`（`docs: ...`） |
| 上游最新 tag | `v1.5.8`（`339611e6c666d1b1761f18ad9940686a175ff4eb`） |
| 本仓库 vendor 代码版本 | `v1.5.7`（见 `blender_manifest.toml` 与 `__init__.py`） |
| 漂移 | 落后约一个版本；需评审 v1.5.8 变更后再同步 |
| 注意 | `vendor/render_monitor/README.md` 顶部仍写 v1.5.1，是滞后的 README，不代表当前代码版本 |

> 上述提交号是检查时点快照。以后做同步时，应以实际 `git ls-remote`/API 结果为准并更新本表。

## 同步范围

需要同步/核对的对象：

1. **直接复制区**
   - `vendor/render_monitor/` ← 上游 `render_monitor/`
   - 同步时优先整目录替换，避免遗漏文件删除/新增。

2. **应用侧同源/强依赖区**
   - `src/rmqueue/render_session.py`：
     内嵌渲染脚本调用 `render_monitor.register()`、`scene.rm_shots`、
     `core.apply_scene_state()`、`rm_utils.parse_render_stats()`、
     `rm_utils.compute_tile_weights()` 等，并实现类似上游 `rm_job.py`
     的会话逻辑。
   - `src/rmqueue/progress.py`：
     与上游 `utils.py` / `rm_job.py` 同款文件-backed mmap 长度前缀协议。
   - `src/rmqueue/tile_progress.py`：
     与上游 rm_job 的分块权重进度算法同源。
   - `src/rmqueue/naming.py`：
     命名/清洗规则与上游 `utils.py` 的模板实现同源，注意是否出现新占位符
     或安全规则变化。
   - `src/rmqueue/blender_probe.py`、`queue.py`：
     依赖 `rm_shots` 字段（uid/name/status/selected/output_path/error）、
     `scene.rm_output_dir`、`data_json` 等；若插件数据模型变更需同步适配。

3. **需要重点确认的“语义契约”**
   - 快照状态：`PENDING / RENDERING / DONE / FAILED`
   - 渲染中止/崩溃后的状态修正规则
   - mmap 缓冲布局：`[0:4] 大端长度` + `[4:] JSON payload`
   - `data_json` 快照结构/版本
   - 场景输出目录解析规则（`//` 相对 .blend）

## 同步流程

### 1. 获取上游最新代码

在仓库根目录执行（首次需联网）：

```bash
git fetch https://github.com/HarrisWilde/Blender-Render-Monitor.git master
# 或临时 clone 到任意目录
git clone --depth 1 https://github.com/HarrisWilde/Blender-Render-Monitor.git /tmp/upstream-render-monitor
```

### 2. 对比差异

```bash
# 如果已把上游加为 remote：
git remote add upstream https://github.com/HarrisWilde/Blender-Render-Monitor.git
git fetch upstream master
git diff --stat FETCH_HEAD -- vendor/render_monitor

# 推荐：临时把上游 render_monitor 展开后，与本地目录做整体 diff
diff -rq /tmp/upstream-render-monitor/render_monitor vendor/render_monitor
```

### 3. 同步 vendor 目录

- 优先整目录替换为上游 `render_monitor/`，保留目录结构；
- 若本仓库对 vendor 做过本地补丁，先记录到下面的「本地补丁」清单；
- 替换后检查是否新增/删除文件，避免遗漏。

### 4. 适配应用侧

- 搜索 `render_monitor`、`rm_shots`、`data_json`、`apply_scene_state`、
  `parse_render_stats`、`compute_tile_weights`、`rm_output_dir` 在上游的改动；
- 对照 `src/rmqueue/` 中对应逻辑，更新协议/字段/API 调用；
- 不要盲目复制上游 `rm_job.py` 或 `ops.py`，应用侧编排与 Blender 插件不同。

### 5. 测试

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python tests\ui_smoke.py
.\.venv\Scripts\python tests\smoke_probe.py --all   # 需要真实 Blender
.\.venv\Scripts\python tests\render_e2e.py --all    # 需要真实 Blender
```

涉及真实渲染的改动，至少应在可用的 Blender 版本上跑一次枚举与渲染 E2E。

### 6. 更新记录

- 更新本文件「当前同步状态」表：上游 commit/tag、本地同步到的版本/commit、日期；
- 如上游 README/版本号变化，同步 `vendor/render_monitor/README.md`（不要留着误导性的旧版本号）；
- 提交信息示例：

```
chore(vendor): sync render_monitor v1.5.7 -> v1.5.8

- vendor/render_monitor 整目录同步至上游 <commit>
- 适配应用侧 xxx/yyy
- 已跑：pytest / UI smoke / Blender E2E
```

## 本地补丁清单

> 如果某次同步必须在上游 vendor 之外保留本仓库特有改动，请写在这里；
> 当前没有已登记的本地补丁。

（暂无）
