# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包：Render Monitor Queue（onedir）
# 用法：python -m PyInstaller packaging/rmqueue.spec --noconfirm

import os

# PyInstaller 执行 spec 时在命名空间注入 SPECPATH（spec 所在目录）
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "src", "rmqueue", "app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[
        # vendor 插件包必须随应用分发：子进程注入 blender 使用
        (os.path.join(ROOT, "vendor"), "vendor"),
        # rmqueue 源码也须以文件形态落盘（_internal/rmqueue）：
        # 渲染/探针子进程由外部 blender python 直接 import，
        # 无法读取 PyInstaller 的 PYZ 归档内模块。
        (os.path.join(ROOT, "src", "rmqueue"), "rmqueue"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RenderMonitorQueue",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # RMQ_CONSOLE=1 时构建控制台版，便于抓取启动错误
    console=os.environ.get("RMQ_CONSOLE") == "1",
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="RenderMonitorQueue",
)
