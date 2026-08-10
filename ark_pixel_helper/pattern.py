"""可编辑且严格受限于 24×24 游戏画布的图案模型。"""

from __future__ import annotations

from dataclasses import dataclass

from .palette import PALETTE, WHITE_INDEX

GRID_SIZE = 24


@dataclass
class Pattern:
    cells: list[list[int]]

    def __post_init__(self) -> None:
        if len(self.cells) != GRID_SIZE or any(len(row) != GRID_SIZE for row in self.cells):
            raise ValueError("图案必须严格为 24×24 格")
        if any(not isinstance(value, int) or not 0 <= value < len(PALETTE) for row in self.cells for value in row):
            raise ValueError("图案色号必须是 0 到 39 的整数")

    @classmethod
    def blank(cls, color_index: int = WHITE_INDEX) -> Pattern:
        if not 0 <= color_index < len(PALETTE):
            raise ValueError("默认色号无效")
        return cls([[color_index for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)])

    @property
    def non_white_count(self) -> int:
        return sum(cell != WHITE_INDEX for row in self.cells for cell in row)

    def get_cell(self, row: int, column: int) -> int:
        self._validate_coordinate(row, column)
        return self.cells[row][column]

    def set_cell(self, row: int, column: int, color_index: int) -> None:
        self._validate_coordinate(row, column)
        if not 0 <= color_index < len(PALETTE):
            raise ValueError("图案色号必须是 0 到 39 的整数")
        self.cells[row][column] = color_index

    @staticmethod
    def _validate_coordinate(row: int, column: int) -> None:
        if not 0 <= row < GRID_SIZE or not 0 <= column < GRID_SIZE:
            raise ValueError("格子坐标必须在 0 到 23 之间")
