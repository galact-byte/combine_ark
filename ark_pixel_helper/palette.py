"""活动编辑器可用的唯一 40 色调色板及颜色匹配。"""

from __future__ import annotations

from math import pow
from typing import Literal, TypeAlias

RGB: TypeAlias = tuple[int, int, int]
Matcher = Literal["rgb", "oklab"]

PALETTE: tuple[RGB, ...] = (
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
WHITE_INDEX = 3


def palette_number_to_index(number: int) -> int:
    if not 1 <= number <= len(PALETTE):
        raise ValueError("游戏色号必须在 1 到 40 之间")
    return number - 1


def palette_index_to_number(index: int) -> int:
    if not 0 <= index < len(PALETTE):
        raise ValueError("调色板索引必须在 0 到 39 之间")
    return index + 1


def _linear(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.04045 else pow((channel + 0.055) / 1.055, 2.4)


def rgb_to_oklab(rgb: RGB) -> tuple[float, float, float]:
    red, green, blue = (_linear(channel) for channel in rgb)
    l = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    m = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    s = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    l_root, m_root, s_root = pow(l, 1 / 3), pow(m, 1 / 3), pow(s, 1 / 3)
    return (
        0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
        1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
        0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
    )


def nearest_palette_index(rgb: RGB, matcher: Matcher = "oklab", candidates: tuple[int, ...] | None = None) -> int:
    indices = candidates or tuple(range(len(PALETTE)))
    if not indices:
        raise ValueError("候选调色板不能为空")
    if matcher == "rgb":
        target = tuple(float(value) for value in rgb)
        palette_values = PALETTE

        def distance(index: int) -> float:
            palette = palette_values[index]
            return sum((target[i] - palette[i]) ** 2 for i in range(3))

    elif matcher == "oklab":
        target = rgb_to_oklab(rgb)
        palette_values = tuple(rgb_to_oklab(color) for color in PALETTE)

        def distance(index: int) -> float:
            palette = palette_values[index]
            # 压低明度(L)权重、突出色度(a,b)：低饱和色不再被明度相近的异色相抢走
            # （否则冷青灰会被匹配成明度接近的暖褐/橄榄，整体偏色）。
            dist = 0.5 * (target[0] - palette[0]) ** 2 + (target[1] - palette[1]) ** 2 + (target[2] - palette[2]) ** 2
            # 冷暖跨界惩罚：明度权重被压低后，低饱和色易被明度相近的相反色相抢走
            # （暗青灰落暖藕紫、金棕发落橄榄绿）。目标与候选在红/青绿轴(a)符号相反时加惩罚，
            # 双向锁定色相符号，冷色留冷、暖色留暖（40 色缺中间过渡色的取舍）。
            if (target[1] < -0.005 and palette[1] > 0.005) or (target[1] > 0.005 and palette[1] < -0.005):
                dist += 20.0 * (palette[1] - target[1]) ** 2
            return dist

    else:
        raise ValueError(f"不支持的颜色匹配方式：{matcher}")
    return min(indices, key=distance)
