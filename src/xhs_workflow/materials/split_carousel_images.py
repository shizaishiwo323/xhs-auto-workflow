#!/usr/bin/env python3
"""Detect and split Xiaohongshu carousel contact-sheet images.

The script keeps original images untouched. Wide composite images are split into
individual vertical pages and written to a separate output folder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def parse_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except Exception as exc:
        raise argparse.ArgumentTypeError("size must look like 1080x1440") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size values must be positive")
    return width, height


def iter_images(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in IMAGE_SUFFIXES:
            yield path
        return

    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
            if "单张裁剪" in item.parts or "split" in item.parts:
                continue
            yield item


def infer_panel_count(width: int, height: int, target_ratio: float, max_panels: int) -> int:
    """Infer how many vertical cards are placed side by side."""
    image_ratio = width / height
    best_count = 1
    best_score = float("inf")

    for count in range(2, max_panels + 1):
        panel_ratio = image_ratio / count
        score = abs(panel_ratio - target_ratio)
        if score < best_score:
            best_score = score
            best_count = count

    return best_count


def background_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    points = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((width - 1, 0)),
        rgb.getpixel((0, height - 1)),
        rgb.getpixel((width - 1, height - 1)),
    ]
    return tuple(int(sum(channel) / len(points)) for channel in zip(*points))


def fit_on_canvas(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """Resize without distortion and pad to the target Xiaohongshu page size."""
    source = ImageOps.exif_transpose(image).convert("RGB")
    canvas_color = background_color(source)
    target_width, target_height = target_size

    source.thumbnail(target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, canvas_color)
    left = (target_width - source.width) // 2
    top = (target_height - source.height) // 2
    canvas.paste(source, (left, top))
    return canvas


def split_image(
    image_path: Path,
    output_dir: Path,
    *,
    count: int | None,
    wide_threshold: float,
    target_ratio: float,
    max_panels: int,
    target_size: tuple[int, int] | None,
) -> dict:
    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    ratio = width / height

    result = {
        "source": str(image_path),
        "source_size": [width, height],
        "source_ratio": round(ratio, 4),
        "detected_as_composite": False,
        "panel_count": 1,
        "outputs": [],
    }

    if ratio <= wide_threshold:
        return result

    panel_count = count or infer_panel_count(width, height, target_ratio, max_panels)
    if panel_count < 2:
        return result

    result["detected_as_composite"] = True
    result["panel_count"] = panel_count
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = image_path.stem
    for index in range(panel_count):
        left = round(index * width / panel_count)
        right = round((index + 1) * width / panel_count)
        panel = image.crop((left, 0, right, height))
        if target_size:
            panel = fit_on_canvas(panel, target_size)
        else:
            panel = panel.convert("RGB")

        output_path = output_dir / f"{stem}_{index + 1:02d}.png"
        panel.save(output_path, "PNG")
        result["outputs"].append(str(output_path))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect wide carousel contact sheets and split them into single Xiaohongshu pages."
    )
    parser.add_argument("input", type=Path, help="Image file, image folder, or a material package folder")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Folder for split images. Default: <input>/03_配图/单张裁剪 or sibling 单张裁剪 folder.",
    )
    parser.add_argument("--count", type=int, default=None, help="Force panel count, for example 3")
    parser.add_argument("--wide-threshold", type=float, default=1.25, help="Ratio above this is treated as composite")
    parser.add_argument("--target-ratio", type=float, default=0.75, help="Expected single-card width/height ratio")
    parser.add_argument("--max-panels", type=int, default=6, help="Maximum cards to infer in a composite image")
    parser.add_argument(
        "--target-size",
        type=parse_size,
        default=parse_size("1080x1440"),
        help="Pad each split page to this size without distortion. Use 0x0 to keep crop size.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON report path")
    args = parser.parse_args()

    target_size = None if args.target_size == (0, 0) else args.target_size
    input_path = args.input

    if args.output_dir:
        output_dir = args.output_dir
    elif input_path.is_dir() and (input_path / "03_配图").exists():
        output_dir = input_path / "03_配图" / "单张裁剪"
    elif input_path.is_dir():
        output_dir = input_path / "单张裁剪"
    else:
        output_dir = input_path.parent / "单张裁剪"

    report = []
    for image_path in iter_images(input_path):
        report.append(
            split_image(
                image_path,
                output_dir,
                count=args.count,
                wide_threshold=args.wide_threshold,
                target_ratio=args.target_ratio,
                max_panels=args.max_panels,
                target_size=target_size,
            )
        )

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
