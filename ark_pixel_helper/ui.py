"""简体中文 tkinter 战术像素编辑器界面。"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter import Canvas

from PIL import Image, ImageDraw, ImageTk

from .autofill import AutoFillRunner, build_residual_pattern
from .calibration import Calibration, CalibrationError, ClientArea, Rect, calibration_from_capture, viewport_seed
from .win_input import SendInputMouse, capture_client, f8_pressed
from .palette_locate import swatch_centers
from .export import ExportError, export_pattern_csv, export_pattern_png
from .image_pipeline import CropBox, ImageOptions, convert_image
from .palette import PALETTE, nearest_palette_index, palette_index_to_number
from .pattern import GRID_SIZE, Pattern

BG = "#e3f2ef"
SURFACE = "#ffffff"
SURFACE_ALT = "#eef6f4"
TEXT = "#153230"
MUTED = "#5f807c"
BORDER = "#c4e0da"
ACCENT = "#0fb6a6"
ACCENT_SOFT = "#d6f2ee"
WARNING = "#f5893a"
ERROR = "#e5533d"
CANVAS_BG = "#ffffff"
GRID_LINE = "#d3e7e3"
HEADER_TOP = "#7fe0d3"
HEADER_BOTTOM = "#39b7c9"


def application_data_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "ArkPixelHelper"


def initial_image_directory() -> Path:
    pictures = Path.home() / "Pictures"
    return pictures if pictures.is_dir() else Path.home()


def progress_percent(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(done * 100 / total)))


def rgb_hex(color: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % color


@dataclass(frozen=True)
class CanvasImageMap:
    """保持原图和等比缩略画布之间坐标转换的单一事实来源。"""

    image_size: tuple[int, int]
    canvas_size: tuple[int, int]

    @property
    def scale(self) -> float:
        image_width, image_height = self.image_size
        canvas_width, canvas_height = self.canvas_size
        return min(canvas_width / image_width, canvas_height / image_height)

    @property
    def origin(self) -> tuple[float, float]:
        image_width, image_height = self.image_size
        canvas_width, canvas_height = self.canvas_size
        return ((canvas_width - image_width * self.scale) / 2, (canvas_height - image_height * self.scale) / 2)

    def canvas_to_source(self, x: float, y: float) -> tuple[int, int]:
        origin_x, origin_y = self.origin
        image_width, image_height = self.image_size
        return (
            max(0, min(image_width, round((x - origin_x) / self.scale))),
            max(0, min(image_height, round((y - origin_y) / self.scale))),
        )

    def canvas_to_source_f(self, x: float, y: float) -> tuple[float, float]:
        """不四舍五入、不限幅的浮点映射，供拖拽平滑跟随。"""
        origin_x, origin_y = self.origin
        return ((x - origin_x) / self.scale, (y - origin_y) / self.scale)

    def crop_to_canvas(self, crop_box: CropBox) -> tuple[float, float, float]:
        crop_box.validate_for(self.image_size)
        origin_x, origin_y = self.origin
        return (origin_x + crop_box.left * self.scale, origin_y + crop_box.top * self.scale, crop_box.side * self.scale)


class CropSelection:
    """维护始终位于原图范围内的头像式正方形选择框。"""

    def __init__(self, image_size: tuple[int, int], crop_box: CropBox | None = None) -> None:
        self.image_size = image_size
        width, height = image_size
        if width <= 0 or height <= 0:
            raise ValueError("图片尺寸无效")
        side = min(width, height)
        self.crop_box = crop_box or CropBox((width - side) // 2, (height - side) // 2, side)
        self.crop_box.validate_for(image_size)

    def _set_box(self, left: float, top: float, side: float) -> CropBox:
        width, height = self.image_size
        bounded_side = max(1, min(round(side), width, height))
        bounded_left = max(0, min(round(left), width - bounded_side))
        bounded_top = max(0, min(round(top), height - bounded_side))
        self.crop_box = CropBox(bounded_left, bounded_top, bounded_side)
        return self.crop_box

    def move_by(self, delta_x: float, delta_y: float) -> CropBox:
        box = self.crop_box
        return self._set_box(box.left + delta_x, box.top + delta_y, box.side)

    def move_to(self, left: float, top: float) -> CropBox:
        return self._set_box(left, top, self.crop_box.side)

    def resize_from_corner(self, corner: str, point: tuple[float, float]) -> CropBox:
        left, top, side = self.crop_box.left, self.crop_box.top, self.crop_box.side
        right, bottom = left + side, top + side
        x, y = point
        if corner == "nw":
            side = min(right - x, bottom - y)
            left, top = right - side, bottom - side
        elif corner == "ne":
            side = min(x - left, bottom - y)
            top = bottom - side
        elif corner == "sw":
            side = min(right - x, y - top)
            left = right - side
        elif corner == "se":
            side = min(x - left, y - top)
        else:
            raise ValueError("不支持的裁切框角点")
        return self._set_box(left, top, side)

    def zoom_at(self, point: tuple[float, float], factor: float) -> CropBox:
        if factor <= 0:
            raise ValueError("缩放比例必须为正数")
        box = self.crop_box
        side = box.side / factor
        x, y = point
        relative_x = (x - box.left) / box.side
        relative_y = (y - box.top) / box.side
        return self._set_box(x - side * relative_x, y - side * relative_y, side)


class CropDialog(Toplevel):
    """在提交前由用户直接确认原图坐标裁切区域的模态对话框。"""

    HANDLE_RADIUS = 8

    def __init__(self, parent: Tk, image: Image.Image, on_confirm: Callable[[CropBox], None], crop_box: CropBox | None = None, options: ImageOptions | None = None) -> None:
        super().__init__(parent)
        self.title("确认正方形裁切区域")
        self.configure(bg=SURFACE)
        self.transient(parent)
        self.resizable(False, False)
        self._on_confirm = on_confirm
        self._source_image = image.copy()
        self._selection = CropSelection(image.size, crop_box)
        self._preview_options = options or ImageOptions()
        self.preview_pattern = convert_image(self._source_image, replace(self._preview_options, crop_box=self._selection.crop_box))
        self._drag_mode: str | None = None
        self._last_source_point: tuple[int, int] | None = None
        self._grab_offset: tuple[float, float] | None = None

        # 左侧原图与右侧 24×24 终局预览必须同时完整可见，横图也不能挤掉右侧预览。
        max_width, max_height = 340, 500
        scale = min(max_width / image.width, max_height / image.height, 1.0)
        self._canvas_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        self._map = CanvasImageMap(image.size, self._canvas_size)
        preview = image.convert("RGB").resize(self._canvas_size, Image.Resampling.LANCZOS)
        self._preview_image = ImageTk.PhotoImage(preview)

        ttk.Label(self, text="框住脸部、双眼和发型等重点区域", style="TLabel", padding=(16, 16, 16, 4)).pack(anchor="w")
        ttk.Label(self, text="拖动框内可移动；拖动四角调整大小；滚轮可围绕指针缩放。确认前不会修改当前图案。", style="Muted.TLabel", padding=(16, 0, 16, 12), wraplength=max_width).pack(anchor="w")
        workspace = ttk.Frame(self, style="TFrame", padding=(16, 0))
        workspace.pack(fill="both", expand=True)
        self.canvas = Canvas(workspace, width=self._canvas_size[0], height=self._canvas_size[1], highlightthickness=1, highlightbackground=BORDER, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="n")
        self.canvas.create_image(0, 0, image=self._preview_image, anchor="nw", tags="image")
        preview_panel = ttk.Frame(workspace, style="TFrame", padding=(14, 0, 0, 0))
        preview_panel.grid(row=0, column=1, sticky="n")
        ttk.Label(preview_panel, text="最终拼豆预览", style="Section.TLabel").pack(anchor="w")
        ttk.Label(preview_panel, text="24 × 24 / 游戏 40 色", style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        self.preview_cell_size = 12
        preview_size = GRID_SIZE * self.preview_cell_size
        self.preview_canvas = Canvas(preview_panel, width=preview_size, height=preview_size, bg=CANVAS_BG, highlightthickness=1, highlightbackground=BORDER)
        self.preview_canvas.pack(anchor="w")
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish_drag)
        self.canvas.bind("<MouseWheel>", self._zoom)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_by(event, 1.15))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_by(event, 1 / 1.15))

        actions = ttk.Frame(self, style="TFrame", padding=16)
        actions.pack(fill="x")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="使用此区域", command=self._confirm, style="Primary.TButton").pack(side="right", padx=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self._redraw()
        self.grab_set()
        self.focus_set()

    def _canvas_point_to_source(self, x: float, y: float) -> tuple[int, int]:
        return self._map.canvas_to_source(x, y)

    def _corners(self) -> dict[str, tuple[float, float]]:
        left, top, side = self._map.crop_to_canvas(self._selection.crop_box)
        return {"nw": (left, top), "ne": (left + side, top), "sw": (left, top + side), "se": (left + side, top + side)}

    def _start_drag(self, event: object) -> None:
        x, y = event.x, event.y  # type: ignore[attr-defined]
        for corner, (corner_x, corner_y) in self._corners().items():
            if (x - corner_x) ** 2 + (y - corner_y) ** 2 <= self.HANDLE_RADIUS ** 2:
                self._drag_mode = corner
                self._last_source_point = None
                self._grab_offset = None
                return
        left, top, side = self._map.crop_to_canvas(self._selection.crop_box)
        if left <= x <= left + side and top <= y <= top + side:
            self._drag_mode = "move"
            # 记下“鼠标相对框左上角”的偏移（浮点源坐标），拖拽时保持框跟光标，不漂不跳。
            src_x, src_y = self._map.canvas_to_source_f(x, y)
            self._grab_offset = (src_x - self._selection.crop_box.left, src_y - self._selection.crop_box.top)

    def _drag(self, event: object) -> None:
        if self._drag_mode is None:
            return
        if self._drag_mode == "move" and self._grab_offset is not None:
            src_x, src_y = self._map.canvas_to_source_f(event.x, event.y)  # type: ignore[attr-defined]
            self._selection.move_to(src_x - self._grab_offset[0], src_y - self._grab_offset[1])
        elif self._drag_mode != "move":
            point = self._canvas_point_to_source(event.x, event.y)  # type: ignore[attr-defined]
            self._selection.resize_from_corner(self._drag_mode, point)
        # 拖拽中只重画轻量级选框叠加层；24×24 量化预览很贵，放到松手时再算一次。
        self._redraw_overlay()

    def _finish_drag(self, _event: object) -> None:
        if self._drag_mode is not None:
            self._redraw()  # 松手时重算一次实时预览
        self._drag_mode = None
        self._last_source_point = None
        self._grab_offset = None

    def _zoom(self, event: object) -> None:
        self._zoom_by(event, 1.15 if event.delta > 0 else 1 / 1.15)  # type: ignore[attr-defined]

    def _zoom_by(self, event: object, factor: float) -> None:
        self._selection.zoom_at(self._canvas_point_to_source(event.x, event.y), factor)  # type: ignore[attr-defined]
        self._redraw()

    def _redraw(self) -> None:
        self.preview_pattern = convert_image(self._source_image, replace(self._preview_options, crop_box=self._selection.crop_box))
        self.preview_canvas.delete("preview-cell")
        for row, values in enumerate(self.preview_pattern.cells):
            for column, color_index in enumerate(values):
                x0 = column * self.preview_cell_size
                y0 = row * self.preview_cell_size
                self.preview_canvas.create_rectangle(x0, y0, x0 + self.preview_cell_size, y0 + self.preview_cell_size, fill=rgb_hex(PALETTE[color_index]), outline=GRID_LINE, tags="preview-cell")
        self._redraw_overlay()

    def _redraw_overlay(self) -> None:
        self.canvas.delete("crop-overlay")
        left, top, side = self._map.crop_to_canvas(self._selection.crop_box)
        width, height = self._canvas_size
        for coords in ((0, 0, width, top), (0, top, left, top + side), (left + side, top, width, top + side), (0, top + side, width, height)):
            self.canvas.create_rectangle(*coords, fill="#102b28", stipple="gray50", outline="", tags="crop-overlay")
        self.canvas.create_rectangle(left, top, left + side, top + side, outline=ACCENT, width=3, tags="crop-overlay")
        for x, y in self._corners().values():
            self.canvas.create_rectangle(x - self.HANDLE_RADIUS, y - self.HANDLE_RADIUS, x + self.HANDLE_RADIUS, y + self.HANDLE_RADIUS, fill="#ffffff", outline=ACCENT, width=2, tags="crop-overlay")

    def _confirm(self) -> None:
        crop_box = self._selection.crop_box
        crop_box.validate_for(self._selection.image_size)
        self._on_confirm(crop_box)
        self.destroy()


@dataclass
class AppSettings:
    last_image_directory: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> AppSettings:
        path = path or application_data_directory() / "settings.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            directory = Path(value["last_image_directory"])
            return cls(directory if directory.is_dir() else None)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path | None = None) -> Path:
        path = path or application_data_directory() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_image_directory": str(self.last_image_directory) if self.last_image_directory else None}, ensure_ascii=False), encoding="utf-8")
        return path


def calibration_path() -> Path:
    return application_data_directory() / "calibration.json"


def foreground_window_handle() -> int:
    if os.name != "nt":
        raise CalibrationError("自动填色仅支持 Windows PC 客户端。")
    try:
        import ctypes

        handle = int(ctypes.windll.user32.GetForegroundWindow())
        if not handle:
            raise CalibrationError("未检测到前台窗口。")
        return handle
    except (AttributeError, OSError) as exc:
        raise CalibrationError("无法读取 Windows 前台窗口；请确认游戏客户端未最小化。") from exc


def is_foreground_window(handle: int) -> bool:
    try:
        return foreground_window_handle() == handle
    except CalibrationError:
        return False


def window_matches_calibration(calibration: Calibration, handle: int, process_id: int) -> bool:
    """拒绝句柄被复用或切到其他前台程序的自动点击。"""
    return calibration.target_window == handle and calibration.target_process_id == process_id


def is_calibrated_window_foreground(calibration: Calibration) -> bool:
    try:
        handle = foreground_window_handle()
        return window_matches_calibration(calibration, handle, window_process_id(handle))
    except CalibrationError:
        return False


def window_process_id(handle: int) -> int:
    if os.name != "nt":
        raise CalibrationError("自动填色仅支持 Windows PC 客户端。")
    try:
        import ctypes
        from ctypes import wintypes

        process_id = wintypes.DWORD()
        if not ctypes.windll.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id)) or not process_id.value:
            raise CalibrationError("无法读取目标游戏窗口的进程标识。")
        return int(process_id.value)
    except (AttributeError, OSError) as exc:
        raise CalibrationError("无法读取目标游戏窗口的进程标识。") from exc


def get_foreground_client_area(handle: int | None = None) -> ClientArea:
    """读取当前前台窗口真实客户区，确保运行时不依赖某个固定分辨率。"""
    if os.name != "nt":
        raise CalibrationError("自动填色仅支持 Windows PC 客户端。")
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = handle or foreground_window_handle()
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise CalibrationError("无法读取前台窗口客户区。")
        point = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            raise CalibrationError("无法换算前台窗口坐标。")
        return ClientArea(point.x, point.y, rect.right - rect.left, rect.bottom - rect.top)
    except (AttributeError, OSError) as exc:
        raise CalibrationError("无法读取 Windows 前台窗口；请确认游戏客户端未最小化。") from exc


class PixelHelperApp:
    CELL_SIZE = 24

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("奇象巡展 · 像素拼豆助手")
        self.root.minsize(1170, 760)
        self.root.configure(bg=BG)
        self.settings = AppSettings.load()
        self.source_image: Image.Image | None = None
        self.source_path: Path | None = None
        self.crop_box: CropBox | None = None
        self.pattern = Pattern.blank()
        self.selected_cell = (0, 0)
        self.calibration: Calibration | None = self._load_calibration()
        self.cancel_event = threading.Event()
        self.ui_events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.is_filling = False

        self.fit_mode = StringVar(value="裁剪（可调构图）")
        self.resample = StringVar(value="平滑取样（照片 / 插画）")
        self.detail_strategy = StringVar(value="更多颜色细节（完整 40 色候选）")
        self.reduce_colors = BooleanVar(value=False)
        self.dither = BooleanVar(value=False)
        self.show_numbers = BooleanVar(value=False)
        self.crop_x = IntVar(value=0)
        self.crop_y = IntVar(value=0)
        self.selected_color = IntVar(value=3)
        self.status = StringVar(value="等待导入图片。处理全程仅在本地完成。")
        self.image_name = StringVar(value="未导入图片")
        self.progress = StringVar(value="待处理")
        self.progress_value = IntVar(value=0)

        self._configure_styles()
        self._build_layout()
        self._refresh_pattern()
        self.image_name.trace_add("write", self._sync_banner_text)
        self.progress.trace_add("write", self._sync_banner_text)
        self.root.after(50, self._process_ui_events)

    def _process_ui_events(self) -> None:
        try:
            while True:
                kind, value = self.ui_events.get_nowait()
                if kind == "countdown":
                    self.progress.set(f"准备中：{value} 秒后检查前台游戏")
                elif kind == "progress":
                    done, total = value  # type: ignore[misc]
                    percent = progress_percent(done, total)
                    self.progress_value.set(percent)
                    self.progress.set(f"自动填色：{done} / {total} 格（{percent}%）")
                elif kind == "finish":
                    self._finish_autofill_ui(str(value))
        except queue.Empty:
            pass
        self.root.after(50, self._process_ui_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=SURFACE, borderwidth=1, relief="solid", bordercolor=BORDER)
        style.configure("TLabel", background=SURFACE, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Section.TLabel", background=SURFACE, foreground=ACCENT, font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TButton", background=SURFACE_ALT, foreground=TEXT, bordercolor=BORDER, padding=(10, 8), font=("Microsoft YaHei UI", 10), relief="solid")
        style.map("TButton", background=[("active", ACCENT_SOFT), ("disabled", "#eef1f0")], foreground=[("disabled", "#a9b7b4")])
        style.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#12c7b5")])
        style.configure("Warning.TButton", background=WARNING, foreground="#231400", bordercolor=WARNING, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Warning.TButton", background=[("active", "#ffbf5e"), ("disabled", "#d7d2c4")], foreground=[("disabled", "#9a917f")])
        style.configure("TCombobox", fieldbackground=SURFACE_ALT, background=SURFACE_ALT, foreground=TEXT, arrowcolor=ACCENT, padding=6, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE_ALT)], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=SURFACE, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", SURFACE)])

    def _panel(self, parent: ttk.Frame, column: int, weight: int) -> ttk.Frame:
        parent.columnconfigure(column, weight=weight)
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0), pady=0)
        return panel

    @staticmethod
    def _mix(c1: str, c2: str, t: float) -> str:
        a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def _draw_header_gradient(self, canvas: "Canvas", width: int, height: int) -> None:
        canvas.delete("grad")
        steps = max(1, width // 4)
        for i in range(steps):
            color = self._mix(HEADER_TOP, HEADER_BOTTOM, i / steps)
            x0 = i * width / steps
            canvas.create_rectangle(x0, 0, x0 + width / steps + 1, height, fill=color, outline=color, tags="grad")
        canvas.tag_lower("grad")

    def _draw_sparkle(self, canvas: "Canvas", cx: float, cy: float, r: float, color: str) -> None:
        """四角星苒：两条细长菱形交叉，营造活动闪光感。"""
        thin = max(1.0, r * 0.24)
        canvas.create_polygon(cx, cy - r, cx + thin, cy, cx, cy + r, cx - thin, cy, fill=color, outline=color, tags="decor")
        canvas.create_polygon(cx - r, cy, cx, cy + thin, cx + r, cy, cx, cy - thin, fill=color, outline=color, tags="decor")

    def _render_banner(self, width: int) -> None:
        c = self._banner
        h = 104
        self._draw_header_gradient(c, width, h)
        c.delete("decor")
        sparkles = ((0.50, 22, 7), (0.56, 60, 4), (0.62, 34, 10), (0.69, 76, 5), (0.75, 26, 6), (0.82, 84, 4), (0.60, 90, 3))
        for fx, cy, r in sparkles:
            color = "#ffe7a6" if r <= 5 else "#ffb454"
            self._draw_sparkle(c, width * fx, cy, r, color)
        c.delete("txt")
        c.create_text(28, 34, anchor="w", text="奇象巡展 · 像素拼豆助手", fill="#06302e", font=("Microsoft YaHei UI", 20, "bold"), tags="txt")
        c.create_text(30, 68, anchor="w", text="导图 · 量化 · 手动修整 · 自动绘制", fill="#0a4b45", font=("Microsoft YaHei UI", 10), tags="txt")
        c.create_text(width - 28, 30, anchor="e", text=self.image_name.get(), fill="#06302e", font=("Microsoft YaHei UI", 10, "bold"), tags=("txt", "imgname"))
        c.create_text(width - 218, 70, anchor="e", text=self.progress.get(), fill="#0a4b45", font=("Microsoft YaHei UI", 9), tags=("txt", "progresstxt"))
        c.coords("pbar", width - 28, 60)

    def _sync_banner_text(self, *_args: object) -> None:
        if hasattr(self, "_banner"):
            self._banner.itemconfigure("imgname", text=self.image_name.get())
            self._banner.itemconfigure("progresstxt", text=self.progress.get())

    def _build_layout(self) -> None:
        banner = Canvas(self.root, height=104, highlightthickness=0, bd=0)
        banner.pack(fill="x")
        self._banner = banner
        banner.bind("<Configure>", lambda e: self._render_banner(e.width))
        self.progress_bar = ttk.Progressbar(banner, maximum=100, variable=self.progress_value, length=180, mode="determinate")
        banner.create_window(0, 0, window=self.progress_bar, anchor="ne", tags="pbar")

        body = ttk.Frame(self.root, padding=(24, 0, 24, 14), style="TFrame")
        body.pack(fill="both", expand=True)
        left = self._panel(body, 0, 1)
        center = self._panel(body, 1, 2)
        right = self._panel(body, 2, 1)
        self._build_controls(left)
        self._build_canvas(center)
        self._build_right_panel(right)

        ttk.Label(self.root, textvariable=self.status, style="Muted.TLabel", background=BG, anchor="w", padding=(24, 8)).pack(fill="x")

    def _section(self, parent: ttk.Frame, label: str) -> None:
        ttk.Separator(parent).pack(fill="x", pady=(14, 8))
        ttk.Label(parent, text=label.upper(), style="Section.TLabel").pack(anchor="w", pady=(0, 8))

    def _build_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="01 / 导入与构图", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Button(parent, text="导入 PNG / JPG 图片", command=self.import_image).pack(fill="x", ipady=6)
        self.recrop_button = ttk.Button(parent, text="重新裁切图片", command=self.recrop_image, state="disabled")
        self.recrop_button.pack(fill="x", ipady=5, pady=(6, 0))
        ttk.Label(parent, text="选择图片后先框选脸部、双眼和发型；图片只在本机处理，不会上传。", style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(6, 8))
        ttk.Label(parent, text="正方形构图（框选区域优先；下方为旧图快捷设置）", style="TLabel", wraplength=230).pack(anchor="w")
        fit = ttk.Combobox(parent, textvariable=self.fit_mode, state="readonly", values=("裁剪（可调构图）", "完整包含（白底留白）", "拉伸"))
        fit.pack(fill="x", pady=(3, 8), ipady=4)
        fit.bind("<<ComboboxSelected>>", self._apply_if_image)
        ttk.Label(parent, text="裁剪主体位置（横向 / 纵向）", style="TLabel").pack(anchor="w")
        for variable, name in ((self.crop_x, "横向"), (self.crop_y, "纵向")):
            line = ttk.Frame(parent, style="Panel.TFrame")
            line.pack(fill="x", pady=2)
            ttk.Label(line, text=name, width=5).pack(side="left")
            ttk.Scale(line, from_=-100, to=100, variable=variable, command=lambda _value: self._apply_if_image()).pack(side="left", fill="x", expand=True)

        self._section(parent, "02 / 像素化策略")
        ttk.Label(parent, text="取样方式", style="TLabel").pack(anchor="w")
        sampling = ttk.Combobox(parent, textvariable=self.resample, state="readonly", values=("平滑取样（照片 / 插画）", "最近邻（已有像素画）"))
        sampling.pack(fill="x", pady=(3, 8), ipady=4)
        sampling.bind("<<ComboboxSelected>>", self._apply_if_image)
        ttk.Label(parent, text="细节策略", style="TLabel").pack(anchor="w")
        strategy = ttk.Combobox(parent, textvariable=self.detail_strategy, state="readonly", values=("更多颜色细节（完整 40 色候选）", "清晰轮廓（最多 16 主色）"))
        strategy.pack(fill="x", pady=(3, 4), ipady=4)
        strategy.bind("<<ComboboxSelected>>", self._apply_detail_strategy)
        ttk.Checkbutton(parent, text="可选抖动（仅更多颜色细节时生效）", variable=self.dither, command=self._apply_if_image).pack(anchor="w", pady=(0, 10))
        ttk.Button(parent, text="应用转换到 24×24 图案", command=self.apply_conversion, style="Primary.TButton").pack(fill="x", ipady=7)
        ttk.Label(parent, text="顺序：导图 → 调整效果 → 检查图纸 → 打开游戏 → 自动填色", style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(10, 0))

    def _build_canvas(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="实时预览", style="Section.TLabel").pack(side="left")
        ttk.Checkbutton(top, text="显示色号", variable=self.show_numbers, command=self._refresh_pattern).pack(side="right")
        self.debug_fill = BooleanVar(value=False)
        ttk.Checkbutton(top, text="保存填色调试图", variable=self.debug_fill).pack(side="right", padx=(0, 12))
        self.canvas = Canvas(parent, width=GRID_SIZE * self.CELL_SIZE + 2, height=GRID_SIZE * self.CELL_SIZE + 2, bg=CANVAS_BG, highlightthickness=1, highlightbackground=BORDER, cursor="crosshair")
        self.canvas.pack(anchor="center", pady=(0, 10))
        self.canvas.bind("<Button-1>", self._select_canvas_cell)
        ttk.Label(parent, text="点击格子选中，再在右侧色号表点选颜色即可修改；导出与自动填色都使用当前图案。", style="Muted.TLabel", wraplength=510, justify="center").pack(anchor="center")
        self.canvas.focus_set()

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="03 / 色号与修正", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.selected_info = StringVar()
        ttk.Label(parent, textvariable=self.selected_info, style="TLabel").pack(anchor="w", pady=(0, 6))
        self.palette_canvas = Canvas(parent, width=260, height=360, bg=SURFACE, highlightthickness=0)
        self.palette_canvas.pack(fill="x")
        self.palette_canvas.bind("<Button-1>", self._select_palette_color)
        self.count_info = StringVar()
        ttk.Label(parent, textvariable=self.count_info, style="Muted.TLabel", wraplength=260).pack(anchor="w", pady=(8, 0))

        self._section(parent, "04 / 图纸导出")
        ttk.Button(parent, text="导出带网格图纸 PNG", command=self.export_png).pack(fill="x", ipady=5)
        ttk.Button(parent, text="导出逐格色号 CSV", command=self.export_csv).pack(fill="x", ipady=5, pady=(6, 0))

        self._section(parent, "05 / 游戏自动填色")
        self.calibration_info = StringVar()
        ttk.Label(parent, textvariable=self.calibration_info, style="Muted.TLabel", wraplength=260).pack(anchor="w", pady=(0, 8))
        ttk.Button(parent, text="捕获游戏窗口并识别画布", command=self.open_calibration).pack(fill="x", ipady=5)
        self.start_button = ttk.Button(parent, text="开始自动填色（需确认）", command=self.start_autofill, style="Warning.TButton")
        self.start_button.pack(fill="x", ipady=6, pady=(8, 0))
        self.cancel_button = ttk.Button(parent, text="停止后续点击", command=self.cancel_autofill, state="disabled")
        self.cancel_button.pack(fill="x", ipady=6, pady=(6, 0))

    def _load_calibration(self) -> Calibration | None:
        try:
            return Calibration.load(calibration_path())
        except CalibrationError:
            return None

    def _apply_detail_strategy(self, *_args: object) -> None:
        self.reduce_colors.set(self.detail_strategy.get().startswith("清晰轮廓"))
        self._apply_if_image()

    def _image_options(self) -> ImageOptions:
        return ImageOptions(
            fit_mode={"裁剪（可调构图）": "crop", "完整包含（白底留白）": "contain", "拉伸": "stretch"}[self.fit_mode.get()],
            resample="nearest" if self.resample.get().startswith("最近邻") else "smooth",
            reduce_colors=self.detail_strategy.get().startswith("清晰轮廓"),
            dither=self.dither.get(),
            crop_box=self.crop_box,
            crop_offset_x=self.crop_x.get() / 100,
            crop_offset_y=self.crop_y.get() / 100,
        )

    def import_image(self) -> None:
        directory = self.settings.last_image_directory or initial_image_directory()
        filename = filedialog.askopenfilename(parent=self.root, title="选择本地图片", initialdir=directory, filetypes=[("图片文件", "*.png *.jpg *.jpeg"), ("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"), ("所有文件", "*.*")])
        if not filename:
            return
        try:
            with Image.open(filename) as image:
                candidate_image = image.copy()
            candidate_path = Path(filename)
        except (OSError, ValueError) as exc:
            self.status.set(f"导入失败：无法读取该图片。请确认它是未损坏的 PNG 或 JPG/JPEG。({exc})")
            return

        def commit(crop_box: CropBox) -> None:
            crop_box.validate_for(candidate_image.size)
            self.source_image = candidate_image
            self.source_path = candidate_path
            self.crop_box = crop_box
            self.settings.last_image_directory = candidate_path.parent
            self.settings.save()
            self.image_name.set(candidate_path.name)
            self.recrop_button.configure(state="normal")
            self.apply_conversion()

        try:
            CropDialog(self.root, candidate_image, commit, None, self._image_options())
        except (OSError, ValueError) as exc:
            self.status.set(f"无法打开裁切确认页：请重新选择图片或稍后重试。({exc})")

    def recrop_image(self) -> None:
        if self.source_image is None:
            self.status.set("请先导入图片，再调整裁切区域。")
            return

        def commit(crop_box: CropBox) -> None:
            self.crop_box = crop_box
            self.apply_conversion()

        try:
            CropDialog(self.root, self.source_image, commit, self.crop_box, self._image_options())
        except (OSError, ValueError) as exc:
            self.status.set(f"无法打开裁切确认页：请稍后重试。({exc})")

    def _apply_if_image(self, *_args: object) -> None:
        if self.source_image is not None:
            self.apply_conversion()

    def apply_conversion(self) -> None:
        if self.source_image is None:
            self.status.set("请先导入 PNG 或 JPG/JPEG 图片。")
            return
        try:
            self.pattern = convert_image(self.source_image, self._image_options())
            self.status.set("转换完成：可点击画布格子，并在右侧点选游戏色号进行修正。")
            self._refresh_pattern()
        except (OSError, ValueError) as exc:
            self.status.set(f"转换失败：请调整构图或更换图片。({exc})")

    def _select_canvas_cell(self, event: object) -> None:
        x, y = event.x, event.y  # type: ignore[attr-defined]
        column, row = x // self.CELL_SIZE, y // self.CELL_SIZE
        if 0 <= row < GRID_SIZE and 0 <= column < GRID_SIZE:
            self.selected_cell = (row, column)
            self.selected_color.set(self.pattern.get_cell(row, column))
            self.status.set("已选中格子；在右侧色号表点选颜色即可修改。")
            self._refresh_pattern()

    def _select_palette_color(self, event: object) -> None:
        x, y = event.x, event.y  # type: ignore[attr-defined]
        column, row = x // 65, y // 36
        index = row * 4 + column
        if 0 <= index < len(PALETTE):
            self.selected_color.set(index)
            row_index, column_index = self.selected_cell
            self.pattern.set_cell(row_index, column_index, index)
            self._refresh_pattern()

    def _refresh_pattern(self) -> None:
        self.canvas.delete("all")
        for row, values in enumerate(self.pattern.cells):
            for column, index in enumerate(values):
                x0, y0 = column * self.CELL_SIZE, row * self.CELL_SIZE
                selected = (row, column) == self.selected_cell
                outline = ACCENT if selected else GRID_LINE
                width = 2 if selected else 1
                self.canvas.create_rectangle(x0, y0, x0 + self.CELL_SIZE, y0 + self.CELL_SIZE, fill=self._hex(PALETTE[index]), outline=outline, width=width)
                if self.show_numbers.get() and self.CELL_SIZE >= 18:
                    r, g, b = PALETTE[index]
                    luminance = 0.299 * r + 0.587 * g + 0.114 * b
                    text_color = "#0c0f0e" if luminance > 150 else "#ffffff"
                    shadow = "#ffffff" if luminance > 150 else "#0c0f0e"
                    cx, cy = x0 + self.CELL_SIZE / 2, y0 + self.CELL_SIZE / 2
                    label = str(index + 1)
                    # 对比阴影：任何底色下色号都清晰可读，方便对照游戏手动补色。
                    self.canvas.create_text(cx + 1, cy + 1, text=label, fill=shadow, font=("Microsoft YaHei UI", 9, "bold"))
                    self.canvas.create_text(cx, cy, text=label, fill=text_color, font=("Microsoft YaHei UI", 9, "bold"))
        self.palette_canvas.delete("all")
        for index, color in enumerate(PALETTE):
            column, row = index % 4, index // 4
            x0, y0 = column * 65, row * 36
            selected = index == self.selected_color.get()
            self.palette_canvas.create_rectangle(x0 + 2, y0 + 2, x0 + 62, y0 + 34, fill=self._hex(color), outline=ACCENT if selected else BORDER, width=3 if selected else 1)
            self.palette_canvas.create_text(x0 + 10, y0 + 18, text=str(index + 1).zfill(2), fill="#101413" if sum(color) > 420 else "#ffffff", anchor="w", font=("Cascadia Mono", 8, "bold"))
        row, column = self.selected_cell
        self.selected_info.set(f"当前格：第 {row + 1} 行 / 第 {column + 1} 列 · 色号 {palette_index_to_number(self.pattern.get_cell(row, column))}")
        self.count_info.set(f"自动填色将跳过白色 {576 - self.pattern.non_white_count} 格；需要点击 {self.pattern.non_white_count} 格。")
        self.calibration_info.set("已载入校准数据。" if self.calibration else "尚未校准：自动填色已锁定。")

    @staticmethod
    def _hex(color: tuple[int, int, int]) -> str:
        return "#%02x%02x%02x" % color

    def _choose_export_path(self, suffix: str) -> Path | None:
        stem = self.source_path.stem if self.source_path else "ark_pixel_pattern"
        filename = filedialog.asksaveasfilename(parent=self.root, title="选择导出位置", initialdir=self.settings.last_image_directory or initial_image_directory(), initialfile=f"{stem}{suffix}", defaultextension=suffix, filetypes=[("PNG 图纸", "*.png")] if suffix == ".png" else [("CSV 色号表", "*.csv")])
        return Path(filename) if filename else None

    def export_png(self) -> None:
        path = self._choose_export_path(".png")
        if path is None:
            return
        try:
            export_pattern_png(self.pattern, path, cell_size=32, show_numbers=True)
            self.status.set(f"图纸已导出：{path}")
        except (ExportError, ValueError) as exc:
            self.status.set(f"导出失败：{exc}")

    def export_csv(self) -> None:
        path = self._choose_export_path(".csv")
        if path is None:
            return
        try:
            export_pattern_csv(self.pattern, path)
            self.status.set(f"色号表已导出：{path}")
        except ExportError as exc:
            self.status.set(f"导出失败：{exc}")

    def open_calibration(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("捕获游戏窗口并识别画布")
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        preview_w = 480
        candidate: list[Calibration | None] = [None]
        status = StringVar(value="点击下方按钮后，3 秒内切到已打开的拼豆编辑器并保持前台。")

        ttk.Label(
            dialog,
            text="自动校准：捕获游戏窗口 → 截图识别 24×24 画布网格 → 预览确认。\n无需再手填坐标；识别失败会回退到居中视口估计并提示重试。",
            style="TLabel", wraplength=preview_w, padding=16,
        ).pack(anchor="w")

        preview = Canvas(dialog, width=preview_w, height=round(preview_w * 9 / 16), bg=CANVAS_BG, highlightthickness=1, highlightbackground=BORDER)
        preview.pack(padx=16, pady=(0, 8))
        ttk.Label(dialog, textvariable=status, style="Muted.TLabel", wraplength=preview_w, padding=(16, 4)).pack(anchor="w")

        def render(image: Image.Image, cal: Calibration, grid_used: bool, palette_used: bool) -> None:
            scale = preview_w / image.width
            disp_h = round(image.height * scale)
            preview.configure(height=disp_h)
            photo = ImageTk.PhotoImage(image.resize((preview_w, disp_h)))
            preview._photo = photo  # 防止被垃圾回收
            preview.delete("all")
            preview.create_image(0, 0, anchor="nw", image=photo)

            def box(rect: Rect, color: str, dash: tuple[int, int] | None = None) -> None:
                preview.create_rectangle(rect.x * scale, rect.y * scale, (rect.x + rect.width) * scale, (rect.y + rect.height) * scale, outline=color, width=2, dash=dash)

            box(cal.grid, ACCENT if grid_used else WARNING)
            box(cal.palette, HEADER_BOTTOM if palette_used else WARNING)

        def capture() -> None:
            status.set("请在 3 秒内切到游戏拼豆编辑器…")
            capture_button.configure(state="disabled")

            def read_target() -> None:
                try:
                    handle = foreground_window_handle()
                    process_id = window_process_id(handle)
                    client = get_foreground_client_area(handle)
                    shot = capture_client(handle)
                    cal, grid_used, palette_used = calibration_from_capture(client, shot, handle, process_id)
                    candidate[0] = cal
                    render(shot, cal, grid_used, palette_used)
                    grid_note = "画布绿框✔" if grid_used else "画布橙框（回退估计）"
                    palette_note = "色板蓝框✔" if palette_used else "色板橙框（回退估计）"
                    status.set(f"识别完成（进程 {process_id}）：{grid_note}，{palette_note}。核对无误点“确认使用”；有橙框可“重新识别”重试。")
                    confirm_button.configure(state="normal")
                    capture_button.configure(text="重新识别")
                except (CalibrationError, RuntimeError, OSError) as exc:
                    status.set(f"捕获失败：{exc}")
                finally:
                    capture_button.configure(state="normal")

            dialog.after(3000, read_target)

        def confirm() -> None:
            cal = candidate[0]
            if cal is None:
                status.set("请先捕获并识别游戏窗口。")
                return
            try:
                cal.save(calibration_path())
                self.calibration = cal
                dialog.destroy()
                self.status.set("校准已保存。开始自动填色前仍会重新读取当前前台游戏客户区并按比例换算。")
                self._refresh_pattern()
            except CalibrationError as exc:
                status.set(f"保存失败：{exc}")

        button_row = ttk.Frame(dialog, style="Panel.TFrame")
        button_row.pack(fill="x", padx=16, pady=16)
        capture_button = ttk.Button(button_row, text="3 秒后捕获并识别画布", command=capture)
        capture_button.pack(side="left", expand=True, fill="x", ipady=5, padx=(0, 6))
        confirm_button = ttk.Button(button_row, text="确认使用", command=confirm, style="Primary.TButton", state="disabled")
        confirm_button.pack(side="left", expand=True, fill="x", ipady=5)

    def start_autofill(self) -> None:
        if self.calibration is None or self.calibration.target_window is None or self.calibration.target_process_id is None:
            self.status.set("无法开始：请重新校准并捕获当前游戏拼豆编辑器窗口。")
            return
        if self.pattern.non_white_count == 0:
            self.status.set("当前图案全为白色；默认跳过白格，因此无需自动点击。")
            return
        message = "将以管理员权限、通过 SendInput 向当前前台游戏窗口发送鼠标点击，默认跳过白色格。\n\n确认后有 3 秒切换到已打开的拼豆编辑器；倒计时结束时必须让游戏保持前台。\n按 F8 或点击“停止后续点击”可安全中止；游戏失去前台也会自动停止。"
        if not messagebox.askokcancel("确认开始自动填色", message, icon="warning", parent=self.root):
            return
        self.cancel_event.clear()
        self.is_filling = True
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress_value.set(0)
        self.progress.set("准备中：请在 3 秒内切回游戏")
        self.status.set("已确认自动填色；正在等待前台游戏编辑器。")
        threading.Thread(target=self._autofill_worker, daemon=True).start()

    def _autofill_worker(self) -> None:
        try:
            for remaining in range(3, 0, -1):
                if self.cancel_event.is_set():
                    self._finish_autofill("已取消：未向游戏发送点击。")
                    return
                self.ui_events.put(("countdown", remaining))
                time.sleep(1)
            target_window = foreground_window_handle()
            target_process_id = window_process_id(target_window)
            if self.calibration is None or not window_matches_calibration(self.calibration, target_window, target_process_id):
                self._finish_autofill("自动填色未开始：当前前台窗口不是校准时确认的游戏窗口，因此未发送任何点击。")
                return
            client_area = get_foreground_client_area(target_window)
            driver = SendInputMouse(target_window)
            runner = AutoFillRunner(driver)
            scaled = self.calibration.for_client(client_area)

            def should_abort() -> bool:
                if f8_pressed():
                    self.cancel_event.set()
                if self.cancel_event.is_set():
                    return True
                return self.calibration is None or not is_calibrated_window_foreground(self.calibration)

            # 实时“认色块”选色：不靠滚动偏移，每色当场截图找它真正的色块（找不到就滚动再找）。
            palette = self.calibration.palette
            margin = max(8, round(palette.width * 0.06))
            palette_roi = (palette.x - margin, palette.y - margin, palette.x + palette.width + margin, palette.y + palette.height + margin)
            centers_cache: list[dict[int, tuple[float, float]] | None] = [None]
            last_shot: list[Image.Image | None] = [None]
            page_state = ["top"]  # 确定性翻页：顶页色号 1–24 / 底页 17–40

            debug_dir: Path | None = None
            if self.debug_fill.get():
                debug_dir = application_data_directory() / f"fill_debug_{int(time.time())}"
                debug_dir.mkdir(parents=True, exist_ok=True)
            debug_seq = [0]

            def refresh_centers() -> None:
                shot = capture_client(target_window)
                last_shot[0] = shot
                centers_cache[0] = swatch_centers(shot, palette_roi)

            def save_debug(color_index: int, position: tuple[float, float] | None) -> None:
                if debug_dir is None or last_shot[0] is None:
                    return
                debug_seq[0] += 1
                centers = centers_cache[0] or {}
                annotated = last_shot[0].convert("RGB").copy()
                draw = ImageDraw.Draw(annotated)
                for idx, (cx, cy) in centers.items():
                    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=(0, 255, 0), width=2)
                    draw.text((cx + 5, cy - 6), str(idx + 1), fill=(0, 255, 0))
                if position is not None:
                    px, py = position
                    draw.line((px - 10, py, px + 10, py), fill=(255, 0, 0), width=2)
                    draw.line((px, py - 10, px, py + 10), fill=(255, 0, 0), width=2)
                left, top, right, bottom = palette_roi
                pad = 30
                crop = annotated.crop((max(0, left - pad), max(0, top - pad), min(annotated.width, right + pad), min(annotated.height, bottom + pad)))
                crop.save(debug_dir / f"{debug_seq[0]:03d}_target{color_index + 1}_{page_state[0]}.png")
                found = "找到" if position is not None else "未找到"
                with open(debug_dir / "log.txt", "a", encoding="utf-8") as fh:
                    fh.write(f"#{debug_seq[0]:03d} 目标色号{color_index + 1} 页{page_state[0]} {found} 当前页识别到色号={sorted(i + 1 for i in centers)}\n")

            def scroll_palette(direction: int) -> None:
                # direction=-1 下翻（露出底页 17–40），+1 上翻（回顶页）；过量滚动 saturate 到末页。
                anchor_x, anchor_y = scaled.scroll_point()
                for _ in range(12):
                    driver.scroll(direction, anchor_x, anchor_y)
                time.sleep(0.35)  # 等滚动动画停稳再截图，避免抓到过渡态
                centers_cache[0] = None

            def ensure_page(color_index: int) -> None:
                if color_index >= 24:
                    need = "bottom"
                elif color_index < 16:
                    need = "top"
                else:
                    need = page_state[0]  # 17–24 两页都有，不必翻页
                if need != page_state[0]:
                    scroll_palette(-1 if need == "bottom" else 1)
                    page_state[0] = need

            def select_color(color_index: int) -> bool:
                # 确定性两遍式：先确保在目标页（只在 top→bottom 翻一次），再在稳定页面上认色块。
                if should_abort():
                    return False
                ensure_page(color_index)
                if centers_cache[0] is None:
                    refresh_centers()
                position = centers_cache[0].get(color_index) if centers_cache[0] else None
                save_debug(color_index, position)
                if position is not None:
                    driver.click(client_area.left + round(position[0]), client_area.top + round(position[1]))
                    return True
                return False

            def reset_palette_to_top() -> None:
                # 把色板滚回顶页并置页状态，保证从色号 0 开始能找到。
                scroll_palette(1)
                page_state[0] = "top"

            def sample_rendered() -> list[list[int]]:
                shot = capture_client(target_window)
                grid: list[list[int]] = []
                for row in range(24):
                    line: list[int] = []
                    for column in range(24):
                        sx, sy = scaled.grid_cell_center(row, column)
                        rx = min(max(0, round(sx - client_area.left)), shot.width - 1)
                        ry = min(max(0, round(sy - client_area.top)), shot.height - 1)
                        line.append(nearest_palette_index(shot.getpixel((rx, ry)), "rgb"))
                    grid.append(line)
                return grid

            reset_palette_to_top()
            completed = runner.run(
                self.pattern,
                self.calibration,
                self.cancel_event,
                self._on_progress,
                client_area,
                should_abort=should_abort,
                select_color=select_color,
            )
            # 填后复检：截图比对图案，只重填“应上色却不符”的格子（漏格/错色），幂等安全，最多 2 遍。
            if completed and not self.cancel_event.is_set():
                for _ in range(2):
                    if should_abort():
                        break
                    residual = build_residual_pattern(self.pattern, sample_rendered())
                    if residual.non_white_count == 0:
                        break
                    self.ui_events.put(("finish", f"复检补漏中：还有 {residual.non_white_count} 格待修…"))
                    reset_palette_to_top()
                    runner.run(residual, self.calibration, self.cancel_event, self._on_progress, client_area, should_abort=should_abort, select_color=select_color)
            done_msg = "自动填色完成（已复检补漏）。如仍有个别格不对，可开“显示色号”对照手动修改。"
            if debug_dir is not None:
                done_msg = f"自动填色完成。调试图已保存到：{debug_dir}（请整个文件夹发给开发者排错）。"
            self._finish_autofill(done_msg if completed else "自动填色已停止：游戏窗口失去前台或用户已取消；已完成部分保留在游戏画布，可按图纸继续。")
        except Exception as exc:  # pyautogui 的安全停止异常也必须恢复界面。
            self._finish_autofill(f"自动填色未开始或已中断：{exc}。请确认游戏为前台、校准有效后重试。")

    def _on_progress(self, progress: tuple[int, int]) -> None:
        self.ui_events.put(("progress", progress))

    def _finish_autofill(self, status: str) -> None:
        self.ui_events.put(("finish", status))

    def _finish_autofill_ui(self, status: str) -> None:
        self.is_filling = False
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status.set(status)
        self.progress_value.set(100 if not self.cancel_event.is_set() and status == "自动填色完成。" else self.progress_value.get())
        self.progress.set("已完成" if not self.cancel_event.is_set() else "已停止")

    def cancel_autofill(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("已请求停止：当前点击完成后不会再向任何窗口发送点击。")


def enable_high_dpi_awareness() -> None:
    """在创建 tkinter 窗口前启用高 DPI 坐标，避免 Windows 坐标虚拟化。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        # Windows 10 1703+；失败时回退到旧版 API，不阻断图纸功能。
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def run() -> None:
    enable_high_dpi_awareness()
    root = Tk()
    PixelHelperApp(root)
    root.mainloop()
