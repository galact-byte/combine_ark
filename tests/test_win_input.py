"""win_input 纯函数的 RED 测试：坐标归一化、相对位移、提权决策。

不触发真实 SendInput / 提权；只验证可移植的纯逻辑。
"""

from __future__ import annotations

from ark_pixel_helper.win_input import relative_delta, should_elevate, to_absolute


def test_to_absolute_maps_corners_to_full_range():
    rect = (0, 0, 1920, 1080)
    assert to_absolute(0, 0, rect) == (0, 0)
    ax, ay = to_absolute(1919, 1079, rect)
    assert ax == 65535 and ay == 65535
    # 中点约在半程附近。
    mx, my = to_absolute(960, 540, rect)
    assert 32000 <= mx <= 33500 and 32000 <= my <= 33500


def test_to_absolute_handles_virtual_desktop_offset_and_clamps():
    rect = (-1920, -100, 3840, 1180)  # 双屏虚拟桌面，左上为负
    assert to_absolute(-1920, -100, rect) == (0, 0)
    ax, ay = to_absolute(1919, 1079, rect)
    assert ax == 65535 and ay == 65535
    # 越界坐标裁剪到 [0, 65535]
    assert to_absolute(-9999, -9999, rect) == (0, 0)
    cx, cy = to_absolute(999999, 999999, rect)
    assert cx == 65535 and cy == 65535


def test_relative_delta_first_frame_and_increment():
    assert relative_delta(None, (100, 200)) == (0, 0)
    assert relative_delta((100, 200), (130, 180)) == (30, -20)


def test_should_elevate_guards_against_uac_retry_loop():
    assert should_elevate(is_admin=True, already_tried=False) is False
    assert should_elevate(is_admin=True, already_tried=True) is False
    assert should_elevate(is_admin=False, already_tried=False) is True
    # 已尝试提权仍非管理员（用户拒绝 UAC）→ 不再重启，避免死循环。
    assert should_elevate(is_admin=False, already_tried=True) is False
