from threading import Event

import pytest

from ark_pixel_helper.autofill import AutoFillRunner, FillStep, build_fill_steps
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


def test_runner_requires_valid_calibration():
    with pytest.raises(ValueError):
        AutoFillRunner(FakeMouse()).run(Pattern.blank(), None, Event())
