import json

import pytest

from ark_pixel_helper.calibration import Calibration, CalibrationError, ClientArea, Rect, suggested_layout, viewport_seed


def calibration() -> Calibration:
    return Calibration(
        reference_client=ClientArea(100, 200, 1000, 500),
        grid=Rect(100, 50, 480, 360),
        palette=Rect(700, 80, 160, 240),
        scroll_anchor=(780, 280),
    )


def test_suggested_layout_is_valid_and_adapts_to_any_client_size():
    for area in (ClientArea(0, 0, 1600, 900), ClientArea(10, 20, 1280, 720), ClientArea(0, 0, 1920, 1080)):
        suggested = suggested_layout(area)
        # 构造不抛异常就证明几何全部落在客户区内、尺寸合法。
        assert isinstance(suggested, Calibration)
        assert suggested.lower_palette is not None
        assert suggested.scroll_clicks > 0
        # 底部色板与顶部列对齐，位置略下移。
        assert suggested.lower_palette.x == suggested.palette.x
        assert suggested.lower_palette.y >= suggested.palette.y
        # 比例自适应：不同客户区宽度得到不同网格宽度。
    assert suggested_layout(ClientArea(0, 0, 1600, 900)).grid.width != suggested_layout(ClientArea(0, 0, 1280, 720)).grid.width


def test_viewport_seed_centers_16_9_viewport_for_letterboxed_clients():
    # 过宽客户区：视口按高居中，左右黑边 → 画布 x 比裸比例推算更靠右。
    wide = viewport_seed(ClientArea(0, 0, 1000, 500))
    assert isinstance(wide, Calibration)
    assert wide.grid.x > round(295 / 1280 * 1000)
    # 过高客户区：视口按宽居中，上下黑边 → 画布 y 更靠下。
    tall = viewport_seed(ClientArea(0, 0, 1280, 1000))
    assert tall.grid.y > round(119 / 720 * 1000)
    # 恰好 16:9：无黑边，构造合法。
    assert isinstance(viewport_seed(ClientArea(0, 0, 1280, 720)), Calibration)


def test_calibration_scales_grid_and_palette_coordinates_for_current_client_size():
    saved = calibration()
    reference = saved.for_client(ClientArea(100, 200, 1000, 500))
    scaled = saved.for_client(ClientArea(10, 20, 2000, 1000))

    assert reference.grid_cell_center(0, 0) == (210, 258)
    assert scaled.grid_cell_center(0, 0) == (230, 135)
    assert reference.palette_center(23, "top") == (940, 500)
    assert scaled.palette_center(23, "top") == (1690, 620)


def test_calibration_rejects_geometry_outside_the_reference_client_area():
    client = ClientArea(0, 0, 100, 100)

    with pytest.raises(CalibrationError):
        Calibration(client, Rect(-1, 1, 24, 24), Rect(1, 1, 40, 60), (10, 10))
    with pytest.raises(CalibrationError):
        Calibration(client, Rect(1, 1, 24, 24), Rect(70, 1, 40, 60), (10, 10))
    with pytest.raises(CalibrationError):
        Calibration(client, Rect(1, 1, 24, 24), Rect(1, 1, 40, 60), (101, 10))


def test_calibration_persists_target_window_identity(tmp_path):
    source = Calibration(
        ClientArea(0, 0, 1000, 500), Rect(100, 50, 480, 360), Rect(700, 80, 160, 240), (780, 280), target_window=1234, target_process_id=5678
    )
    path = tmp_path / "calibration.json"
    source.save(path)

    loaded = Calibration.load(path)
    assert (loaded.target_window, loaded.target_process_id) == (1234, 5678)
    with pytest.raises(CalibrationError):
        Calibration(source.reference_client, source.grid, source.palette, source.scroll_anchor, target_window=0, target_process_id=5678)
    with pytest.raises(CalibrationError):
        Calibration(source.reference_client, source.grid, source.palette, source.scroll_anchor, target_window=1234)


def test_lower_palette_and_scroll_distance_are_explicitly_calibrated():
    saved = Calibration(
        ClientArea(0, 0, 1000, 500),
        Rect(100, 50, 480, 360),
        Rect(700, 80, 160, 240),
        (780, 280),
        lower_palette=Rect(700, 94, 160, 240),
        scroll_clicks=4,
    )

    scaled = saved.for_client(ClientArea(10, 20, 2000, 1000))
    assert scaled.palette_center(24, "bottom") == (1450, 408)
    assert saved.scroll_clicks == 4


def test_calibration_persists_and_rejects_missing_or_non_positive_dimensions(tmp_path):
    source = calibration()
    path = tmp_path / "settings" / "calibration.json"
    source.save(path)
    assert Calibration.load(path) == source

    path.write_text(json.dumps({"reference_client": {"left": 1}}), encoding="utf-8")
    with pytest.raises(CalibrationError):
        Calibration.load(path)

    with pytest.raises(CalibrationError):
        Calibration(ClientArea(0, 0, 0, 1), Rect(1, 1, 1, 1), Rect(1, 1, 1, 1), (1, 1))
