"""从 Pattern 唯一编辑状态导出手工填色图纸。"""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .palette import PALETTE, palette_index_to_number
from .pattern import GRID_SIZE, Pattern


class ExportError(RuntimeError):
    """用户可以据此选择其他导出位置的导出错误。"""


def export_pattern_png(pattern: Pattern, path: str | Path, cell_size: int = 32, show_numbers: bool = True) -> Path:
    if cell_size < 8:
        raise ValueError("图纸格子尺寸至少为 8 像素")
    output = Path(path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (GRID_SIZE * cell_size, GRID_SIZE * cell_size), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for row, cells in enumerate(pattern.cells):
            for column, index in enumerate(cells):
                x0, y0 = column * cell_size, row * cell_size
                draw.rectangle((x0, y0, x0 + cell_size - 1, y0 + cell_size - 1), fill=PALETTE[index])
                if show_numbers and cell_size >= 16:
                    label = str(palette_index_to_number(index))
                    box = draw.textbbox((0, 0), label, font=font)
                    draw.text((x0 + (cell_size - (box[2] - box[0])) / 2, y0 + (cell_size - (box[3] - box[1])) / 2), label, fill="black", font=font)
        for position in range(0, GRID_SIZE * cell_size + 1, cell_size):
            draw.line((position, 0, position, GRID_SIZE * cell_size), fill=(48, 54, 52), width=1)
            draw.line((0, position, GRID_SIZE * cell_size, position), fill=(48, 54, 52), width=1)
        image.save(output, "PNG")
    except OSError as exc:
        raise ExportError(f"无法导出图纸到“{output}”，请检查目录权限或文件占用。") from exc
    return output


def export_pattern_csv(pattern: Pattern, path: str | Path) -> Path:
    output = Path(path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerows([[palette_index_to_number(index) for index in row] for row in pattern.cells])
    except OSError as exc:
        raise ExportError(f"无法导出色号表到“{output}”，请检查目录权限或文件占用。") from exc
    return output
