"""色板色块识别的 RED 测试：用合成色板图验证反推顶部色板矩形。

利用 40 色精确 RGB 在截图里"认色板"，对 UI 缩放/分辨率免疫。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ark_pixel_helper.calibration import ClientArea, Rect, calibration_from_capture, viewport_seed
from ark_pixel_helper.palette import PALETTE
from ark_pixel_helper.palette_locate import detect_palette_rect, swatch_centers

CANVAS = Rect(369, 148, 700, 700)


def _synthetic_editor(palette_rect: Rect) -> Image.Image:
    """左侧白画布 + 右侧灰面板上的 4×6 顶部色板（色号 1–24）。"""
    image = Image.new("RGB", (1550, 860), (232, 232, 232))
    draw = ImageDraw.Draw(image)
    # 画布区域（应被 ROI 排除）：白底 + 几个彩色格，验证不会污染色板识别。
    draw.rectangle((CANVAS.x, CANVAS.y, CANVAS.x + CANVAS.width, CANVAS.y + CANVAS.height), fill=(255, 255, 255))
    draw.rectangle((CANVAS.x + 40, CANVAS.y + 40, CANVAS.x + 90, CANVAS.y + 90), fill=PALETTE[30])
    # 右侧色板面板灰底。
    draw.rectangle((palette_rect.x - 40, palette_rect.y - 60, palette_rect.x + palette_rect.width + 40, palette_rect.y + palette_rect.height + 40), fill=(58, 58, 60))
    cell_w = palette_rect.width / 4
    cell_h = palette_rect.height / 6
    for index in range(24):  # 顶部页显示索引 0–23
        col, row = index % 4, index // 4
        cx = palette_rect.x + palette_rect.width * (col + 0.5) / 4
        cy = palette_rect.y + palette_rect.height * (row + 0.5) / 6
        half_w, half_h = cell_w * 0.4, cell_h * 0.4
        draw.rectangle((cx - half_w, cy - half_h, cx + half_w, cy + half_h), fill=PALETTE[index])
    return image


def test_detect_palette_rect_recovers_top_page_geometry():
    palette_rect = Rect(1150, 330, 320, 456)
    image = _synthetic_editor(palette_rect)

    result = detect_palette_rect(image, CANVAS)

    assert result is not None
    assert abs(result.x - palette_rect.x) <= 4
    assert abs(result.y - palette_rect.y) <= 6
    assert abs(result.width - palette_rect.width) <= 8
    assert abs(result.height - palette_rect.height) <= 10


def test_swatch_centers_locates_dark_color_despite_dark_panel_background():
    # 底页色板（索引 16–39），面板底色接近深藏蓝：验证背景不污染深色块。
    rect = Rect(1200, 330, 320, 456)
    image = Image.new("RGB", (1600, 900), (230, 230, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle((rect.x - 40, rect.y - 60, rect.x + rect.width + 40, rect.y + rect.height + 40), fill=(58, 58, 60))
    for page_pos in range(24):  # 页内位置 0–23 → 索引 16–39
        index = 16 + page_pos
        col, row = page_pos % 4, page_pos // 4
        cx = rect.x + rect.width * (col + 0.5) / 4
        cy = rect.y + rect.height * (row + 0.5) / 6
        draw.rectangle((cx - 30, cy - 28, cx + 30, cy + 28), fill=PALETTE[index])
    roi = (rect.x - 20, rect.y - 20, rect.x + rect.width + 20, rect.y + rect.height + 20)

    centers = swatch_centers(image, roi)

    # 索引 28 深藏蓝在页内位置 12 → row3,col0，不能被底色拖到面板中心。
    assert 28 in centers
    exp_x = rect.x + rect.width * 0.5 / 4
    exp_y = rect.y + rect.height * 3.5 / 6
    assert abs(centers[28][0] - exp_x) <= 3 and abs(centers[28][1] - exp_y) <= 3
    assert len(centers) == 24


def test_detect_palette_rect_recovers_geometry_when_captured_on_second_page():
    # 底页显示色号 17–40（索引 16–39）；面板屏幕位置固定，应得到与顶页一致的矩形。
    palette_rect = Rect(1150, 330, 320, 456)
    image = Image.new("RGB", (1550, 860), (232, 232, 232))
    draw = ImageDraw.Draw(image)
    draw.rectangle((CANVAS.x, CANVAS.y, CANVAS.x + CANVAS.width, CANVAS.y + CANVAS.height), fill=(255, 255, 255))
    draw.rectangle((palette_rect.x - 40, palette_rect.y - 60, palette_rect.x + palette_rect.width + 40, palette_rect.y + palette_rect.height + 40), fill=(58, 58, 60))
    for page_pos in range(24):  # 页内位置 0–23 → 索引 16–39
        index = 16 + page_pos
        col, row = page_pos % 4, page_pos // 4
        cx = palette_rect.x + palette_rect.width * (col + 0.5) / 4
        cy = palette_rect.y + palette_rect.height * (row + 0.5) / 6
        draw.rectangle((cx - 22, cy - 20, cx + 22, cy + 20), fill=PALETTE[index])

    result = detect_palette_rect(image, CANVAS)

    assert result is not None
    assert abs(result.x - palette_rect.x) <= 6
    assert abs(result.y - palette_rect.y) <= 8
    assert abs(result.width - palette_rect.width) <= 10
    assert abs(result.height - palette_rect.height) <= 12


def test_detect_palette_rect_returns_none_without_swatches():
    blank = Image.new("RGB", (1550, 860), (232, 232, 232))
    assert detect_palette_rect(blank, CANVAS) is None


def test_calibration_from_capture_detects_grid_and_palette_together():
    client = ClientArea(0, 0, 1600, 900)
    grid = viewport_seed(client).grid
    image = Image.new("RGB", (1600, 900), (230, 230, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle((grid.x, grid.y, grid.x + grid.width, grid.y + grid.height), fill=(250, 250, 250))
    step_x, step_y = grid.width / 24, grid.height / 24
    for i in range(25):
        gx, gy = round(grid.x + i * step_x), round(grid.y + i * step_y)
        draw.line((gx, grid.y, gx, grid.y + grid.height), fill=(40, 40, 40))
        draw.line((grid.x, gy, grid.x + grid.width, gy), fill=(40, 40, 40))
    palette = Rect(1200, 330, 320, 456)
    draw.rectangle((palette.x - 40, palette.y - 60, palette.x + palette.width + 40, palette.y + palette.height + 40), fill=(58, 58, 60))
    for index in range(24):
        col, row = index % 4, index // 4
        cx = palette.x + palette.width * (col + 0.5) / 4
        cy = palette.y + palette.height * (row + 0.5) / 6
        draw.rectangle((cx - 30, cy - 28, cx + 30, cy + 28), fill=PALETTE[index])

    cal, grid_used, palette_used = calibration_from_capture(client, image, 111, 222)

    assert grid_used is True and palette_used is True
    assert abs(cal.palette.x - palette.x) <= 4 and abs(cal.palette.width - palette.width) <= 8
    assert cal.lower_palette == cal.palette and cal.scroll_clicks >= 6
    # 顶部/底部选色中心落在正确列行（底部偏移 16）。
    scaled = cal.for_client(client)
    top_x, _ = scaled.palette_center(4, "top")
    bottom_x, _ = scaled.palette_center(24, "bottom")
    assert abs(top_x - bottom_x) <= 1  # 同一列（col0）同屏位置
