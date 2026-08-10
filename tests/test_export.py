import csv

from PIL import Image

from ark_pixel_helper.export import export_pattern_csv, export_pattern_png
from ark_pixel_helper.palette import PALETTE
from ark_pixel_helper.pattern import Pattern


def test_export_png_scales_cells_and_uses_palette_colors(tmp_path):
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    output = tmp_path / "nested" / "pattern.png"

    export_pattern_png(pattern, output, cell_size=10, show_numbers=False)

    image = Image.open(output)
    assert image.size == (240, 240)
    assert image.getpixel((5, 5)) == PALETTE[0]
    assert image.getpixel((15, 15)) == PALETTE[3]
    assert image.getpixel((10, 5)) != PALETTE[0]  # 网格线


def test_export_csv_writes_24_rows_of_user_facing_color_numbers(tmp_path):
    pattern = Pattern.blank()
    pattern.set_cell(0, 0, 0)
    output = tmp_path / "pattern.csv"

    export_pattern_csv(pattern, output)

    with output.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.reader(file))
    assert len(rows) == 24
    assert all(len(row) == 24 for row in rows)
    assert rows[0][0] == "1"
    assert rows[0][1] == "4"
