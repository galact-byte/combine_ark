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


def _fit_axis(energy: list[float], cells: int) -> tuple[float, float, float] | None:
    """网格拟合：已知 cells 格（cells+1 条线），搜索最优“起点+格距”使 25 条预测线总能量最大。

    对粗线（能量极强）与细线缺失都鲁棒：粗线只会帮忙锡定相位。返回 (起点, 格距, 峰/基线比)。"""
    n = len(energy)
    if n < cells + 1:
        return None
    smoothed = [energy[max(0, i - 1)] + energy[i] + energy[min(n - 1, i + 1)] for i in range(n)]
    total = sum(smoothed)
    if total <= 0:
        return None
    baseline = total / n

    def score(left: float, pitch: float) -> float:
        acc = 0.0
        for k in range(cells + 1):
            index = int(round(left + k * pitch))
            if 0 <= index < n:
                acc += smoothed[index]
        return acc

    best_score, best_left, best_pitch = -1.0, 0.0, 0.0
    pitch = (n * 0.5) / cells
    pitch_max = (n * 1.0) / cells
    while pitch <= pitch_max:
        max_left = n - 1 - cells * pitch
        left = 0.0
        while left <= max_left:
            current = score(left, pitch)
            if current > best_score:
                best_score, best_left, best_pitch = current, left, pitch
            left += 1.0
        pitch += 0.2
    if best_pitch <= 0:
        return None
    # 亚像素细化
    refined_left, refined_pitch = best_left, best_pitch
    left = best_left - 1.5
    while left <= best_left + 1.5:
        pitch = best_pitch - 0.3
        while pitch <= best_pitch + 0.3:
            if pitch > 0:
                current = score(left, pitch)
                if current > best_score:
                    best_score, refined_left, refined_pitch = current, left, pitch
            pitch += 0.05
        left += 0.25
    ratio = (best_score / (cells + 1)) / baseline if baseline > 0 else 0.0
    return refined_left, refined_pitch, ratio


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
    fit_x = _fit_axis(col_energy, expected_cells)
    fit_y = _fit_axis(row_energy, expected_cells)
    if fit_x is None or fit_y is None:
        return None
    left_x, pitch_x, ratio_x = fit_x
    left_y, pitch_y, ratio_y = fit_y
    # 峰/基线比 → 置信度：约 1 为无网格，越大线越清晰。
    confidence = min(max(0.0, (ratio_x - 1.3) / 2.0), max(0.0, (ratio_y - 1.3) / 2.0))
    confidence = min(1.0, confidence)
    if confidence < min_confidence:
        return None
    x_lines = [origin_x + left_x + k * pitch_x for k in range(expected_lines)]
    y_lines = [origin_y + left_y + k * pitch_y for k in range(expected_lines)]
    bbox = (round(x_lines[0]), round(y_lines[0]), round(x_lines[-1]), round(y_lines[-1]))
    return GridResult(bbox, x_lines, y_lines, confidence)
