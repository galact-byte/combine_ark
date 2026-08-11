"""Win32 SendInput 双路鼠标注入、坐标归一化、管理员提权与 F8 急停。

顶层仅放跨平台安全的纯函数与 ctypes 结构体定义；所有 `windll` 调用
都在函数内惰性访问并守卫非 Windows，保证导图/图纸与单元测试在任意平台可导入。
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import Structure, Union, c_long, c_ulong

# ---- 纯函数（可单测、可移植） -------------------------------------------------

_ABS_MAX = 65535


def to_absolute(x: int, y: int, virtual_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """屏幕像素 → 0..65535 虚拟桌面绝对坐标；越界裁剪。"""
    left, top, width, height = virtual_rect

    def norm(value: int, origin: int, size: int) -> int:
        if size <= 1:
            return 0
        scaled = round((value - origin) * _ABS_MAX / (size - 1))
        return max(0, min(_ABS_MAX, scaled))

    return (norm(x, left, width), norm(y, top, height))


def relative_delta(prev: tuple[int, int] | None, cur: tuple[int, int]) -> tuple[int, int]:
    """相对位移增量：首帧（无历史）返回 (0, 0)。"""
    if prev is None:
        return (0, 0)
    return (cur[0] - prev[0], cur[1] - prev[1])


def should_elevate(is_admin: bool, already_tried: bool) -> bool:
    """是否应重启提权：仅当非管理员且尚未尝试过（防 UAC 拒绝后死循环）。"""
    return (not is_admin) and (not already_tried)


# ---- ctypes 结构体（定义不触发 windll，跨平台安全） ---------------------------

ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_VK_F8 = 0x77
_WHEEL_DELTA = 120


class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_long),
        ("dy", c_long),
        ("mouseData", c_ulong),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _InputUnion(Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(Structure):
    _fields_ = [("type", c_ulong), ("union", _InputUnion)]


class InputError(RuntimeError):
    """SendInput 调用被系统拒绝或注入失败。"""


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("鼠标注入仅在 Windows 上可用。")


def is_admin() -> bool:
    """当前进程是否具备管理员权限；非 Windows 视为无需提权。"""
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def elevate_and_exit(argv: list[str] | None = None, marker: str = "--elevated") -> None:
    """以管理员重启当前脚本并退出；子进程带 marker 防再次提权。"""
    _require_windows()
    args = list(argv if argv is not None else sys.argv)
    params = " ".join(f'"{a}"' for a in args[1:] + [marker])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{args[0]}" {params}'.strip(), None, 1)
    sys.exit(0)


def f8_pressed() -> bool:
    """F8 是否按下（全局急停）；非 Windows 恒为 False。"""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(_VK_F8) & 0x8000)
    except (AttributeError, OSError):
        return False


def _virtual_desktop_rect() -> tuple[int, int, int, int]:
    metrics = ctypes.windll.user32.GetSystemMetrics
    return (
        metrics(_SM_XVIRTUALSCREEN),
        metrics(_SM_YVIRTUALSCREEN),
        metrics(_SM_CXVIRTUALSCREEN),
        metrics(_SM_CYVIRTUALSCREEN),
    )


def client_screen_bbox(hwnd: int) -> tuple[int, int, int, int]:
    """窗口客户区在屏幕坐标下的包围盒 (left, top, right, bottom)。"""
    _require_windows()
    user32 = ctypes.windll.user32
    rect = (c_long * 4)()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise InputError("无法读取游戏客户区尺寸。")
    point = (c_long * 2)(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise InputError("无法换算游戏客户区屏幕坐标。")
    left, top = point[0], point[1]
    return (left, top, left + rect[2], top + rect[3])


def capture_client(hwnd: int):
    """截取窗口客户区图像（前台窗口）。延迟导入 Pillow.ImageGrab。"""
    from PIL import ImageGrab

    bbox = client_screen_bbox(hwnd)
    return ImageGrab.grab(bbox=bbox, all_screens=True)


class SendInputMouse:
    """SendInput 双路注入：先发相对位移喂 Raw Input，再发绝对坐标校系统光标。"""

    PAUSE = 0.03

    def __init__(self, hwnd: int | None = None) -> None:
        _require_windows()
        self._user32 = ctypes.windll.user32
        self._user32.SendInput.argtypes = (c_ulong, ctypes.POINTER(INPUT), ctypes.c_int)
        self._user32.SendInput.restype = c_ulong
        self._virtual = _virtual_desktop_rect()
        self._prev: tuple[int, int] | None = None
        self._hwnd = hwnd

    def _emit(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        event = INPUT(type=INPUT_MOUSE, union=_InputUnion(mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)))
        sent = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if sent != 1:
            raise InputError("SendInput 被系统拒绝；请确认已以管理员身份运行。")

    def move_relative(self, dx: int, dy: int) -> None:
        self._emit(MOUSEEVENTF_MOVE, dx, dy)

    def _move_absolute(self, x: int, y: int) -> None:
        ax, ay = to_absolute(x, y, self._virtual)
        self._emit(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)

    def click(self, x: int, y: int) -> None:
        # 路径①：相对位移喂 Unity Raw Input。
        dx, dy = relative_delta(self._prev, (x, y))
        if (dx, dy) != (0, 0):
            self.move_relative(dx, dy)
        else:
            self.move_relative(1, 0)
            self.move_relative(-1, 0)
        # 路径②：绝对坐标校准系统光标后点击。
        self._move_absolute(x, y)
        time.sleep(self.PAUSE)
        self._emit(MOUSEEVENTF_LEFTDOWN)
        time.sleep(self.PAUSE / 2)
        self._emit(MOUSEEVENTF_LEFTUP)
        self._prev = (x, y)

    def scroll(self, clicks: int, x: int, y: int) -> None:
        self._move_absolute(x, y)
        time.sleep(self.PAUSE)
        self._emit(MOUSEEVENTF_WHEEL, data=(clicks * _WHEEL_DELTA) & 0xFFFFFFFF)
        self._prev = (x, y)
