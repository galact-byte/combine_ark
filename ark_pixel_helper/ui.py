"""简体中文 tkinter 战术像素编辑器界面。"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter import Canvas

from PIL import Image

from .autofill import AutoFillRunner, PyAutoGuiMouse
from .calibration import Calibration, CalibrationError, ClientArea, Rect, suggested_layout
from .export import ExportError, export_pattern_csv, export_pattern_png
from .image_pipeline import ImageOptions, convert_image
from .palette import PALETTE, palette_index_to_number
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
    CELL_SIZE = 22

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("奇象巡展 · 像素拼豆助手")
        self.root.minsize(1170, 760)
        self.root.configure(bg=BG)
        self.settings = AppSettings.load()
        self.source_image: Image.Image | None = None
        self.source_path: Path | None = None
        self.pattern = Pattern.blank()
        self.selected_cell = (0, 0)
        self.calibration: Calibration | None = self._load_calibration()
        self.cancel_event = threading.Event()
        self.ui_events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.is_filling = False

        self.fit_mode = StringVar(value="裁剪（可调构图）")
        self.resample = StringVar(value="平滑取样（照片 / 插画）")
        self.reduce_colors = BooleanVar(value=True)
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
        ttk.Label(parent, text="图片只在本机处理，不会上传。", style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(6, 8))
        ttk.Label(parent, text="正方形构图", style="TLabel").pack(anchor="w")
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
        ttk.Checkbutton(parent, text="减少杂色（保留最多 16 个主色）", variable=self.reduce_colors, command=self._apply_if_image).pack(anchor="w", pady=(2, 4))
        ttk.Checkbutton(parent, text="可选抖动（关闭减少杂色后生效）", variable=self.dither, command=self._apply_if_image).pack(anchor="w", pady=(0, 10))
        ttk.Button(parent, text="应用转换到 24×24 图案", command=self.apply_conversion, style="Primary.TButton").pack(fill="x", ipady=7)
        ttk.Label(parent, text="顺序：导图 → 调整效果 → 检查图纸 → 打开游戏 → 自动填色", style="Muted.TLabel", wraplength=230).pack(anchor="w", pady=(10, 0))

    def _build_canvas(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="实时预览", style="Section.TLabel").pack(side="left")
        ttk.Checkbutton(top, text="显示色号", variable=self.show_numbers, command=self._refresh_pattern).pack(side="right")
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
        ttk.Button(parent, text="手动校准游戏画布与色板", command=self.open_calibration).pack(fill="x", ipady=5)
        self.start_button = ttk.Button(parent, text="开始自动填色（需确认）", command=self.start_autofill, style="Warning.TButton")
        self.start_button.pack(fill="x", ipady=6, pady=(8, 0))
        self.cancel_button = ttk.Button(parent, text="停止后续点击", command=self.cancel_autofill, state="disabled")
        self.cancel_button.pack(fill="x", ipady=6, pady=(6, 0))

    def _load_calibration(self) -> Calibration | None:
        try:
            return Calibration.load(calibration_path())
        except CalibrationError:
            return None

    def _image_options(self) -> ImageOptions:
        return ImageOptions(
            fit_mode={"裁剪（可调构图）": "crop", "完整包含（白底留白）": "contain", "拉伸": "stretch"}[self.fit_mode.get()],
            resample="nearest" if self.resample.get().startswith("最近邻") else "smooth",
            reduce_colors=self.reduce_colors.get(),
            dither=self.dither.get(),
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
                self.source_image = image.copy()
            self.source_path = Path(filename)
            self.settings.last_image_directory = self.source_path.parent
            self.settings.save()
            self.image_name.set(self.source_path.name)
            self.apply_conversion()
        except (OSError, ValueError) as exc:
            self.status.set(f"导入失败：无法读取该图片。请确认它是未损坏的 PNG 或 JPG/JPEG。({exc})")

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
                    text_color = "#101413" if sum(PALETTE[index]) > 420 else "#f5f7f6"
                    self.canvas.create_text(x0 + self.CELL_SIZE / 2, y0 + self.CELL_SIZE / 2, text=str(index + 1), fill=text_color, font=("Cascadia Mono", 7))
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
        dialog.title("手动校准游戏画布与色板")
        dialog.configure(bg=SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()
        fields = (("客户区左上 X", ""), ("客户区左上 Y", ""), ("客户区宽", ""), ("客户区高", ""), ("画布左上 X（相对客户区）", ""), ("画布左上 Y（相对客户区）", ""), ("画布宽", ""), ("画布高", ""), ("顶部色板左上 X（相对客户区）", ""), ("顶部色板左上 Y（相对客户区）", ""), ("顶部色板宽", ""), ("顶部色板可视高（6行）", ""), ("滚轮锚点 X（相对客户区）", ""), ("滚轮锚点 Y（相对客户区）", ""), ("底部色板左上 X（滚到底后）", ""), ("底部色板左上 Y（滚到底后）", ""), ("底部色板宽", ""), ("底部色板可视高（6行）", ""), ("滚到底所需滚轮档数", ""))
        defaults = self.calibration
        lower = defaults.lower_palette if defaults else None
        existing = [str(value) for value in (
            defaults.reference_client.left, defaults.reference_client.top, defaults.reference_client.width, defaults.reference_client.height,
            defaults.grid.x, defaults.grid.y, defaults.grid.width, defaults.grid.height,
            defaults.palette.x, defaults.palette.y, defaults.palette.width, defaults.palette.height,
            *defaults.scroll_anchor,
            lower.x if lower else "", lower.y if lower else "", lower.width if lower else "", lower.height if lower else "",
            defaults.scroll_clicks,
        )] if defaults else [item[1] for item in fields]
        entries: list[ttk.Entry] = []
        captured_target: list[tuple[int, int] | None] = [None]
        capture_status = StringVar(value="未捕获游戏窗口：保存后无法启动自动绘制。")
        ttk.Label(dialog, text="校准使用当前游戏客户区的相对位置，任何窗口尺寸 / DPI 下均按比例换算。\n先点击捕获按钮，3 秒内切到已打开的游戏编辑器；再填写画布、顶部色板、底部色板和滚轮数据。", style="TLabel", wraplength=500, padding=16).grid(row=0, column=0, columnspan=2, sticky="w")
        for row, ((label, _), value) in enumerate(zip(fields, existing), 1):
            ttk.Label(dialog, text=label, style="TLabel", padding=(16, 3)).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(dialog, width=16)
            entry.insert(0, value)
            entry.grid(row=row, column=1, padx=(8, 16), pady=3, sticky="ew")
            entries.append(entry)

        def capture_game_window() -> None:
            capture_status.set("请在 3 秒内切到游戏拼豆编辑器…")
            capture_button.configure(state="disabled")

            def read_target() -> None:
                try:
                    handle = foreground_window_handle()
                    process_id = window_process_id(handle)
                    client = get_foreground_client_area(handle)
                    captured_target[0] = (handle, process_id)
                    guess = suggested_layout(client)
                    suggested_values = (
                        client.left, client.top, client.width, client.height,
                        guess.grid.x, guess.grid.y, guess.grid.width, guess.grid.height,
                        guess.palette.x, guess.palette.y, guess.palette.width, guess.palette.height,
                        guess.scroll_anchor[0], guess.scroll_anchor[1],
                        guess.lower_palette.x, guess.lower_palette.y, guess.lower_palette.width, guess.lower_palette.height,
                        guess.scroll_clicks,
                    )
                    for index, value in enumerate(suggested_values):
                        entries[index].delete(0, "end")
                        entries[index].insert(0, str(value))
                    capture_status.set(f"已捕获游戏窗口（进程 {process_id}）并自动填入建议值；请对照游戏微调画布和色板区域后保存。")
                except CalibrationError as exc:
                    capture_status.set(f"捕获失败：{exc}")
                finally:
                    capture_button.configure(state="normal")

            dialog.after(3000, read_target)

        capture_button = ttk.Button(dialog, text="3 秒后捕获当前游戏窗口", command=capture_game_window)
        capture_button.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 4), ipady=5)
        ttk.Label(dialog, textvariable=capture_status, style="Muted.TLabel", wraplength=500, padding=(16, 4)).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="w")

        def save() -> None:
            try:
                if captured_target[0] is None:
                    raise CalibrationError("请先使用“3 秒后捕获当前游戏窗口”，并在倒计时结束时保持游戏编辑器为前台")
                values = [int(entry.get()) for entry in entries]
                target_window, target_process_id = captured_target[0]
                self.calibration = Calibration(
                    ClientArea(*values[:4]),
                    Rect(*values[4:8]),
                    Rect(*values[8:12]),
                    tuple(values[12:14]),
                    lower_palette=Rect(*values[14:18]),
                    scroll_clicks=values[18],
                    target_window=target_window,
                    target_process_id=target_process_id,
                )
                self.calibration.save(calibration_path())
                dialog.destroy()
                self.status.set("校准已保存到本机应用数据目录。开始自动填色前仍会读取当前前台游戏客户区。")
                self._refresh_pattern()
            except (ValueError, CalibrationError) as exc:
                messagebox.showerror("校准数据无效", f"请检查全部数值；宽高必须为正数。\n{exc}", parent=dialog)

        ttk.Button(dialog, text="保存校准", command=save, style="Primary.TButton").grid(row=len(fields) + 3, column=0, columnspan=2, sticky="ew", padx=16, pady=16, ipady=5)

    def start_autofill(self) -> None:
        if self.calibration is None or self.calibration.target_window is None or self.calibration.target_process_id is None:
            self.status.set("无法开始：请重新校准并捕获当前游戏拼豆编辑器窗口。")
            return
        if self.pattern.non_white_count == 0:
            self.status.set("当前图案全为白色；默认跳过白格，因此无需自动点击。")
            return
        message = "将向当前前台游戏窗口发送鼠标点击，默认跳过白色格。\n\n确认后有 3 秒切换到已打开的拼豆编辑器；倒计时结束时必须让游戏保持前台。\n鼠标移到屏幕左上角或点击“停止后续点击”可安全中止。"
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
            runner = AutoFillRunner(PyAutoGuiMouse())
            completed = runner.run(
                self.pattern,
                self.calibration,
                self.cancel_event,
                self._on_progress,
                client_area,
                lambda: self.calibration is not None and is_calibrated_window_foreground(self.calibration),
            )
            self._finish_autofill("自动填色完成。" if completed else "自动填色已停止：游戏窗口失去前台或用户已取消；已完成部分保留在游戏画布，可按图纸继续。")
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
