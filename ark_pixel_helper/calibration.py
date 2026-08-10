"""游戏客户区相对坐标的校准、缩放和本地持久化。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


class CalibrationError(ValueError):
    """校准数据无法安全用于鼠标点击。"""


@dataclass(frozen=True)
class ClientArea:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise CalibrationError("游戏客户区宽高必须为正数")


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise CalibrationError("校准矩形宽高必须为正数")


@dataclass(frozen=True)
class Calibration:
    reference_client: ClientArea
    grid: Rect
    palette: Rect
    scroll_anchor: tuple[int, int]
    lower_palette: Rect | None = None
    scroll_clicks: int = 0
    target_window: int | None = None
    target_process_id: int | None = None

    def __post_init__(self) -> None:
        self._validate_rect(self.grid, "画布")
        self._validate_rect(self.palette, "顶部色板")
        if self.lower_palette is not None:
            self._validate_rect(self.lower_palette, "底部色板")
        anchor_x, anchor_y = self.scroll_anchor
        if not 0 <= anchor_x < self.reference_client.width or not 0 <= anchor_y < self.reference_client.height:
            raise CalibrationError("滚动锚点必须位于游戏客户区内")
        if self.grid.width < 24 or self.grid.height < 24:
            raise CalibrationError("画布校准尺寸过小，无法容纳完整的 24×24 网格")
        if self.palette.width < 4 or self.palette.height < 6:
            raise CalibrationError("顶部色板校准尺寸过小，无法容纳 4×6 个可见色块")
        if self.lower_palette is not None and (self.lower_palette.width < 4 or self.lower_palette.height < 6):
            raise CalibrationError("底部色板校准尺寸过小，无法容纳 4×6 个可见色块")
        if self.scroll_clicks < 0:
            raise CalibrationError("色板滚动量不能为负数")
        if (self.target_window is None) != (self.target_process_id is None):
            raise CalibrationError("目标游戏窗口和进程标识必须同时保存")
        if self.target_window is not None and self.target_window <= 0:
            raise CalibrationError("目标游戏窗口标识无效；请重新捕获游戏窗口")
        if self.target_process_id is not None and self.target_process_id <= 0:
            raise CalibrationError("目标游戏进程标识无效；请重新捕获游戏窗口")
        if self.lower_palette is not None and self.scroll_clicks == 0:
            raise CalibrationError("已设置底部色板时，必须填写滚动量")

    def _validate_rect(self, rect: Rect, label: str) -> None:
        if rect.x < 0 or rect.y < 0 or rect.x + rect.width > self.reference_client.width or rect.y + rect.height > self.reference_client.height:
            raise CalibrationError(f"{label}必须完整位于游戏客户区内")

    def for_client(self, current: ClientArea) -> ScaledCalibration:
        return ScaledCalibration(self, current, current.width / self.reference_client.width, current.height / self.reference_client.height)

    def save(self, path: str | Path) -> Path:
        output = Path(path)
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise CalibrationError("无法保存校准数据，请检查本地应用数据目录权限。") from exc
        return output

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            reference = raw["reference_client"]
            grid = raw["grid"]
            palette = raw["palette"]
            anchor = raw["scroll_anchor"]
            lower_palette = raw.get("lower_palette")
            scroll_clicks = raw.get("scroll_clicks", 0)
            if not isinstance(anchor, list) or len(anchor) != 2:
                raise CalibrationError("滚动锚点数据无效")
            return cls(
                ClientArea(**reference),
                Rect(**grid),
                Rect(**palette),
                (int(anchor[0]), int(anchor[1])),
                Rect(**lower_palette) if lower_palette is not None else None,
                int(scroll_clicks),
                int(raw["target_window"]) if raw.get("target_window") is not None else None,
                int(raw["target_process_id"]) if raw.get("target_process_id") is not None else None,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, CalibrationError):
                raise
            raise CalibrationError("校准文件无效，请重新完成手动校准。") from exc


def suggested_layout(client: ClientArea) -> "Calibration":
    """以 1280×720 参考编辑器几何按当前客户区比例生成建议校准，供用户微调。"""
    def sx(value: float) -> int:
        return round(value / 1280 * client.width)

    def sy(value: float) -> int:
        return round(value / 720 * client.height)

    grid = Rect(sx(295), sy(119), sx(561), sy(561))
    palette = Rect(sx(954), sy(250), sx(281), sy(420))
    lower_palette = Rect(sx(954), sy(264), sx(281), sy(420))
    return Calibration(client, grid, palette, (sx(1100), sy(600)), lower_palette=lower_palette, scroll_clicks=4)


@dataclass(frozen=True)
class ScaledCalibration:
    source: Calibration
    client: ClientArea
    x_scale: float
    y_scale: float

    def _point(self, x: float, y: float) -> tuple[int, int]:
        return (round(self.client.left + x * self.x_scale), round(self.client.top + y * self.y_scale))

    def grid_cell_center(self, row: int, column: int) -> tuple[int, int]:
        if not 0 <= row < 24 or not 0 <= column < 24:
            raise CalibrationError("画布格子坐标必须在 0 到 23 之间")
        grid = self.source.grid
        return self._point(grid.x + grid.width * (column + 0.5) / 24, grid.y + grid.height * (row + 0.5) / 24)

    def palette_center(self, color_index: int, position: str) -> tuple[int, int]:
        if not 0 <= color_index < 40 or position not in ("top", "bottom"):
            raise CalibrationError("色板色号或位置无效")
        displayed_index = color_index if position == "top" else color_index - 16
        if not 0 <= displayed_index < 24:
            raise CalibrationError("该颜色不在当前色板可视区域")
        if position == "bottom" and self.source.lower_palette is None:
            raise CalibrationError("后 16 色尚未校准；请滚动色板到底部后完成底部色板校准")
        palette = self.source.palette if position == "top" else self.source.lower_palette
        assert palette is not None
        column, row = displayed_index % 4, displayed_index // 4
        return self._point(palette.x + palette.width * (column + 0.5) / 4, palette.y + palette.height * (row + 0.5) / 6)

    def scroll_point(self) -> tuple[int, int]:
        return self._point(*self.source.scroll_anchor)
