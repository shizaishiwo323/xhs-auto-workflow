#!/usr/bin/env python3
"""Add a small non-destructive watermark to XHS publish images."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def iter_images(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in IMAGE_SUFFIXES:
            yield path
        return
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
            if "加水印" in item.parts or "watermark" in item.parts:
                continue
            yield item


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def add_watermark(
    image_path: Path,
    output_path: Path,
    *,
    text: str,
    opacity: int,
    scale: float,
    margin_ratio: float,
) -> None:
    source = ImageOps.exif_transpose(Image.open(image_path)).convert("RGBA")
    width, height = source.size
    font_size = max(18, int(min(width, height) * scale))
    font = load_font(font_size)
    draw_probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = draw_probe.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    padding_x = max(14, int(font_size * 0.65))
    padding_y = max(8, int(font_size * 0.38))
    margin = max(18, int(min(width, height) * margin_ratio))

    box_width = text_width + padding_x * 2
    box_height = text_height + padding_y * 2
    left = width - box_width - margin
    top = height - box_height - margin

    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (left, top, left + box_width, top + box_height),
        radius=max(8, int(font_size * 0.35)),
        fill=(255, 255, 255, max(35, opacity // 3)),
        outline=(0, 0, 0, max(30, opacity // 4)),
        width=1,
    )
    draw.text(
        (left + padding_x, top + padding_y - bbox[1]),
        text,
        font=font,
        fill=(0, 0, 0, opacity),
    )

    output = Image.alpha_composite(source, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path, "PNG")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a small watermark to images without touching originals.")
    parser.add_argument("input", type=Path, help="Image file or folder")
    parser.add_argument("--output-dir", type=Path, required=True, help="Folder for watermarked PNG outputs")
    parser.add_argument("--text", default="to be here", help="Watermark text")
    parser.add_argument("--opacity", type=int, default=115, help="Text opacity, 0-255")
    parser.add_argument("--scale", type=float, default=0.028, help="Font size as min(width,height) ratio")
    parser.add_argument("--margin-ratio", type=float, default=0.025, help="Margin as min(width,height) ratio")
    args = parser.parse_args()

    outputs = []
    for image_path in iter_images(args.input):
        output_path = args.output_dir / f"{image_path.stem}_watermarked.png"
        add_watermark(
            image_path,
            output_path,
            text=args.text,
            opacity=max(0, min(255, args.opacity)),
            scale=args.scale,
            margin_ratio=args.margin_ratio,
        )
        outputs.append(str(output_path))

    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()

