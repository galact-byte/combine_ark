import pytest
from PIL import Image

from ark_pixel_helper.image_pipeline import CropBox, ImageOptions, compose_image, convert_image, enhance_for_pixel_art, prepare_square
from ark_pixel_helper.palette import WHITE_INDEX


def test_contain_mode_keeps_transparent_pixels_on_white_background():
    image = Image.new("RGBA", (4, 2), (255, 0, 0, 0))
    image.putpixel((0, 0), (211, 47, 54, 255))

    squared = prepare_square(image, ImageOptions(fit_mode="contain"))

    assert squared.mode == "RGB"
    assert squared.size == (4, 4)
    assert squared.getpixel((3, 3)) == (255, 255, 255)


def test_crop_contain_and_stretch_prepare_a_square():
    image = Image.new("RGB", (8, 4), (211, 47, 54))
    expected_sizes = {"crop": (4, 4), "contain": (8, 8), "stretch": (4, 4)}
    for mode, expected_size in expected_sizes.items():
        assert prepare_square(image, ImageOptions(fit_mode=mode)).size == expected_size


def test_crop_mode_uses_user_selected_horizontal_framing_offset():
    image = Image.new("RGB", (8, 4), (255, 255, 255))
    for x in range(4):
        for y in range(4):
            image.putpixel((x, y), (34, 34, 34))

    left = prepare_square(image, ImageOptions(fit_mode="crop", crop_offset_x=-1))
    right = prepare_square(image, ImageOptions(fit_mode="crop", crop_offset_x=1))

    assert left.getpixel((0, 0)) == (34, 34, 34)
    assert right.getpixel((0, 0)) == (255, 255, 255)


def test_pipeline_returns_a_valid_24_by_24_pattern_and_supports_nearest_sampling():
    image = Image.new("RGB", (2, 2), (255, 255, 255))
    image.putpixel((0, 0), (34, 34, 34))

    pattern = convert_image(image, ImageOptions(resample="nearest", matcher="rgb"))

    assert len(pattern.cells) == 24
    assert all(len(row) == 24 for row in pattern.cells)
    assert pattern.get_cell(0, 0) == 0
    assert all(0 <= color < 40 for row in pattern.cells for color in row)


def test_reduce_colors_uses_at_most_sixteen_palette_indices_and_disables_dithering():
    image = Image.new("RGB", (24, 24))
    for y in range(24):
        for x in range(24):
            image.putpixel((x, y), ((x * 11) % 256, (y * 13) % 256, ((x + y) * 7) % 256))

    options = ImageOptions(reduce_colors=True, dither=True)
    pattern = convert_image(image, options)

    assert options.dither is False
    assert len({color for row in pattern.cells for color in row}) <= 16


def test_optional_dithering_distributes_a_flat_intermediate_color_between_palette_colors():
    image = Image.new("RGB", (24, 24), (120, 120, 120))

    pattern = convert_image(image, ImageOptions(reduce_colors=False, dither=True, matcher="rgb"))

    assert len({color for row in pattern.cells for color in row}) > 1


def test_dithering_uses_the_same_enhanced_pixels_as_the_non_dither_path(monkeypatch):
    image = Image.new("RGB", (24, 24), (100, 100, 100))
    image.putpixel((1, 0), (156, 156, 156))
    received: list[tuple[int, int, int]] = []

    def capture_dither(colors, _matcher, _candidates):
        received.extend(colors)
        return [0] * (24 * 24)

    monkeypatch.setattr("ark_pixel_helper.image_pipeline._dither", capture_dither)
    convert_image(image, ImageOptions(reduce_colors=False, dither=True))

    assert received[0] != (100, 100, 100) or received[1] != (156, 156, 156)


def test_compose_image_returns_white_backed_rgb():
    assert compose_image(Image.new("RGBA", (1, 1), (0, 0, 0, 0))).getpixel((0, 0)) == (255, 255, 255)


def test_crop_box_requires_a_positive_square_entirely_inside_the_source_image():
    CropBox(100, 50, 400).validate_for((600, 500))

    for crop_box in (CropBox(-1, 0, 1), CropBox(0, -1, 1), CropBox(0, 0, 0), CropBox(300, 100, 301), CropBox(0.5, 0, 1), CropBox(0, 0, 1.5)):
        with pytest.raises(ValueError):
            crop_box.validate_for((600, 500))


def test_crop_box_is_the_exact_source_for_prepare_square_and_conversion():
    image = Image.new("RGB", (600, 500), (255, 255, 255))
    image.putpixel((100, 50), (211, 47, 54))
    image.putpixel((499, 449), (34, 34, 34))
    options = ImageOptions(crop_box=CropBox(100, 50, 400), resample="nearest", matcher="rgb")

    prepared = prepare_square(image, options)
    pattern = convert_image(image, options)

    assert prepared.size == (400, 400)
    assert prepared.getpixel((0, 0)) == (211, 47, 54)
    assert prepared.getpixel((399, 399)) == (34, 34, 34)
    assert len(pattern.cells) == 24
    assert all(len(row) == 24 for row in pattern.cells)
    assert all(0 <= color < 40 for row in pattern.cells for color in row)


def test_image_options_preserve_more_color_detail_by_default():
    assert ImageOptions().reduce_colors is False


def test_enhancement_increases_local_luminance_separation_before_quantization():
    image = Image.new("RGB", (3, 1))
    image.putdata([(100, 100, 100), (128, 128, 128), (156, 156, 156)])

    enhanced = enhance_for_pixel_art(image)

    assert enhanced.getpixel((2, 0))[0] - enhanced.getpixel((0, 0))[0] > 56
