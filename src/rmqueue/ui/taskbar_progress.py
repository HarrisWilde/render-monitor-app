"""Windows 任务栏进度（Taskbar Progress，同 WPF 底层 ITaskbarList3）。

Qt6/PySide6 移除了 Qt5 的 QtWinExtras，这里用 ctypes 直接调用
ITaskbarList3 COM vtable：SetProgressValue(9) / SetProgressState(10)。

COM 内存布局要点：
  接口指针 → [0] = vtable 数组地址 → vtable[fn] = 函数指针；
  本模块先 CoCreateInstance(IUnknown)，再 QueryInterface 到 ITaskbarList3。
非 Windows / 调用失败时静默降级（返回 False）。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2

_CLSID_TASKBAR_LIST = "56FDF344-FD6D-11D0-958A-006097C9A090"
_IID_ITASKBAR_LIST3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEAFC"
_IID_IUNKNOWN = "00000000-0000-0000-C000-000000000046"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    parts = text.split("-")
    # 末 8 字节 = 文本第 4 段（4 hex）+ 第 5 段（12 hex）拼成 16 hex
    data4 = bytes.fromhex(parts[3] + parts[4])
    return _GUID(
        int(parts[0], 16), int(parts[1], 16), int(parts[2], 16),
        (ctypes.c_ubyte * 8).from_buffer_copy(data4),
    )


def _vtable_of(ptr: int):
    """接口指针 → vtable 函数指针数组（POINTER(c_void_p)，支持 [i] 索引）。"""
    iface = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    return iface.contents  # 接口对象首成员 = vtable 数组首地址


class TaskbarProgress:
    """对某个顶层窗口（hwnd）设置任务栏进度；全部操作失败静默返回 False。"""

    def __init__(self) -> None:
        self._this: int | None = None
        self._funcs = None
        self._ok = False
        self._init()

    # ------------------------------------------------------------ 初始化
    def _init(self) -> None:
        if sys.platform != "win32":
            return
        dbg = os.environ.get("RMQ_TB_DEBUG") == "1"

        def log(msg: str) -> None:
            if dbg:
                print(f"[tb] {msg}", flush=True)

        try:
            ole32 = ctypes.windll.ole32
            try:
                ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
            except Exception:  # noqa: BLE001
                pass

            # 1) IUnknown 创建
            unk = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(_guid(_CLSID_TASKBAR_LIST)), None, 1,
                ctypes.byref(_guid(_IID_IUNKNOWN)), ctypes.byref(unk))
            log(f"CoCreateInstance hr=0x{hr & 0xffffffff:08x}")
            if hr < 0 or not unk.value:
                return
            # 2) QueryInterface → ITaskbarList3
            iid3 = _guid(_IID_ITASKBAR_LIST3)
            out = ctypes.c_void_p()
            qi = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p,
                ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
            )(_vtable_of(unk.value)[0])
            hr_qi = qi(unk.value, ctypes.byref(iid3), ctypes.byref(out))
            log(f"QI ITaskbarList3 hr=0x{hr_qi & 0xffffffff:08x}")
            if hr_qi < 0 or not out.value:
                return
            # 3) 存 vtable + HrInit
            self._this = int(out.value)
            self._funcs = _vtable_of(out.value)
            hrinit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(
                self._funcs[3])
            hr2 = hrinit(self._this)
            log(f"HrInit hr=0x{hr2 & 0xffffffff:08x}")
            self._ok = hr2 >= 0
        except Exception as exc:  # noqa: BLE001
            log(f"init err {exc!r}")
            self._ok = False

    def _call(self, index: int, this_value: int, *args) -> int | None:
        """调用 vtable[index]（首参 this）。args 为已构造 ctypes 值。"""
        if self._funcs is None:
            return None
        fn_ptr = self._funcs[index]
        if not fn_ptr:
            return None
        argtypes = [ctypes.c_void_p] + [type(a) for a in args]
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, *argtypes)(fn_ptr)
        return fn(this_value, *args)

    # ------------------------------------------------------------ 状态
    def _apply(self, index: int, hwnd: int, *values) -> bool:
        if not self._ok or not self._this or not hwnd:
            return False
        try:
            hr = self._call(index, self._this,
                            wintypes.HWND(int(hwnd)), *values)
            return hr is not None and hr >= 0
        except Exception:  # noqa: BLE001
            return False

    def normal(self, hwnd: int, fraction: float) -> bool:
        """常规进度 0..1（映射 0..1000 整数区间）。"""
        frac = max(0.0, min(float(fraction), 1.0))
        done = int(round(frac * 1000))
        ok1 = self._apply(9, hwnd, ctypes.c_ulonglong(done),
                          ctypes.c_ulonglong(1000))
        ok2 = self._apply(10, hwnd, ctypes.c_int(TBPF_NORMAL))
        return ok1 and ok2

    def indeterminate(self, hwnd: int) -> bool:
        """忙碌动画（不确定量）。"""
        return self._apply(10, hwnd, ctypes.c_int(TBPF_INDETERMINATE))

    def clear(self, hwnd: int) -> bool:
        """移除任务栏进度。"""
        return self._apply(10, hwnd, ctypes.c_int(TBPF_NOPROGRESS))

    def available(self) -> bool:
        return self._ok
