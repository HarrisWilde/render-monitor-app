# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包：Render Monitor Queue（onedir）
# 用法：python -m PyInstaller packaging/rmqueue.spec --noconfirm

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

a = Analysis(
    [os.path.join(ROOT, "src", "rmqueue", "app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    # vendor 插件包必须随应用分发：子进程注入 blender 使用
    datas=[(os.path.join(ROOT, "vendor"), "vendor")],
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
    console=False,
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
