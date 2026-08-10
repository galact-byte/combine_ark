from ark_pixel_helper.calibration import Calibration, ClientArea, Rect
from ark_pixel_helper import ui
from ark_pixel_helper.ui import window_matches_calibration


def calibration() -> Calibration:
    return Calibration(
        ClientArea(0, 0, 1000, 500),
        Rect(100, 50, 480, 360),
        Rect(700, 80, 160, 240),
        (780, 280),
        target_window=1234,
        target_process_id=5678,
    )


def test_window_match_requires_both_the_calibrated_handle_and_process_id():
    saved = calibration()

    assert window_matches_calibration(saved, 1234, 5678)
    assert not window_matches_calibration(saved, 1234, 9999)
    assert not window_matches_calibration(saved, 9999, 5678)


def test_calibrated_foreground_check_re_reads_the_current_process_id(monkeypatch):
    saved = calibration()
    monkeypatch.setattr(ui, "foreground_window_handle", lambda: 1234)
    monkeypatch.setattr(ui, "window_process_id", lambda _handle: 9999)

    assert not ui.is_calibrated_window_foreground(saved)
