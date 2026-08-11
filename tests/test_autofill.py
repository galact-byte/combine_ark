from threading import Event

import pytest

from ark_pixel_helper.autofill import AutoFillRunner, FillStep, build_fill_steps, build_residual_pattern
from ark_pixel_helper.calibration import Calibration, ClientArea, Rect
from ark_pixel_helper.pattern import Pattern


class FakeMouse:
    def __init__(self, cancel_after: int | None = None) -> None:
        self.actions: list[tuple[str, int, int | None]] = []
        self.cancel_after = cancel_after
        self.cancel_event: Event | None = None

    def click(self, x: int, y: int) -> None:
        self.actions.append(("click", x, y))
        if self.cancel_event and self.cancel_after == len(self.actions):
            self.cancel_event.set()

    def scroll(self, clicks: int, x: int, y: int) -> None:
        self.actions.append(("scroll", clicks, x))


def get_calibration() -> Calibration:
    return Calibration(
        ClientArea(0, 0, 1000, 500),
        Rect(100, 50, 480, 360),
        Rect(700, 80, 160, 240),
        (780, 280),
        lower_palette=Rect(700, 94, 160, 240),
        scroll_clicks=4,
        target_window=100,
        target_process_id=200,
    )


def test_build_fill_steps_groups_by_color_skips_white_and_scrolls_for_colors_25_to_40():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    pattern.set_cell(0, 1, 0)
    pattern.set_cell(2, 3, 24)

    steps = build_fill_steps(pattern)

    assert [(step.kind, step.color_index) for step in steps] == [("select", 0), ("cell", 0), ("cell", 0), ("scroll", 24), ("select", 24), ("cell", 24)]
    assert [step.row for step in steps if step.kind == "cell"] == [0, 0, 2]


def test_runner_sends_predictable_clicks_and_stops_after_cancellation():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    pattern.set_cell(0, 1, 0)
    pattern.set_cell(1, 0, 24)
    cancel = Event()
    mouse = FakeMouse(cancel_after=2)
    mouse.cancel_event = cancel
    progress: list[tuple[int, int]] = []

    completed = AutoFillRunner(mouse).run(pattern, get_calibration(), cancel, progress.append)

    assert completed is False
    assert mouse.actions == [("click", 720, 100), ("click", 110, 58)]
    assert progress == [(1, 3)]


def test_runner_stops_before_clicking_when_target_window_is_no_longer_foreground():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    mouse = FakeMouse()

    completed = AutoFillRunner(mouse).run(pattern, get_calibration(), Event(), target_is_active=lambda: False)

    assert completed is False
    assert mouse.actions == []


def test_runner_uses_current_client_area_instead_of_assuming_reference_resolution():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    mouse = FakeMouse()

    AutoFillRunner(mouse).run(pattern, get_calibration(), Event(), client_area=ClientArea(10, 20, 2000, 1000))

    assert mouse.actions == [("click", 1450, 220), ("click", 230, 135)]


def test_build_residual_pattern_keeps_only_mismatched_non_white_cells():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 5)   # 应为色号6，截图也是5 → 已正确，不重填
    pattern.set_cell(0, 1, 5)   # 应为5，截图是白(3) → 漏格，重填
    pattern.set_cell(1, 0, 28)  # 应为28，截图是错色26 → 错色，重填
    pattern.set_cell(2, 2, 3)   # 白格，永不重填
    rendered = [[3] * 24 for _ in range(24)]
    rendered[0][0] = 5
    rendered[0][1] = 3
    rendered[1][0] = 26

    residual = build_residual_pattern(pattern, rendered)

    assert residual.get_cell(0, 0) == 3  # 已正确 → 残留中为白
    assert residual.get_cell(0, 1) == 5  # 漏格 → 保留
    assert residual.get_cell(1, 0) == 28  # 错色 → 保留
    assert residual.non_white_count == 2


def test_runner_requires_valid_calibration():
    with pytest.raises(ValueError):
        AutoFillRunner(FakeMouse()).run(Pattern.blank(), None, Event())


def test_runner_splits_scroll_into_single_ticks_with_reanchor():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    pattern.set_cell(1, 0, 24)
    mouse = FakeMouse()

    AutoFillRunner(mouse).run(pattern, get_calibration(), Event())

    # 一次大滚动拆成 scroll_clicks 次单刻度，每次重锚到滚轮锤点。
    scrolls = [action for action in mouse.actions if action[0] == "scroll"]
    assert scrolls == [("scroll", -1, 780)] * 4


def test_runner_honors_should_abort_predicate():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    pattern.set_cell(0, 1, 0)
    calls = {"n": 0}

    def should_abort() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    mouse = FakeMouse()
    completed = AutoFillRunner(mouse).run(pattern, get_calibration(), Event(), should_abort=should_abort)

    assert completed is False
    assert len(mouse.actions) <= 2


def test_runner_uses_live_select_color_and_skips_geometric_scroll():
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    pattern.set_cell(0, 1, 0)
    pattern.set_cell(1, 0, 24)
    selected: list[int] = []

    def select_color(color_index: int) -> bool:
        selected.append(color_index)
        return color_index != 24  # 模拟后 16 色定位失败 → 该色格子跳过

    mouse = FakeMouse()
    AutoFillRunner(mouse).run(pattern, get_calibration(), Event(), select_color=select_color)

    # 两种颜色都经 select_color 选，不走几何滚动步。
    assert selected == [0, 24]
    assert not any(action[0] == "scroll" for action in mouse.actions)
    # 选色成功的 color 0 两格被点；color 24 选色失败其格被跳过。
    assert mouse.actions == [("click", 110, 58), ("click", 130, 58)]
