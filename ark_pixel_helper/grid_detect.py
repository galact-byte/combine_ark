"""从游戏客户区截图中识别 24×24 画布的网格线，反推每格中心。

纯函数、仅依赖 Pillow：输入 PIL Image，输出识别到的网格线与置信度。
不涉及任何 Win32 或 GUI，便于用合成网格图做单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

# 相对能量阈值：低于峰值该比例的列/行不视为网格线候选。
_PEAK_RATIO = 0.35


@dataclass(frozen=True)
class GridResult:
    """一次网格识别的结果。x_lines / y_lines 为全图坐标下的线位置（升序）。"""

    cells_bbox: tuple[int, int, int, int]  # (left, top, right, bottom)
    x_lines: list[float]
    y_lines: list[float]
    confidence: float

    def cell_center(self, row: int, column: int) -> tuple[float, float]:
        if not 0 <= row < len(self.y_lines) - 1 or not 0 <= column < len(self.x_lines) - 1:
            raise ValueError("格子坐标超出识别到的网格范围")
        x = (self.x_lines[column] + self.x_lines[column + 1]) / 2
        y = (self.y_lines[row] + self.y_lines[row + 1]) / 2
        return (x, y)


def _projections(data: bytes, width: int, height: int) -> tuple[list[float], list[float]]:
    """一次遍历得到列方向与行方向的梯度能量投影。"""
    col_energy = [0.0] * width
    row_energy = [0.0] * height
    up = [0] * width
    for y in range(height):
        base = y * width
        left = data[base]
        for x in range(width):
            cur = data[base + x]
            if x > 0:
                d = cur - left
                col_energy[x] += d if d >= 0 else -d
            if y > 0:
                dv = cur - up[x]
                row_energy[y] += dv if dv >= 0 else -dv
            left = cur
            up[x] = cur
    return col_energy, row_energy


def _find_lines(energy: list[float]) -> list[float]:
    """在 1D 能量信号上找出网格线：阈值以上的连续簇取能量加权质心。"""
    peak = max(energy) if energy else 0.0
    if peak <= 0:
        return []
    threshold = peak * _PEAK_RATIO
    lines: list[float] = []
    index = 0
    n = len(energy)
    while index < n:
        if energy[index] >= threshold:
            end = index
            while end < n and energy[end] >= threshold:
                end += 1
            weight = sum(energy[k] for k in range(index, end))
            centroid = sum(k * energy[k] for k in range(index, end)) / weight
            lines.append(centroid)
            index = end
        else:
            index += 1
    return lines


def _score(lines: list[float], expected: int, tol: float) -> float:
    """按数量接近度与间距均匀度给这一轴的识别打分（0..1）。"""
    if len(lines) < 2 or len(lines) < expected * 0.6:
        return 0.0
    diffs = [b - a for a, b in zip(lines, lines[1:])]
    ordered = sorted(diffs)
    median = ordered[len(ordered) // 2]
    if median <= 0:
        return 0.0
    within = sum(1 for d in diffs if abs(d - median) <= tol * median)
    uniformity = within / len(diffs)
    count_score = 1.0 - min(1.0, abs(len(lines) - expected) / expected)
    return uniformity * count_score


def detect_grid(
    image: Image.Image,
    roi: tuple[int, int, int, int] | None = None,
    expected_cells: int = 24,
    tol: float = 0.15,
    min_confidence: float = 0.6,
) -> GridResult | None:
    """识别画布网格。置信度不足时返回 None，由调用方回退到视口种子几何。"""
    expected_lines = expected_cells + 1
    gray = image.convert("L")
    origin_x, origin_y = 0, 0
    if roi is not None:
        left, top, right, bottom = (max(0, roi[0]), max(0, roi[1]), min(image.width, roi[2]), min(image.height, roi[3]))
        if right - left < expected_lines or bottom - top < expected_lines:
            return None
        gray = gray.crop((left, top, right, bottom))
        origin_x, origin_y = left, top
    width, height = gray.size
    if width < expected_lines or height < expected_lines:
        return None
    col_energy, row_energy = _projections(gray.tobytes(), width, height)
    x_lines = [x + origin_x for x in _find_lines(col_energy)]
    y_lines = [y + origin_y for y in _find_lines(row_energy)]
    confidence = min(_score(x_lines, expected_lines, tol), _score(y_lines, expected_lines, tol))
    if confidence < min_confidence or len(x_lines) < 2 or len(y_lines) < 2:
        return None
    bbox = (round(x_lines[0]), round(y_lines[0]), round(x_lines[-1]), round(y_lines[-1]))
    return GridResult(bbox, x_lines, y_lines, confidence)
