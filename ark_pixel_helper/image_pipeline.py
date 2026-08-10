"""本地图片构图、缩放与游戏调色板量化。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageEnhance

from .palette import Matcher, nearest_palette_index
from .pattern import GRID_SIZE, Pattern

FitMode = Literal["crop", "contain", "stretch"]
ResampleMode = Literal["smooth", "nearest"]


@dataclass(frozen=True)
class CropBox:
    """原图坐标系中的严格正方形裁切区域。"""

    left: int
    top: int
    side: int

    def validate_for(self, image_size: tuple[int, int]) -> None:
        width, height = image_size
        if width <= 0 or height <= 0:
            raise ValueError("图片尺寸无效")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (self.left, self.top, self.side)):
            raise ValueError("裁切区域必须使用整数原图像素坐标")
        if self.left < 0 or self.top < 0 or self.side <= 0:
            raise ValueError("裁切区域必须位于图片内且边长为正数")
        if self.left + self.side > width or self.top + self.side > height:
            raise ValueError("裁切区域超出图片范围")


@dataclass
class ImageOptions:
    fit_mode: FitMode = "crop"
    resample: ResampleMode = "smooth"
    matcher: Matcher = "oklab"
    reduce_colors: bool = False
    dither: bool = False
    crop_box: CropBox | None = None
    crop_offset_x: float = 0.0
    crop_offset_y: float = 0.0

    def __post_init__(self) -> None:
        if self.fit_mode not in ("crop", "contain", "stretch"):
            raise ValueError("不支持的构图方式")
        if self.resample not in ("smooth", "nearest"):
            raise ValueError("不支持的取样方式")
        if self.matcher not in ("oklab", "rgb"):
            raise ValueError("不支持的颜色匹配方式")
        if not -1 <= self.crop_offset_x <= 1 or not -1 <= self.crop_offset_y <= 1:
            raise ValueError("构图偏移必须在 -1 到 1 之间")
        if self.crop_box is not None and not isinstance(self.crop_box, CropBox):
            raise ValueError("裁切区域数据无效")
        if self.reduce_colors:
            self.dither = False


def compose_image(image: Image.Image) -> Image.Image:
    """将透明图像合成到白底，保证所有下游处理都是不透明 RGB。"""
    if image.mode == "RGB":
        return image.copy()
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def prepare_square(image: Image.Image, options: ImageOptions) -> Image.Image:
    source = compose_image(image)
    width, height = source.size
    if not width or not height:
        raise ValueError("图片尺寸无效")
    if options.crop_box is not None:
        options.crop_box.validate_for(source.size)
        left, top, side = options.crop_box.left, options.crop_box.top, options.crop_box.side
        return source.crop((left, top, left + side, top + side))
    if options.fit_mode == "stretch":
        return source.resize((min(width, height), min(width, height)), Image.Resampling.BICUBIC)

    side = max(width, height) if options.fit_mode == "contain" else min(width, height)
    if options.fit_mode == "crop":
        left = round((width - side) * (options.crop_offset_x + 1) / 2)
        top = round((height - side) * (options.crop_offset_y + 1) / 2)
        return source.crop((left, top, left + side, top + side))

    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(source, ((side - width) // 2, (side - height) // 2))
    return square


def enhance_for_pixel_art(image: Image.Image) -> Image.Image:
    """轻度拉开缩小后相邻像素的明暗与饱和度，保留人物关键特征。"""
    enhanced = ImageEnhance.Contrast(image).enhance(1.4)
    return ImageEnhance.Color(enhanced).enhance(1.12)


def _resample_filter(mode: ResampleMode) -> Image.Resampling:
    return Image.Resampling.NEAREST if mode == "nearest" else Image.Resampling.LANCZOS


def convert_image(image: Image.Image, options: ImageOptions | None = None) -> Pattern:
    options = options or ImageOptions()
    prepared = prepare_square(image, options)
    small = prepared.resize((GRID_SIZE, GRID_SIZE), _resample_filter(options.resample))
    enhanced = enhance_for_pixel_art(small)
    colors = [enhanced.getpixel((column, row)) for row in range(GRID_SIZE) for column in range(GRID_SIZE)]
    initial = [nearest_palette_index(color, options.matcher) for color in colors]
    candidates: tuple[int, ...] | None = None
    if options.reduce_colors:
        candidates = tuple(index for index, _ in Counter(initial).most_common(16))
    if options.dither:
        indices = _dither(colors, options.matcher, candidates)
    else:
        indices = [nearest_palette_index(color, options.matcher, candidates) for color in colors]
    return Pattern([indices[offset:offset + GRID_SIZE] for offset in range(0, len(indices), GRID_SIZE)])


def _dither(colors: list[tuple[int, int, int]], matcher: Matcher, candidates: tuple[int, ...] | None) -> list[int]:
    """Floyd-Steinberg 误差扩散，仅作为不降杂色时的可选效果。"""
    from .palette import PALETTE

    work = [[float(channel) for channel in color] for color in colors]
    result: list[int] = []
    for row in range(GRID_SIZE):
        for column in range(GRID_SIZE):
            offset = row * GRID_SIZE + column
            source = tuple(max(0, min(255, round(channel))) for channel in work[offset])
            index = nearest_palette_index(source, matcher, candidates)
            result.append(index)
            error = [work[offset][channel] - PALETTE[index][channel] for channel in range(3)]
            for delta_column, delta_row, weight in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                target_column, target_row = column + delta_column, row + delta_row
                if 0 <= target_column < GRID_SIZE and target_row < GRID_SIZE:
                    target = target_row * GRID_SIZE + target_column
                    for channel in range(3):
                        work[target][channel] += error[channel] * weight
    return result
