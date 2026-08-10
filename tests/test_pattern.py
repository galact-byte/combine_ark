import pytest

from ark_pixel_helper.pattern import GRID_SIZE, Pattern


def test_pattern_rejects_invalid_grid_dimensions_and_color_indices():
    with pytest.raises(ValueError):
        Pattern([[3] * GRID_SIZE for _ in range(GRID_SIZE - 1)])
    with pytest.raises(ValueError):
        Pattern([[3] * (GRID_SIZE - 1) for _ in range(GRID_SIZE)])
    with pytest.raises(ValueError):
        Pattern([[40] * GRID_SIZE for _ in range(GRID_SIZE)])


def test_pattern_can_edit_cells_and_count_non_white_cells():
    pattern = Pattern.blank()
    assert pattern.non_white_count == 0

    pattern.set_cell(2, 4, 0)
    assert pattern.get_cell(2, 4) == 0
    assert pattern.non_white_count == 1

    pattern.set_cell(2, 4, 3)
    assert pattern.non_white_count == 0


def test_pattern_rejects_out_of_range_coordinates_and_color_index():
    pattern = Pattern.blank()
    with pytest.raises(ValueError):
        pattern.set_cell(24, 0, 0)
    with pytest.raises(ValueError):
        pattern.set_cell(0, 24, 0)
    with pytest.raises(ValueError):
        pattern.set_cell(0, 0, -1)
