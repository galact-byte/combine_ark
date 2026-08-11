"""按已知 40 色在游戏截图里"认色板"，反推顶部色板矩形。

对 UI 缩放 / 分辨率免疫：不靠固定比例或锚定画布，而是用每个色号精确 RGB
在画布右侧面板里定位色块中心，再拟合 4×6 色板网格。跳过黑/灰/白(索引0-3)
这些与 UI 灰底/白底易混的色，用彩色(4-23)做稳健拟合。
"""

from __future__ import annotations

from PIL import Image

from .calibration import Rect
from .palette import PALETTE

_TOP_PAGE_ROWS = 6


def _nearest_index(r: int, g: int, b: int, tol_sq: int) -> int | None:
    best: int | None = None
    best_d = tol_sq
    for index, color in enumerate(PALETTE):
        d = (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2
        if d < best_d:
            best_d = d
            best = index
    return best


def _swatch_centers(image: Image.Image, roi: tuple[int, int, int, int], tol: int, min_pixels: int) -> dict[int, tuple[float, float]]:
    left = max(0, roi[0])
    top = max(0, roi[1])
    right = min(image.width, roi[2])
    bottom = min(image.height, roi[3])
    if right - left <= 0 or bottom - top <= 0:
        return {}
    crop = image.convert("RGB").crop((left, top, right, bottom))
    width0, height0 = crop.size
    # 降采样加速（最近邻保持色块纯色），中心坐标再乘回原尺度。
    target = 360
    factor = width0 / target if width0 > target else 1.0
    if factor > 1.0:
        crop = crop.resize((target, max(1, round(height0 / factor))), Image.NEAREST)
    width, height = crop.size
    data = crop.tobytes()
    tol_sq = tol * tol
    min_scaled = max(10, round(min_pixels / (factor * factor)))
    acc: dict[int, list[float]] = {}
    for y in range(height):
        base = y * width * 3
        for x in range(width):
            p = base + x * 3
            index = _nearest_index(data[p], data[p + 1], data[p + 2], tol_sq)
            if index is not None:
                cell = acc.get(index)
                if cell is None:
                    cell = [0.0, 0.0, 0.0]
                    acc[index] = cell
                cell[0] += x
                cell[1] += y
                cell[2] += 1
    return {
        index: (cell[0] / cell[2] * factor + left, cell[1] / cell[2] * factor + top)
        for index, cell in acc.items()
        if cell[2] >= min_scaled
    }


def _linfit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    n = len(points)
    if n < 2:
        return None
    st = sum(t for t, _ in points)
    sv = sum(v for _, v in points)
    stt = sum(t * t for t, _ in points)
    stv = sum(t * v for t, v in points)
    denom = n * stt - st * st
    if denom == 0:
        return None
    slope = (n * stv - st * sv) / denom
    intercept = (sv - slope * st) / n
    return slope, intercept


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def detect_palette_rect(image: Image.Image, canvas_grid_rect: Rect, tol: int = 35, min_pixels: int = 80) -> Rect | None:
    """识别顶部色板矩形（4 列 × 6 行，色号 1–24）；失败返回 None 由调用方回退。"""
    margin = round(canvas_grid_rect.width * 0.05)
    roi = (canvas_grid_rect.x + canvas_grid_rect.width + margin, 0, image.width, image.height)
    centers = _swatch_centers(image, roi, tol, min_pixels)
    usable = {index: center for index, center in centers.items() if 4 <= index < 24}
    if len(usable) < 8 or len({i % 4 for i in usable}) < 4 or len({i // 4 for i in usable}) < 3:
        return None
    col_points = [(col, _median([c[0] for i, c in usable.items() if i % 4 == col])) for col in range(4) if any(i % 4 == col for i in usable)]
    row_points = [(row, _median([c[1] for i, c in usable.items() if i // 4 == row])) for row in range(_TOP_PAGE_ROWS) if any(i // 4 == row for i in usable)]
    col_fit = _linfit(col_points)
    row_fit = _linfit(row_points)
    if col_fit is None or row_fit is None:
        return None
    a, b = col_fit  # cx = a*col + b，a=width/4，b=x+a/2
    e, f = row_fit  # cy = e*row + f，e=height/6，f=y+e/2
    if a <= 0 or e <= 0:
        return None
    width = a * 4
    height = e * _TOP_PAGE_ROWS
    if width <= 0 or height <= 0:
        return None
    return Rect(round(b - a / 2), round(f - e / 2), round(width), round(height))
