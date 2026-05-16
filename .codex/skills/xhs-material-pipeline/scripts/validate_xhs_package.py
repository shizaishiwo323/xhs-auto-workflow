#!/usr/bin/env python3
"""Validate a Xiaohongshu material package for publish constraints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def image_info(path: Path, composite_threshold: float) -> dict[str, Any]:
    image = ImageOps.exif_transpose(Image.open(path))
    width, height = image.size
    ratio = width / height
    return {
        "path": str(path.resolve()),
        "width": width,
        "height": height,
        "ratio": round(ratio, 4),
        "likely_composite": ratio > composite_threshold,
        "publish_friendly_ratio": 0.55 <= ratio <= 0.9,
    }


def read_publish_rows(package: Path) -> list[dict[str, Any]]:
    candidates = [
        package / "00_自动发推适配" / "merged_table.xlsx",
        package / "00_自动发推适配" / "publish_queue.xlsx",
        package / "merged_table.xlsx",
    ]
    for candidate in candidates:
        if candidate.exists():
            df = pd.read_excel(candidate)
            return df.fillna("").to_dict("records")
    return []


def collect_manifest_images(package: Path) -> list[Path]:
    manifest = package / "00_自动发推适配" / "publish_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        images = []
        for item in data.get("images", []):
            path = Path(str(item.get("path", "")))
            if path.exists() and path.suffix.lower() in IMAGE_SUFFIXES:
                images.append(path)
        if images:
            return images

    image_dirs = [package / "02_封面", package / "03_配图" / "单张裁剪", package / "03_配图"]
    images = []
    for image_dir in image_dirs:
        if image_dir.exists():
            for path in sorted(image_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    if "加水印" in path.parts:
                        continue
                    images.append(path)
    return images


def validate(package: Path, composite_threshold: float) -> dict[str, Any]:
    rows = read_publish_rows(package)
    images = collect_manifest_images(package)
    issues = []

    if not rows:
        issues.append("未找到 merged_table.xlsx 或 publish_queue.xlsx。")

    row_checks = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("标题", ""))
        body = str(row.get("推文", ""))
        cover = str(row.get("封面地址", ""))
        check = {
            "row": index,
            "title_chars": len(title),
            "body_chars": len(body),
            "cover_exists": bool(cover and Path(cover).exists()),
        }
        if len(title) > 20:
            issues.append(f"第{index}行标题超过20字：{len(title)}")
        if len(body) > 1000:
            issues.append(f"第{index}行正文超过1000字：{len(body)}")
        if cover and not Path(cover).exists():
            issues.append(f"第{index}行封面不存在：{cover}")
        row_checks.append(check)

    image_checks = []
    for path in images:
        try:
            info = image_info(path, composite_threshold)
            image_checks.append(info)
            if info["likely_composite"]:
                issues.append(f"疑似横向拼版，需要裁剪：{path}")
        except Exception as exc:
            issues.append(f"图片无法读取：{path} ({exc})")

    if len(images) > 18:
        issues.append(f"图片数量超过18张：{len(images)}")

    return {
        "package": str(package.resolve()),
        "ok": not issues,
        "issues": issues,
        "row_checks": row_checks,
        "image_count": len(images),
        "image_checks": image_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an XHS material package.")
    parser.add_argument("package", type=Path, help="Package folder")
    parser.add_argument("--composite-threshold", type=float, default=1.25)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    result = validate(args.package, args.composite_threshold)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
