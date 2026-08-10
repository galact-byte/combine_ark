import pytest

import ark_pixel_helper.ui as ui
from ark_pixel_helper.image_pipeline import CropBox, ImageOptions

from PIL import Image

from ark_pixel_helper.ui import CanvasImageMap, CropDialog, CropSelection


def test_canvas_image_map_round_trips_crop_box_in_original_image_coordinates():
    image_map = CanvasImageMap((1000, 500), (500, 250))
    crop_box = CropBox(250, 0, 500)

    assert image_map.crop_to_canvas(crop_box) == (125.0, 0.0, 250.0)
    assert image_map.canvas_to_source(125, 0) == (250, 0)
    assert image_map.canvas_to_source(375, 250) == (750, 500)


def test_crop_selection_clamps_drag_resize_and_zoom_to_image_bounds():
    selection = CropSelection((1000, 500), CropBox(250, 0, 500))

    assert selection.move_by(1000, 1000) == CropBox(500, 0, 500)
    assert selection.resize_from_corner("nw", (0, 0)) == CropBox(500, 0, 500)
    assert selection.zoom_at((750, 250), 1.5) == CropBox(583, 83, 333)


def test_crop_selection_defaults_to_the_largest_centered_square_and_rejects_unknown_corners():
    selection = CropSelection((1000, 500))

    assert selection.crop_box == CropBox(250, 0, 500)
    with pytest.raises(ValueError):
        selection.resize_from_corner("center", (100, 100))


def test_crop_dialog_rebuilds_the_24_by_24_preview_when_the_crop_changes(root):
    dialog = CropDialog(root, Image.new("RGB", (1000, 500), (211, 47, 54)), lambda _crop: None)
    original_preview = dialog.preview_pattern

    dialog._selection.move_by(100, 0)
    dialog._redraw()

    assert len(dialog.preview_pattern.cells) == 24
    assert dialog.preview_pattern is not original_preview
    dialog.destroy()


def test_crop_dialog_draws_all_24_by_24_game_palette_cells(root):
    dialog = CropDialog(root, Image.new("RGB", (1000, 500), (211, 47, 54)), lambda _crop: None)

    assert len(dialog.preview_canvas.find_withtag("preview-cell")) == 24 * 24
    dialog.destroy()


def test_crop_dialog_uses_the_current_detail_options_for_its_final_preview(root, monkeypatch):
    received_options: list[ImageOptions] = []
    original_convert = ui.convert_image

    def capture_options(image, options):
        received_options.append(options)
        return original_convert(image, options)

    monkeypatch.setattr(ui, "convert_image", capture_options)
    expected = ImageOptions(resample="nearest", reduce_colors=True)
    dialog = CropDialog(root, Image.new("RGB", (1000, 500), (211, 47, 54)), lambda _crop: None, options=expected)

    assert received_options[-1].resample == "nearest"
    assert received_options[-1].reduce_colors is True
    assert received_options[-1].crop_box == dialog._selection.crop_box
    dialog.destroy()


def test_crop_dialog_confirms_only_a_valid_crop_box(root):
    selected: list[CropBox] = []
    dialog = CropDialog(root, Image.new("RGB", (1000, 500)), selected.append, CropBox(250, 0, 500))

    dialog._confirm()

    assert selected == [CropBox(250, 0, 500)]
