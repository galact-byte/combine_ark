from ark_pixel_helper.palette import PALETTE, nearest_palette_index, palette_index_to_number, palette_number_to_index


def test_palette_has_exact_game_colors_and_number_mapping():
    expected_game_palette = (
        (34, 34, 34), (180, 180, 180), (234, 231, 223), (255, 255, 255),
        (211, 47, 54), (156, 10, 0), (214, 12, 74), (230, 150, 141),
        (254, 152, 117), (247, 208, 192), (252, 239, 234), (251, 246, 232),
        (220, 210, 200), (226, 206, 171), (213, 99, 34), (212, 140, 66),
        (242, 153, 0), (249, 201, 51), (252, 228, 153), (179, 180, 122),
        (194, 218, 114), (108, 110, 0), (170, 139, 82), (169, 143, 116),
        (170, 146, 40), (63, 43, 18), (116, 73, 31), (83, 70, 88),
        (42, 36, 70), (57, 69, 153), (90, 69, 157), (186, 163, 215),
        (182, 188, 223), (169, 172, 190), (99, 171, 185), (180, 210, 220),
        (145, 216, 230), (71, 174, 160), (182, 211, 200), (39, 56, 100),
    )
    assert PALETTE == expected_game_palette
    assert palette_number_to_index(1) == 0
    assert palette_number_to_index(40) == 39
    assert palette_index_to_number(0) == 1
    assert palette_index_to_number(39) == 40


def test_palette_rejects_invalid_user_numbers():
    for number in (0, 41):
        try:
            palette_number_to_index(number)
        except ValueError:
            pass
        else:
            raise AssertionError("无效色号必须被拒绝")


def test_nearest_match_supports_rgb_and_oklab():
    for matcher in ("rgb", "oklab"):
        assert nearest_palette_index((255, 255, 255), matcher) == 3
        result = nearest_palette_index((200, 100, 30), matcher)
        assert 0 <= result < len(PALETTE)
