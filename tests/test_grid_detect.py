"""网格线识别的 RED 测试：用合成网格图验证反推画布框与格心。"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ark_pixel_helper.calibration import ClientArea, viewport_seed
from ark_pixel_helper.calibration import detect_grid_rect
from ark_pixel_helper.grid_detect import GridResult, detect_grid

CELLS = 24
LINES = CELLS + 1


def _synthetic_grid(offset_x: int, offset_y: int, step: int, margin: int = 30) -> Image.Image:
    """在白底上按已知偏移/格边画 25×25 网格线，四周留 flat 白边。"""
    width = offset_x + step * CELLS + margin
    height = offset_y + step * CELLS + margin
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # 先给每格填中灰，模拟真实画布内容，确保识别靠的是线而非空白。
    for row in range(CELLS):
        for col in range(CELLS):
            shade = 200 if (row + col) % 2 == 0 else 170
            x0 = offset_x + col * step
            y0 = offset_y + row * step
            draw.rectangle((x0, y0, x0 + step, y0 + step), fill=(shade, shade, shade))
    # 再画深色网格线（25 竖 + 25 横）。
    for i in range(LINES):
        x = offset_x + i * step
        draw.line((x, offset_y, x, offset_y + step * CELLS), fill=(40, 40, 40), width=1)
        y = offset_y + i * step
        draw.line((offset_x, y, offset_x + step * CELLS, y), fill=(40, 40, 40), width=1)
    return image


def test_detect_grid_recovers_bbox_and_cell_centers():
    ox, oy, step = 50, 40, 14
    image = _synthetic_grid(ox, oy, step)

    result = detect_grid(image)

    assert isinstance(result, GridResult)
    assert len(result.x_lines) == LINES
    assert len(result.y_lines) == LINES
    # 画布外框应贴合首末线（容差 ≤1px）。
    left, top, right, bottom = result.cells_bbox
    assert abs(left - ox) <= 1
    assert abs(top - oy) <= 1
    assert abs(right - (ox + step * CELLS)) <= 1
    assert abs(bottom - (oy + step * CELLS)) <= 1
    # 每格中心用识别线中点反推（容差 ≤1px）。
    cx0, cy0 = result.cell_center(0, 0)
    assert abs(cx0 - (ox + step * 0.5)) <= 1
    assert abs(cy0 - (oy + step * 0.5)) <= 1
    cx, cy = result.cell_center(23, 23)
    assert abs(cx - (ox + step * 23.5)) <= 1
    assert abs(cy - (oy + step * 23.5)) <= 1
    assert result.confidence >= 0.8


def test_detect_grid_honors_roi_within_larger_image():
    ox, oy, step = 60, 55, 12
    image = _synthetic_grid(ox, oy, step, margin=80)
    roi = (ox - 20, oy - 20, ox + step * CELLS + 20, oy + step * CELLS + 20)

    result = detect_grid(image, roi=roi)

    assert result is not None
    left, top, right, bottom = result.cells_bbox
    assert abs(left - ox) <= 1
    assert abs(right - (ox + step * CELLS)) <= 1


def _grid_at(x: int, y: int, side: int, canvas_w: int, canvas_h: int) -> Image.Image:
    """在指定客户区相对位置画一个 24×24 真实网格的模拟截图。"""
    step = side / CELLS
    image = Image.new("RGB", (canvas_w, canvas_h), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    for r in range(CELLS):
        for c in range(CELLS):
            shade = 205 if (r + c) % 2 == 0 else 165
            x0 = x + c * step
            y0 = y + r * step
            draw.rectangle((x0, y0, x0 + step, y0 + step), fill=(shade, shade, shade))
    for i in range(LINES):
        xi = round(x + i * step)
        yi = round(y + i * step)
        draw.line((xi, y, xi, y + side), fill=(35, 35, 35), width=1)
        draw.line((x, yi, x + side, yi), fill=(35, 35, 35), width=1)
    return image


def test_detect_grid_rect_uses_screenshot_when_grid_present():
    client = ClientArea(0, 0, 1280, 720)
    seed = viewport_seed(client)
    image = _grid_at(seed.grid.x, seed.grid.y, seed.grid.width, client.width, client.height)

    rect, used = detect_grid_rect(client, image)

    assert used is True
    assert abs(rect.x - seed.grid.x) <= 2
    assert abs(rect.width - seed.grid.width) <= 2


def test_detect_grid_rect_falls_back_to_seed_without_grid():
    client = ClientArea(0, 0, 1280, 720)
    blank = Image.new("RGB", (client.width, client.height), (255, 255, 255))

    rect, used = detect_grid_rect(client, blank)

    assert used is False
    assert rect == viewport_seed(client).grid


def test_detect_grid_returns_none_without_regular_grid():
    blank = Image.new("RGB", (300, 300), (255, 255, 255))
    assert detect_grid(blank) is None

    ramp = Image.new("L", (300, 300))
    ramp.putdata([x % 256 for _ in range(300) for x in range(300)])
    assert detect_grid(ramp.convert("RGB")) is None
