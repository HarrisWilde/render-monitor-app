"""渲染进度共享协议（mmap，双端共用同一实现）。

主应用（Qt worker）与 blender 渲染子进程通过一个文件的内存映射交换进度：
写端先把 payload 写入 [HEADER:]，最后写 4 字节大端长度前缀——读端看到新长度
时 payload 必然完整（单写单读，无需锁）。

此模块同时被两处 import：
- 应用侧：轮询/收尾时读进度；
- 渲染子进程侧：注入脚本把 app 源码加入 sys.path 后 import（保证协议唯一实现）。
"""

from __future__ import annotations

import json
import mmap
import os
import struct

MMAP_SIZE = 1 << 20          # 1 MiB
HEADER = 4                   # struct ">I"
_HEADER_FMT = ">I"


def _payload_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def write_file(path: str, obj) -> None:
    """把 obj 写入进度文件（长度前缀最后写）。失败静默（只丢本次进度）。"""
    payload = _payload_bytes(obj)
    if len(payload) > MMAP_SIZE - HEADER:
        return
    try:
        fd = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
            0o666,
        )
        try:
            os.ftruncate(fd, MMAP_SIZE)
            mm = mmap.mmap(fd, MMAP_SIZE, access=mmap.ACCESS_WRITE)
        except (OSError, ValueError):
            os.close(fd)
            return
        os.close(fd)
        try:
            mm[HEADER:HEADER + len(payload)] = payload
            mm[0:HEADER] = struct.pack(_HEADER_FMT, len(payload))
        finally:
            mm.close()
    except OSError:
        return


def read_file(path: str):
    """读进度文件；不存在/空/未就绪/损坏一律返回 None（调用方容错）。"""
    if not path or not os.path.exists(path):
        return None
    try:
        size = os.path.getsize(path)
        if size < HEADER:
            return None
        with open(path, "rb") as f:
            mm = mmap.mmap(f.fileno(), min(size, MMAP_SIZE), access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        return None
    try:
        (length,) = struct.unpack(_HEADER_FMT, mm[0:HEADER])
        if length <= 0 or length > mm.size() - HEADER:
            return None
        data = mm[HEADER:HEADER + length]
    except struct.error:
        return None
    finally:
        mm.close()
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
