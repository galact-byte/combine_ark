from ark_pixel_helper.ui import progress_percent


def test_progress_percent_clamps_invalid_and_completed_values():
    assert progress_percent(0, 0) == 0
    assert progress_percent(3, 10) == 30
    assert progress_percent(15, 10) == 100
