#!/usr/bin/env python3
"""Validate a Xiaohongshu material package for publish constraints."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TOPIC_FIELDS = ("recommended_topics", "topic_tags", "topics", "tags", "hot_topics")
COLLECTION_FIELDS = ("collection_name", "collection_title", "target_collection", "collection")
COLLECTION_INTRO_FIELDS = ("collection_intro", "collection_description", "collection_desc")
COLLECTION_TITLE_LIMIT = 20
COLLECTION_INTRO_LIMIT = 50
TAROT_COLLECTION = "塔罗牌合集"
DATA_COLLECTION = "数据资源的合集"
CASUAL_COLLECTION = "随便发发合集"
FIXED_COLLECTIONS = (TAROT_COLLECTION, DATA_COLLECTION, CASUAL_COLLECTION)
DATA_COLLECTION_KEYWORDS = (
    "数据",
    "爬虫",
    "爬取",
    "采集",
    "公开",
    "字段",
    "表格",
    "分析",
    "可视化",
    "清洗",
    "python",
    "pandas",
    "excel",
    "api",
)
TAROT_COLLECTION_KEYWORDS = ("塔罗", "tarot")
TAROT_CONTENT_KEYWORDS = ("塔罗", "tarot")
TAROT_RISK_PATTERNS = (
    ("预测未来或断言结局", r"(预测|预言|断言|测出).{0,8}(未来|结局|结果|命运)"),
    ("改变未来或改运消灾", r"(改变未来|改命|改运|转运|消灾|化解厄运|逆天改命)"),
    ("运势测算或实现愿望", r"(运势测算|每日运势|本周运势|实现愿望|愿望成真|心想事成)"),
    ("封建迷信服务或商品", r"(代参拜|代开光|开光|符箓|法事|能量水晶|灵验)"),
    ("付费占卜或私域引流", r"(付费占卜|私信.{0,6}占卜|私聊.{0,6}占卜|加微|加v|VX|微信)"),
    ("隐私信息收集", r"(生日|生辰|八字|手机号|身份证).{0,8}(发我|私信|填写|提供)"),
    ("未成年人学业绑定", r"(未成年|小学生|初中生|高中生|学生|考试|升学|中考|高考).{0,12}(塔罗|占卜|运势|预测)"),
    ("互动换福利", r"(点赞|评论|收藏|关注|互关|互赞).{0,10}(福利|抽奖|领取|获得|好运|解读|资源)"),
)


def has_tarot_context(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(keyword.lower() in normalized for keyword in TAROT_CONTENT_KEYWORDS)


def is_negated_context(text: str, start: int) -> bool:
    prefix = str(text or "")[max(0, start - 8):start]
    return any(marker in prefix for marker in ("不", "不要", "不做", "不是", "不能", "避免", "拒绝", "非"))


def find_tarot_safety_issues(*parts: Any) -> list[str]:
    text = " ".join(str(part or "") for part in parts)
    if not has_tarot_context(text):
        return []

    issues: list[str] = []
    for label, pattern in TAROT_RISK_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if not is_negated_context(text, match.start()):
                issues.append(f"塔罗牌内容触及边界：{label}")
                break
    return issues


def normalize_topic_tag(raw: Any) -> str:
    return str(raw or "").strip().lstrip("#").strip()


def collect_manifest_topics(package: Path) -> list[str]:
    manifest = package / "00_自动发推适配" / "publish_manifest.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    topics: list[str] = []
    for field in TOPIC_FIELDS:
        raw = data.get(field)
        if raw is None:
            continue
        if isinstance(raw, str):
            candidates = re.split(r"[\s,，、;；|]+", raw)
        elif isinstance(raw, list):
            candidates = raw
        else:
            candidates = [raw]
        for candidate in candidates:
            tag = normalize_topic_tag(candidate)
            if tag and tag not in topics:
                topics.append(tag)
        if topics:
            break
    return topics


def first_manifest_text(data: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        raw = data.get(field)
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("title")
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def collect_manifest_collection(package: Path) -> dict[str, Any]:
    manifest = package / "00_自动发推适配" / "publish_manifest.json"
    if not manifest.exists():
        return {"name": "", "intro": ""}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        "name": first_manifest_text(data, COLLECTION_FIELDS),
        "intro": first_manifest_text(data, COLLECTION_INTRO_FIELDS),
    }


def short_text(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_collection_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def canonical_collection_name(text: str) -> str | None:
    normalized = normalize_collection_text(text).lower()
    if not normalized:
        return None
    for collection in FIXED_COLLECTIONS:
        collection_norm = normalize_collection_text(collection).lower()
        if collection_norm in normalized or normalized in collection_norm:
            return collection
    if any(keyword.lower() in normalized for keyword in TAROT_COLLECTION_KEYWORDS):
        return TAROT_COLLECTION
    if any(keyword.lower() in normalized for keyword in DATA_COLLECTION_KEYWORDS):
        return DATA_COLLECTION
    return None


def infer_collection_name(package: Path, title: str, topics: list[str]) -> str:
    text = " ".join([package.name, title, " ".join(topics)])
    canonical = canonical_collection_name(text)
    return canonical or CASUAL_COLLECTION


def infer_collection_intro(title: str, topics: list[str]) -> str:
    if topics:
        intro = "、".join(topics[:4]) + "相关内容整理"
    else:
        intro = f"{title}相关内容整理"
    return short_text(intro, COLLECTION_INTRO_LIMIT)


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
    topics = collect_manifest_topics(package)
    collection = collect_manifest_collection(package)
    first_title = str(rows[0].get("标题", "")) if rows else ""
    if collection["name"]:
        collection["name"] = canonical_collection_name(
            " ".join([collection["name"], package.name, first_title, " ".join(topics)])
        ) or CASUAL_COLLECTION
        collection["inferred"] = False
    else:
        collection["name"] = infer_collection_name(package, first_title, topics)
        collection["inferred"] = True
    if not collection["intro"]:
        collection["intro"] = infer_collection_intro(first_title, topics)
    issues = []

    if not rows:
        issues.append("未找到 merged_table.xlsx 或 publish_queue.xlsx。")
    if not (package / "00_自动发推适配" / "publish_manifest.json").exists():
        issues.append("未找到 publish_manifest.json。")
    if not topics:
        issues.append("缺少发布话题：请在 manifest 中提供 recommended_topics/topic_tags/topics/tags。")
    if collection["name"] and len(collection["name"]) > COLLECTION_TITLE_LIMIT:
        issues.append(f"合集名称超过{COLLECTION_TITLE_LIMIT}字：{len(collection['name'])}")
    if collection["intro"] and len(collection["intro"]) > COLLECTION_INTRO_LIMIT:
        issues.append(f"合集简介超过{COLLECTION_INTRO_LIMIT}字：{len(collection['intro'])}")

    row_checks = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("标题", ""))
        body = str(row.get("推文", ""))
        cover = str(row.get("封面地址", ""))
        for issue in find_tarot_safety_issues(title, body, topics, collection["name"], collection["intro"]):
            issues.append(f"第{index}行{issue}")
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
        "topic_tags": topics,
        "collection": collection,
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
