"""经用户确认后，按校准数据向前台游戏画布发送安全鼠标输入。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Literal, Protocol

from .calibration import Calibration, ClientArea
from .palette import WHITE_INDEX
from .pattern import Pattern


class MouseDriver(Protocol):
    def click(self, x: int, y: int) -> None: ...

    def scroll(self, clicks: int, x: int, y: int) -> None: ...


@dataclass(frozen=True)
class FillStep:
    kind: Literal["select", "cell", "scroll"]
    color_index: int
    row: int | None = None
    column: int | None = None


def build_fill_steps(pattern: Pattern) -> list[FillStep]:
    steps: list[FillStep] = []
    needs_lower_palette = any(cell >= 24 for row in pattern.cells for cell in row)
    for color_index in range(24):
        cells = [(row, column) for row, values in enumerate(pattern.cells) for column, value in enumerate(values) if value == color_index and value != WHITE_INDEX]
        if cells:
            steps.append(FillStep("select", color_index))
            steps.extend(FillStep("cell", color_index, row, column) for row, column in cells)
    if needs_lower_palette:
        steps.append(FillStep("scroll", 24))
        for color_index in range(24, 40):
            cells = [(row, column) for row, values in enumerate(pattern.cells) for column, value in enumerate(values) if value == color_index]
            if cells:
                steps.append(FillStep("select", color_index))
                steps.extend(FillStep("cell", color_index, row, column) for row, column in cells)
    return steps


def build_residual_pattern(pattern: Pattern, rendered: list[list[int]]) -> Pattern:
    """根据截图识别到的当前画布 rendered（每格最近色号索引）与目标图案比对，
    返回仅包含“应上色但当前不符”格子的残留图案（其余为白），供填后复检重填。"""
    residual = Pattern.blank()
    for row, values in enumerate(pattern.cells):
        for column, expected in enumerate(values):
            if expected == WHITE_INDEX:
                continue
            if rendered[row][column] != expected:
                residual.set_cell(row, column, expected)
    return residual


class AutoFillRunner:
    def __init__(self, mouse: MouseDriver) -> None:
        self.mouse = mouse

    def run(
        self,
        pattern: Pattern,
        calibration: Calibration | None,
        cancel_event: Event,
        on_progress: Callable[[tuple[int, int]], None] | None = None,
        client_area: ClientArea | None = None,
        target_is_active: Callable[[], bool] | None = None,
        should_abort: Callable[[], bool] | None = None,
        select_color: Callable[[int], bool] | None = None,
    ) -> bool:
        if calibration is None:
            raise ValueError("尚未完成校准。请先打开游戏拼豆编辑器并完成手动校准。")
        if calibration.target_window is None or calibration.target_process_id is None:
            raise ValueError("校准尚未绑定游戏窗口。请重新校准并捕获当前游戏窗口。")
        if any(cell >= 24 for row in pattern.cells for cell in row) and calibration.lower_palette is None:
            raise ValueError("图案使用了后 16 色，但底部色板尚未校准。请先滚动色板到底部并完成校准。")
        scaled = calibration.for_client(client_area or calibration.reference_client)

        def aborted() -> bool:
            if should_abort is not None:
                return should_abort()
            return cancel_event.is_set() or (target_is_active is not None and not target_is_active())

        total = pattern.non_white_count
        completed = 0
        lower_palette_visible = False
        selected_ok = True
        for step in build_fill_steps(pattern):
            if aborted():
                return False
            if step.kind == "scroll":
                # 实时“认色块”选色时，滚动由 select_color 内部处理，跳过固定偏移滚动步。
                if select_color is not None:
                    continue
                x, y = scaled.scroll_point()
                # 拆成多次单刻度滚动，每次重锚，避免 Unity 把一次大滚动只算一格。
                for _ in range(scaled.source.scroll_clicks):
                    if aborted():
                        return False
                    self.mouse.scroll(-1, x, y)
                lower_palette_visible = True
            elif step.kind == "select":
                if select_color is not None:
                    selected_ok = select_color(step.color_index)
                else:
                    x, y = scaled.palette_center(step.color_index, "bottom" if lower_palette_visible else "top")
                    self.mouse.click(x, y)
            else:
                # 实时选色失败时跳过该色格子，不在未选中颜料的情况下盲点。
                if select_color is not None and not selected_ok:
                    continue
                assert step.row is not None and step.column is not None
                x, y = scaled.grid_cell_center(step.row, step.column)
                self.mouse.click(x, y)
                completed += 1
                if on_progress:
                    on_progress((completed, total))
        return not cancel_event.is_set()


class PyAutoGuiMouse:
    """延迟导入 pyautogui，确保图纸功能不依赖自动化库。"""

    def __init__(self) -> None:
        try:
            import pyautogui
        except ImportError as exc:
            raise RuntimeError("未安装 pyautogui；请安装依赖后再使用自动填色。") from exc
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.03
        self._driver = pyautogui

    def click(self, x: int, y: int) -> None:
        self._driver.click(x, y)

    def scroll(self, clicks: int, x: int, y: int) -> None:
        self._driver.moveTo(x, y)
        self._driver.scroll(clicks)
