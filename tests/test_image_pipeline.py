from PIL import Image

from ark_pixel_helper.image_pipeline import ImageOptions, compose_image, convert_image, prepare_square
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


def test_compose_image_returns_white_backed_rgb():
    assert compose_image(Image.new("RGBA", (1, 1), (0, 0, 0, 0))).getpixel((0, 0)) == (255, 255, 255)
