from __future__ import annotations

import io
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import TextRegion

try:
    from PIL import Image, ImageColor, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def _parse_color(color: str) -> tuple[int, int, int]:
    """Convert a CSS hex color or named color to an (R, G, B) tuple."""
    try:
        rgb = ImageColor.getrgb(color)
        return (rgb[0], rgb[1], rgb[2])
    except Exception:
        return (255, 255, 255)


def _wrap_to_width(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
    max_width: int,
) -> list[str]:
    """Word-wrap *text* so every line fits within *max_width* pixels."""
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        w = draw.textlength(candidate, font=font)
        if w <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _line_height(
    draw: "ImageDraw.ImageDraw",
    font: "ImageFont.FreeTypeFont | ImageFont.ImageFont",
) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return bbox[3] - bbox[1]


def _draw_fitted_text(
    draw: "ImageDraw.ImageDraw",
    text: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    text_color: tuple[int, int, int],
) -> None:
    """Draw *text* inside the bounding box, picking the largest font that fits."""
    box_w = x2 - x1
    box_h = y2 - y1
    padding = 3

    for font_size in range(max(box_w, box_h) // 2, 5, -1):
        font: "ImageFont.FreeTypeFont | ImageFont.ImageFont"
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        available_w = box_w - padding * 2
        available_h = box_h - padding * 2
        lines = _wrap_to_width(draw, text, font, available_w)
        lh = _line_height(draw, font)
        total_h = lh * len(lines) + max(0, len(lines) - 1) * 2

        if total_h <= available_h:
            curr_y = y1 + padding
            for line in lines:
                draw.text((x1 + padding, curr_y), line, fill=text_color, font=font)
                curr_y += lh + 2
            return

    # Last-resort: draw with default font regardless of fit
    font = ImageFont.load_default()
    lines = textwrap.wrap(text, width=max(1, box_w // 6)) or [text]
    curr_y = y1 + 2
    for line in lines[:3]:
        draw.text((x1 + 2, curr_y), line, fill=text_color, font=font)
        curr_y += 12


def apply_translations(
    image_bytes: bytes,
    regions: "list[TextRegion]",
) -> bytes:
    """Apply translated text regions to an image and return the modified bytes."""
    if not PIL_AVAILABLE:
        return image_bytes

    img_fmt = _detect_format(image_bytes)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    for region in regions:
        if not region.translation:
            continue

        # Clamp bounding box to image dimensions
        x1 = max(0, min(region.x1, img.width - 1))
        y1 = max(0, min(region.y1, img.height - 1))
        x2 = max(x1 + 1, min(region.x2, img.width))
        y2 = max(y1 + 1, min(region.y2, img.height))

        bg = _parse_color(region.background_color)
        fg = _parse_color(region.text_color)

        # Erase original text by filling with background color
        draw.rectangle([x1, y1, x2, y2], fill=(*bg, 255))

        # Render the translation
        _draw_fitted_text(draw, region.translation, x1, y1, x2, y2, fg)

    output = io.BytesIO()
    if img_fmt.upper() in ("JPEG", "JPG"):
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=90)
    else:
        img.save(output, format=img_fmt.upper() if img_fmt else "PNG")
    return output.getvalue()


def _detect_format(image_bytes: bytes) -> str:
    if not PIL_AVAILABLE:
        return "jpeg"
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.format or "jpeg"
