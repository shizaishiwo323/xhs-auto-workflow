# -*- coding: utf-8 -*-
"""Notebook-derived Xiaohongshu auto publisher.

This module is a parameterized Python version of
``notebooks/publisher/xhs_auto_publish.ipynb``.  It keeps the notebook's
queue, validation, scheduling, browser actions, history, and notification
flow as the baseline, while making the inputs callable from scripts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import pandas as pd

from xhs_workflow.materials.validate_xhs_package import validate as validate_material_package

try:
    from xhs_notify import notify_failure, send_email
except Exception:
    try:
        from xhs_workflow.notify import notify_failure, send_email
    except Exception:
        def notify_failure(*args, **kwargs):
            return False

        def send_email(*args, **kwargs):
            return False


ROOT = Path(__file__).resolve().parents[3]
TITLE_LIMIT = 20
BODY_LIMIT = 1000
IMAGE_LIMIT = 18
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
DEFAULT_DAILY_TIME_SLOTS = ("12:00", "16:00")
DEFAULT_TOPIC_ORDER = [
    "数据获取爬虫_公开数据流程",
    "数据分析方法选择表",
]
HISTORY_COLUMNS = [
    "recorded_at",
    "status",
    "publish_key",
    "topic_folder",
    "title",
    "body_chars",
    "image_count",
    "topic_tags_json",
    "collection_name",
    "schedule_time",
    "manifest_path",
    "cover_path",
    "image_paths_json",
    "materials_date",
    "message",
]
SUCCESS_STATUSES = {"scheduled", "scheduled_click_success", "published", "submitted", "success"}


@dataclass
class PublishConfig:
    root: Path = ROOT
    materials_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    materials_dir: Path | None = None
    chromium_port: int = 9209
    submit: bool = True
    daily_time_slots: tuple[str, ...] = DEFAULT_DAILY_TIME_SLOTS
    topic_order: list[str] = field(default_factory=lambda: list(DEFAULT_TOPIC_ORDER))

    @property
    def resolved_materials_dir(self) -> Path:
        return self.materials_dir or (self.root / "outputs" / "materials" / self.materials_date)

    @property
    def history_dir(self) -> Path:
        return self.root / "outputs" / "publish_history"

    @property
    def history_xlsx(self) -> Path:
        return self.history_dir / "published_history.xlsx"

    @property
    def history_csv(self) -> Path:
        return self.history_dir / "published_history.csv"

    @property
    def history_jsonl(self) -> Path:
        return self.history_dir / "published_history.jsonl"


@dataclass
class PublishItem:
    topic_folder: str
    manifest_path: Path
    publish_key: str
    title: str
    body: str
    images: list[Path]
    topic_tags: list[str]
    collection_name: str
    collection_intro: str
    schedule_time: str | None = None


def resolve_image_path(raw_path: str, manifest_path: Path, config: PublishConfig) -> Path:
    path = Path(str(raw_path)).expanduser()
    if path.exists():
        return path

    daily_root = config.root / "xhs每日生成素材"
    output_root = config.root / "outputs" / "materials"
    try:
        rel = path.relative_to(daily_root)
        alt = output_root / rel
        if alt.exists():
            return alt
    except ValueError:
        pass

    package_dir = manifest_path.parents[1]
    alt = package_dir / path
    if alt.exists():
        return alt
    return path


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"manifest 格式不正确：{path}")
    return data


def publish_key_for_manifest(manifest_path: Path, manifest: dict[str, Any]) -> str:
    row = manifest.get("publish_row") or {}
    image_paths = [
        str(item.get("path", ""))
        for item in sorted(manifest.get("images", []), key=lambda item: item.get("upload_order", 999))
    ]
    payload = {
        "topic_folder": manifest_path.parents[1].name,
        "title": str(manifest.get("recommended_title") or row.get("标题") or "").strip(),
        "body": str(manifest.get("body") or row.get("推文") or "").strip(),
        "images": image_paths,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pick_text(manifest: dict[str, Any]) -> tuple[str, str]:
    row = manifest.get("publish_row") or {}
    title = str(manifest.get("recommended_title") or row.get("标题") or "").strip()
    body = str(manifest.get("body") or row.get("推文") or "").strip()
    return title[:TITLE_LIMIT], body[:BODY_LIMIT]


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


def pick_topic_tags(manifest: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for field in TOPIC_FIELDS:
        raw = manifest.get(field)
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
            if tag and tag not in tags:
                tags.append(tag)
        if tags:
            break
    return tags


def _first_manifest_text(manifest: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        raw = manifest.get(field)
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("title")
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _short_text(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def canonical_collection_name(text: str) -> str | None:
    normalized = re.sub(r"\s+", "", str(text or "").strip()).lower()
    if not normalized:
        return None
    for collection in FIXED_COLLECTIONS:
        collection_norm = re.sub(r"\s+", "", collection).lower()
        if collection_norm in normalized or normalized in collection_norm:
            return collection
    if any(keyword.lower() in normalized for keyword in TAROT_COLLECTION_KEYWORDS):
        return TAROT_COLLECTION
    if any(keyword.lower() in normalized for keyword in DATA_COLLECTION_KEYWORDS):
        return DATA_COLLECTION
    return None


def infer_collection_name(manifest: dict[str, Any], title: str, topic_folder: str, topic_tags: list[str]) -> str:
    explicit = _first_manifest_text(manifest, COLLECTION_FIELDS)
    if explicit:
        canonical = canonical_collection_name(explicit)
        if canonical:
            return canonical

    text = " ".join([title, topic_folder, " ".join(topic_tags)])
    canonical = canonical_collection_name(text)
    return canonical or CASUAL_COLLECTION


def infer_collection_intro(manifest: dict[str, Any], collection_name: str, title: str, topic_tags: list[str]) -> str:
    explicit = _first_manifest_text(manifest, COLLECTION_INTRO_FIELDS)
    if explicit:
        return _short_text(explicit, COLLECTION_INTRO_LIMIT)

    if topic_tags:
        intro = "、".join(topic_tags[:4]) + "相关内容整理"
    else:
        intro = f"{title}相关内容整理"
    return _short_text(intro or f"{collection_name}简介", COLLECTION_INTRO_LIMIT)


def pick_collection(manifest: dict[str, Any], title: str, topic_folder: str, topic_tags: list[str]) -> tuple[str, str]:
    collection_name = infer_collection_name(manifest, title, topic_folder, topic_tags)
    collection_intro = infer_collection_intro(manifest, collection_name, title, topic_tags)
    return collection_name, collection_intro


def ordered_images(manifest: dict[str, Any], manifest_path: Path, config: PublishConfig) -> list[Path]:
    items = sorted(manifest.get("images", []), key=lambda item: item.get("upload_order", 999))
    return [resolve_image_path(str(item.get("path", "")), manifest_path, config) for item in items]


def discover_manifests(config: PublishConfig) -> list[Path]:
    manifests = list(config.resolved_materials_dir.glob("*/00_自动发推适配/publish_manifest.json"))
    if config.topic_order:
        order = {name: idx for idx, name in enumerate(config.topic_order)}
        manifests.sort(key=lambda p: (order.get(p.parents[1].name, 999), p.parents[1].name))
    else:
        manifests.sort(key=lambda p: p.parents[1].name)
    return manifests


def generate_schedule_times(count: int, config: PublishConfig) -> list[str]:
    material_date = datetime.strptime(config.materials_date, "%Y-%m-%d").date()
    start_date = material_date + timedelta(days=1)

    tomorrow = datetime.now().date() + timedelta(days=1)
    if start_date < tomorrow:
        start_date = tomorrow

    slots: list[str] = []
    day = start_date
    while len(slots) < count:
        for slot in config.daily_time_slots:
            slots.append(f"{day:%Y-%m-%d} {slot}")
            if len(slots) >= count:
                break
        day += timedelta(days=1)
    return slots


def validate_schedule_time(value: str) -> str:
    try:
        publish_at = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("定时时间格式应为 YYYY-MM-DD HH:MM，例如 2026-05-10 20:30") from exc
    if publish_at <= datetime.now():
        raise ValueError(f"定时时间必须晚于当前时间：{value}")
    return publish_at.strftime("%Y-%m-%d %H:%M")


def validate_item(item: PublishItem) -> list[str]:
    issues: list[str] = []
    if not item.title:
        issues.append("缺少标题")
    if len(item.title) > TITLE_LIMIT:
        issues.append(f"标题超过 {TITLE_LIMIT} 字：{len(item.title)}")
    if not item.body:
        issues.append("缺少正文")
    if len(item.body) > BODY_LIMIT:
        issues.append(f"正文超过 {BODY_LIMIT} 字：{len(item.body)}")
    if not item.topic_tags:
        issues.append("缺少话题标签：请在 manifest 中提供 recommended_topics/topic_tags/topics/tags")
    if not item.collection_name:
        issues.append("缺少合集名称")
    if len(item.collection_name) > COLLECTION_TITLE_LIMIT:
        issues.append(f"合集名称超过 {COLLECTION_TITLE_LIMIT} 字：{len(item.collection_name)}")
    if len(item.collection_intro) > COLLECTION_INTRO_LIMIT:
        issues.append(f"合集简介超过 {COLLECTION_INTRO_LIMIT} 字：{len(item.collection_intro)}")
    issues.extend(find_tarot_safety_issues(item.title, item.body, item.topic_tags, item.collection_name, item.collection_intro))
    if not item.images:
        issues.append("缺少图片")
    if len(item.images) > IMAGE_LIMIT:
        issues.append(f"图片超过 {IMAGE_LIMIT} 张：{len(item.images)}")
    for image in item.images:
        if not image.exists():
            issues.append(f"图片不存在：{image}")
    return issues


def load_publish_history(config: PublishConfig) -> pd.DataFrame:
    if config.history_xlsx.exists():
        df = pd.read_excel(config.history_xlsx, dtype=str).fillna("")
    elif config.history_csv.exists():
        df = pd.read_csv(config.history_csv, dtype=str).fillna("")
    else:
        df = pd.DataFrame(columns=HISTORY_COLUMNS)
    for col in HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[HISTORY_COLUMNS]


def load_published_keys(config: PublishConfig) -> set[str]:
    history = load_publish_history(config)
    if history.empty:
        return set()
    status = history["status"].astype(str).str.lower()
    return set(history.loc[status.isin(SUCCESS_STATUSES), "publish_key"].astype(str))


def make_history_record(item: PublishItem, config: PublishConfig, *, status: str, message: str = "") -> dict[str, Any]:
    return {
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "publish_key": item.publish_key,
        "topic_folder": item.topic_folder,
        "title": item.title,
        "body_chars": len(item.body),
        "image_count": len(item.images),
        "topic_tags_json": json.dumps(item.topic_tags, ensure_ascii=False),
        "collection_name": item.collection_name,
        "schedule_time": item.schedule_time or "",
        "manifest_path": str(item.manifest_path),
        "cover_path": str(item.images[0]) if item.images else "",
        "image_paths_json": json.dumps([str(p) for p in item.images], ensure_ascii=False),
        "materials_date": config.materials_date,
        "message": message,
    }


def append_publish_history(
    item: PublishItem,
    config: PublishConfig,
    *,
    status: str = "scheduled_click_success",
    message: str = "已点击定时发布",
) -> Path:
    config.history_dir.mkdir(parents=True, exist_ok=True)
    record = make_history_record(item, config, status=status, message=message)
    history = load_publish_history(config)
    history = pd.concat([history, pd.DataFrame([record])], ignore_index=True)
    history.to_excel(config.history_xlsx, index=False)
    history.to_csv(config.history_csv, index=False, encoding="utf-8-sig")
    with config.history_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return config.history_xlsx


def build_completion_body(processed_items: list[PublishItem], config: PublishConfig, skipped_count: int = 0) -> str:
    lines = [
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"素材日期：{config.materials_date}",
        f"本次检测发布成功：{len(processed_items)} 篇",
        f"因历史记录跳过：{skipped_count} 篇",
        f"发布历史表：{config.history_xlsx}",
        "",
    ]
    if processed_items:
        lines.append("本次发布明细：")
        for idx, item in enumerate(processed_items, 1):
            lines.append(f"{idx}. {item.topic_folder}｜{item.title}｜{item.schedule_time}｜图片{len(item.images)}张")
    else:
        lines.append("本次没有新的待发布素材。")
    return "\n".join(lines)


def send_publish_completion_email(processed_items: list[PublishItem], config: PublishConfig, skipped_count: int = 0) -> bool:
    subject = f"[小红书自动化完成] 定时发布 {len(processed_items)} 篇"
    attachments = [path for path in (config.history_xlsx, config.history_csv) if path.exists()]
    return send_email(
        subject=subject,
        body=build_completion_body(processed_items, config, skipped_count=skipped_count),
        attachments=attachments,
    )


def build_publish_item(
    manifest_path: Path,
    manifest: dict[str, Any],
    config: PublishConfig,
    *,
    publish_key: str | None = None,
    schedule_time: str | None = None,
) -> PublishItem:
    package_issues = validate_material_package_for_publish(manifest_path)
    if package_issues:
        raise ValueError(
            f"{manifest_path.parents[1].name} 发布前素材包门禁未通过："
            + "；".join(package_issues)
        )
    title, body = pick_text(manifest)
    topic_tags = pick_topic_tags(manifest)
    collection_name, collection_intro = pick_collection(manifest, title, manifest_path.parents[1].name, topic_tags)
    return PublishItem(
        topic_folder=manifest_path.parents[1].name,
        manifest_path=manifest_path,
        publish_key=publish_key or publish_key_for_manifest(manifest_path, manifest),
        title=title,
        body=body,
        images=ordered_images(manifest, manifest_path, config),
        topic_tags=topic_tags,
        collection_name=collection_name,
        collection_intro=collection_intro,
        schedule_time=schedule_time,
    )


def validate_material_package_for_publish(manifest_path: Path) -> list[str]:
    package = manifest_path.parents[1]
    result = validate_material_package(package, composite_threshold=1.25)
    return list(result.get("issues") or [])


def load_publish_queue(config: PublishConfig) -> list[PublishItem]:
    manifests = discover_manifests(config)
    if not manifests:
        raise FileNotFoundError(f"没有找到 publish_manifest.json：{config.resolved_materials_dir}")

    published_keys = load_published_keys(config)
    pending: list[tuple[Path, dict[str, Any], str]] = []
    skipped: list[tuple[str, str]] = []
    for manifest_path in manifests:
        manifest = load_manifest(manifest_path)
        publish_key = publish_key_for_manifest(manifest_path, manifest)
        if publish_key in published_keys:
            skipped.append((manifest_path.parents[1].name, publish_key[:12]))
            continue
        pending.append((manifest_path, manifest, publish_key))

    if skipped:
        print(f"根据发布历史跳过 {len(skipped)} 篇已发布素材：")
        for topic, key in skipped:
            print(f"  - {topic} ({key})")

    schedule_times = generate_schedule_times(len(pending), config)
    return [
        build_publish_item(manifest_path, manifest, config, publish_key=publish_key, schedule_time=schedule_time)
        for (manifest_path, manifest, publish_key), schedule_time in zip(pending, schedule_times)
    ]


def print_publish_queue(publish_queue: list[PublishItem]) -> None:
    for idx, item in enumerate(publish_queue, 1):
        issues = validate_item(item)
        print(f"[{idx}] {item.topic_folder}")
        print("  标题：", item.title, f"({len(item.title)}/{TITLE_LIMIT})")
        print("  正文：", f"{len(item.body)}/{BODY_LIMIT}")
        print("  图片：", len(item.images), f"/{IMAGE_LIMIT}")
        print("  话题：", "、".join(item.topic_tags) if item.topic_tags else "未设置")
        print("  合集：", item.collection_name, f"({len(item.collection_name)}/{COLLECTION_TITLE_LIMIT})")
        print("  定时：", item.schedule_time)
        print("  manifest：", item.manifest_path)
        for image in item.images:
            print("   -", image)
        if issues:
            print("  校验问题：")
            for issue in issues:
                print("   !", issue)
        print()


def validate_queue_or_raise(publish_queue: list[PublishItem]) -> None:
    all_issues = [(item.topic_folder, validate_item(item)) for item in publish_queue]
    all_issues = [(topic, issues) for topic, issues in all_issues if issues]
    if all_issues:
        raise ValueError("发布校验未通过，请先处理上面列出的问题。")
    print("发布队列校验通过。")


def connect_browser(port: int = 9209):
    from DrissionPage import ChromiumOptions, ChromiumPage
    from DrissionPage.common import Actions

    co = (
        ChromiumOptions()
        .set_paths(local_port=port)
        .mute(True)
        .set_argument("--start-maximized")
        .ignore_certificate_errors(True)
    )
    page = ChromiumPage(co)
    page.set.auto_handle_alert()
    actions = Actions(page)
    page.get("https://creator.xiaohongshu.com/publish/publish?from=menu")
    return page, actions


def open_image_publish_page(page, actions) -> None:
    try:
        page.get("https://creator.xiaohongshu.com/publish/publish?from=menu&target=image")
    except Exception:
        page.get("https://creator.xiaohongshu.com/publish/publish")
    sleep(2)
    try:
        tab = page.ele("text=上传图文", timeout=2)
        actions.move_to(ele_or_loc=tab).click()
    except Exception:
        pass


def real_element(ele):
    if ele is None or getattr(ele, "_type", "") == "NoneElement":
        return None
    return ele


def element_has_size(ele) -> bool:
    try:
        width, height = ele.rect.size
        return width > 0 and height > 0
    except Exception:
        return False


def find_real_element(scope, selector: str, timeout: float = 2):
    try:
        return real_element(scope.ele(selector, timeout=timeout))
    except Exception:
        return None


def scroll_down(page, actions, distance: int = 700) -> None:
    try:
        size = page.run_js("return {w: window.innerWidth, h: window.innerHeight};")
        actions.move_to((size["w"] // 2, size["h"] // 2))
    except Exception:
        pass

    total = 0
    while total < distance:
        actions.scroll(delta_y=70)
        total += 70
        sleep(0.08)


def human_scroll_down(page, actions, distance: int) -> None:
    from random import randint, uniform

    sleep(3)
    try:
        size = page.run_js("return {w: window.innerWidth, h: window.innerHeight};")
        center_x = size["w"] // 2
        center_y = size["h"] // 2
        actions.move_to((center_x, center_y))
    except Exception:
        pass

    total = 0
    while total < distance:
        step = randint(35, 70)
        actions.scroll(delta_y=step)
        total += step
        sleep(uniform(0.08, 0.18))


def find_upload_control(page, first_image: bool = False):
    selectors = (
        ".entry",
        "tx=上传图片",
        ".upload-wrapper",
        ".upload-input",
        "@type=file",
    )
    for selector in selectors:
        ele = find_real_element(page, selector, timeout=5 if first_image else 2)
        if not ele:
            continue
        try:
            is_image_file_input = (
                ele.tag == "input"
                and ele.attr("type") == "file"
                and "image" in str(ele.attr("accept") or "").lower()
            )
        except Exception:
            is_image_file_input = False
        if is_image_file_input:
            return ele
        if not element_has_size(ele):
            continue
        return ele
    raise RuntimeError("找不到上传图片控件。")


def current_uploaded_image_count(page) -> int:
    try:
        text = page.ele("tag:body", timeout=1).text
    except Exception:
        return 0
    match = re.search(r"图片编辑\s*(\d+)/18", text) or re.search(r"(\d+)/18", text)
    return int(match.group(1)) if match else 0


def wait_uploaded_image_count(page, min_count: int, timeout: float = 45) -> None:
    end = perf_counter() + timeout
    while perf_counter() < end:
        if current_uploaded_image_count(page) >= min_count:
            return
        page.wait(1)
    raise RuntimeError(f"图片上传后未等到数量更新到 {min_count}/18。")


def upload_file(upload, image: Path) -> None:
    try:
        if upload.tag == "input" and upload.attr("type") == "file":
            upload.input(str(image))
            return
    except Exception:
        pass
    upload.click.to_upload(str(image))


def upload_files(upload, images: list[Path]) -> None:
    file_paths = [str(image) for image in images]
    try:
        if upload.tag == "input" and upload.attr("type") == "file":
            upload.input(file_paths)
            return
    except Exception:
        pass
    upload.click.to_upload(file_paths)


def upload_images(page, images: list[Path]) -> None:
    if not images:
        return

    if len(images) > 1:
        try:
            upload = find_upload_control(page, first_image=True)
            upload_files(upload, images)
            wait_uploaded_image_count(page, len(images), timeout=max(60, 25 * len(images)))
            return
        except Exception as exc:
            current_count = current_uploaded_image_count(page)
            if current_count:
                raise RuntimeError(
                    f"批量上传图片后只识别到 {current_count}/{len(images)} 张，请刷新发布页后重试。"
                ) from exc
            print(f"批量上传图片失败，准备逐张重试：{exc}")

    for idx, image in enumerate(images):
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                upload = find_upload_control(page, first_image=(idx == 0))
                upload_file(upload, image)
                wait_uploaded_image_count(page, idx + 1)
                break
            except Exception as exc:
                last_error = exc
                print(f"第{idx + 1}张图片上传失败，准备重试 {attempt}/3：{exc}")
                page.wait(2)
        else:
            raise RuntimeError(f"第{idx + 1}张图片上传失败：{image}") from last_error


def fill_field(page, selectors: tuple[str, ...], value: str, field_name: str):
    last_error: Exception | None = None
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=4)
            ele.input(value)
            return ele
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"找不到{field_name}输入框。") from last_error


def move_body_cursor_after_input(actions) -> None:
    from DrissionPage.common import Keys

    for _ in range(2):
        actions.key_down(Keys.DOWN).key_up(Keys.DOWN)
        sleep(0.05)
    actions.key_down(Keys.END).key_up(Keys.END)


def input_preselected_topic_tags(input_target, topic_tags: list[str]) -> None:
    for tag in topic_tags:
        input_target.input(f"#{tag}")
        sleep(0.5)
        input_target.input("\n")


def normalize_collection_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def parse_collection_names(raw_text: str) -> list[str]:
    names: list[str] = []
    for line in str(raw_text or "").splitlines():
        name = line.strip()
        if not name or "创建合集" in name or name in {"合集", "选择合集"}:
            continue
        if name not in names:
            names.append(name)
    return names


def collection_match_score(target: str, existing: str, topic_tags: list[str]) -> int:
    canonical_target = canonical_collection_name(target)
    canonical_existing = canonical_collection_name(existing)
    if canonical_target and canonical_existing:
        return 100 if canonical_target == canonical_existing else 0

    target_norm = normalize_collection_text(target)
    existing_norm = normalize_collection_text(existing)
    if not target_norm or not existing_norm:
        return 0
    if target_norm == existing_norm:
        return 100
    if target_norm in existing_norm or existing_norm in target_norm:
        return 80

    score = 0
    for tag in topic_tags:
        tag_norm = normalize_collection_text(tag)
        if tag_norm and (tag_norm in existing_norm or existing_norm in tag_norm):
            score += 20
    for keyword in ("数据", "爬虫", "爬取", "采集", "公开", "分析", "塔罗"):
        if keyword in target_norm and keyword in existing_norm:
            score += 15
    return score


def best_existing_collection(target: str, existing_names: list[str], topic_tags: list[str]) -> str | None:
    target_norm = normalize_collection_text(target)
    for name in existing_names:
        if normalize_collection_text(name) == target_norm:
            return name
    for name in existing_names:
        existing_norm = normalize_collection_text(name)
        if target_norm and (target_norm in existing_norm or existing_norm in target_norm):
            return name

    scored = [(collection_match_score(target, name, topic_tags), name) for name in existing_names]
    scored = [(score, name) for score, name in scored if score >= 20]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return scored[0][1]


def open_collection_popover(page, actions):
    sleep(3)
    wrapper = page.ele(".collection-plugin-wrapper", timeout=5)
    actions.move_to(ele_or_loc=wrapper).click()
    sleep(1)
    return page.ele(".collection-plugin-popover-content", timeout=5)


def select_or_create_collection(page, actions, item: PublishItem) -> None:
    popover = open_collection_popover(page, actions)
    existing_text = str(getattr(popover, "text", "") or "")
    print(existing_text)
    existing_names = parse_collection_names(existing_text)
    target_collection = best_existing_collection(item.collection_name, existing_names, item.topic_tags)

    if target_collection:
        target = popover.ele(f"tx:{target_collection}", timeout=3)
        actions.move_to(ele_or_loc=target).click()
        sleep(1)
        selected = page.ele(".collection-name", timeout=5).text
        print(selected)
        if normalize_collection_text(target_collection) not in normalize_collection_text(selected):
            raise RuntimeError(f"合集选择后校验不一致：期望 {target_collection}，页面显示 {selected}")
        return

    available = "、".join(existing_names) if existing_names else "未读取到合集"
    fixed = "、".join(FIXED_COLLECTIONS)
    raise RuntimeError(
        f"未找到目标合集：{item.collection_name}。当前规则只使用已创建的 3 个合集（{fixed}），"
        f"不会自动新建合集。页面已读取合集：{available}"
    )


def declare_original(page, actions) -> None:
    human_scroll_down(page, actions, 600)

    sleep(3)
    last_error: Exception | None = None

    def click_first(candidates: tuple[tuple[str, int], ...], label: str, timeout: float = 3) -> bool:
        nonlocal last_error
        for selector, index in candidates:
            try:
                element = page.ele(selector, index=index, timeout=timeout)
                actions.move_to(ele_or_loc=element).click()
                print(f"已点击{label}：{selector}")
                last_error = None
                return True
            except Exception as exc:
                last_error = exc
        return False

    switch_clicked = click_first(
        (
            (".d-switch-indicator", 1),
            (".d-switch-box", 1),
            ("text=声明原创", 1),
            ("tx=声明原创", 1),
        ),
        "声明原创开关",
        timeout=5,
    )
    if not switch_clicked:
        raise RuntimeError("声明原创点击失败。") from last_error

    sleep(1)
    click_first(
        (
            (".d-checkbox-indicator", 1),
            (".:d-checkbox-indicator", 1),
            ("text=我已阅读并同意", 1),
            ("tx=我已阅读并同意", 1),
        ),
        "原创声明协议勾选框",
        timeout=2,
    )
    click_first(
        (
            ("tx= 声明原创 ", 1),
            ("tx=声明原创", 1),
            ("text=声明原创", 1),
            ("text=确定", 1),
            ("tx=确定", 1),
        ),
        "原创声明确认按钮",
        timeout=2,
    )

    human_scroll_down(page, actions, 300)


def set_schedule_time(page, actions, schedule_time: str) -> None:
    from DrissionPage.common import Keys

    scroll_down(page, actions, 700)

    last_error: Exception | None = None
    for selector in (".custom-switch-switch", ".d-switch-box", "text=定时发布"):
        try:
            switch = page.ele(selector, index=-1, timeout=4)
            try:
                switch = switch.ele(".d-switch-box", timeout=1)
            except Exception:
                pass
            actions.move_to(ele_or_loc=switch).click()
            last_error = None
            break
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise RuntimeError("找不到定时发布开关。") from last_error

    sleep(3)

    input_selectors = (
        ".d-datepicker-suffix --color-text-description d-datepicker-suffix-indicator",
        ".d-datepicker input",
        "@placeholder=请选择时间",
        "@placeholder:请选择时间",
    )
    last_error = None
    for selector in input_selectors:
        try:
            date_input = page.ele(selector, timeout=4)
            actions.move_to(ele_or_loc=date_input).click()
            actions.key_down(Keys.SHIFT)
            for _ in range(24):
                actions.key_down(Keys.LEFT).key_up(Keys.LEFT)
                sleep(0.03)
            actions.key_up(Keys.SHIFT)
            date_input.input(schedule_time)
            sleep(1)
            return
        except Exception as exc:
            last_error = exc
            try:
                actions.key_up(Keys.SHIFT)
            except Exception:
                pass
    raise RuntimeError("找不到定时时间输入框。") from last_error


def first_existing_element(page, selectors: tuple[str, ...], field_name: str):
    last_error: Exception | None = None
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=5)
            if getattr(ele, "_type", "") == "ChromiumElement":
                return ele
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"找不到{field_name}。") from last_error


def find_button_by_text(page, text: str):
    for selector in ("@class:bg-red", "tag:button"):
        try:
            for ele in page.eles(selector, timeout=2):
                if text in str(getattr(ele, "text", "")) and element_has_size(ele):
                    return ele
        except Exception:
            continue
    return None


def find_publish_button_in_shadow(page, text: str):
    for host_selector in ("t:xhs-publish-btn", "tag:xhs-publish-btn"):
        try:
            host = page.ele(host_selector, timeout=5)
            shadow_root = host.sr
            if not shadow_root:
                continue
            for selector in (".ce-btn bg-red", "tx=" + text, "text=" + text):
                try:
                    button = shadow_root.ele(selector, timeout=3)
                    button_text = str(getattr(button, "text", ""))
                    if (not text or text in button_text) and element_has_size(button):
                        return button
                except Exception:
                    continue
        except Exception:
            continue
    return None


def click_submit(page, actions, schedule_time: str | None = None) -> None:
    if schedule_time:
        page.wait(2, 3)
        button = (
            find_publish_button_in_shadow(page, "定时发布")
            or find_button_by_text(page, "定时发布")
            or first_existing_element(
                page,
                (".:publishBtn", "tx=定时发布", "text=定时发布"),
                "定时发布按钮",
            )
        )
        actions.move_to(ele_or_loc=button).click()
        print(f"已点击定时发布：{schedule_time}")
        return

    button = (
        find_publish_button_in_shadow(page, "发布")
        or find_button_by_text(page, "发布")
        or first_existing_element(
            page,
            (".:publishBtn", "tx=发布", "text=发布", "tx=立即发布", "text=立即发布"),
            "发布按钮",
        )
    )
    actions.move_to(ele_or_loc=button).click()
    print("已点击发布按钮。")


def check_publish_success(page) -> bool:
    for _ in range(10):
        if "published=true" in str(page.url):
            print("发布后页面 URL 包含 published=true。")
            return True
        for selector in ("text=发布成功", "text=定时发布成功"):
            try:
                print(page.ele(selector, timeout=1).text)
                return True
            except Exception:
                continue
        page.wait(1)
    return False


def publish_one_item(page, actions, item: PublishItem, submit: bool = True) -> bool:
    issues = validate_item(item)
    if issues:
        raise ValueError(f"{item.topic_folder} 校验失败：" + "；".join(issues))

    print(f"开始处理：{item.topic_folder} -> {item.schedule_time or '立即发布'}")
    open_image_publish_page(page, actions)
    upload_images(page, item.images)

    fill_field(page, ("@placeholder:填写标题", "@placeholder=填写标题会有更多赞哦～"), item.title, "标题")
    body_field = fill_field(
        page,
        ("@data-placeholder:输入正文描述", "@data-placeholder=输入正文描述，真诚有价值的分享予人温暖"),
        item.body,
        "正文",
    )
    body_field.input("\n")
    move_body_cursor_after_input(actions)
    sleep(1)

    input_preselected_topic_tags(body_field, item.topic_tags)
    declare_original(page, actions)
    select_or_create_collection(page, actions, item)
    if item.schedule_time:
        set_schedule_time(page, actions, item.schedule_time)

    if submit:
        click_submit(page, actions, item.schedule_time)
        page.wait(2, 3)
        return check_publish_success(page)
    elif item.schedule_time:
        print(f"DRY RUN：已填充并设置定时时间，但未点击发布：{item.schedule_time}")
    else:
        print("DRY RUN：已填充页面，但未点击发布。")

    page.wait(2, 3)
    return False


def run_batch_publish(config: PublishConfig) -> list[PublishItem]:
    publish_queue = load_publish_queue(config)
    print_publish_queue(publish_queue)
    validate_queue_or_raise(publish_queue)

    processed_items: list[PublishItem] = []
    initial_manifest_count = len(discover_manifests(config))
    skipped_count = max(0, initial_manifest_count - len(publish_queue))

    if not publish_queue:
        print("没有新的待发布素材；已根据发布历史全部跳过。")
        send_publish_completion_email(processed_items, config, skipped_count=skipped_count)
        return processed_items

    page, actions = connect_browser(config.chromium_port)
    try:
        for item in publish_queue:
            publish_success = publish_one_item(page, actions, item, submit=config.submit)
            if config.submit:
                if not publish_success:
                    raise RuntimeError(f"{item.topic_folder} 未检测到发布成功提示。")
                append_publish_history(item, config, status="success", message="检测到发布成功")
                print(f"已记录发布历史：{item.topic_folder} -> {config.history_xlsx}")
            else:
                print(f"DRY RUN：不写入发布历史：{item.topic_folder}")
            processed_items.append(item)
        print("全部素材处理完成。")
        send_publish_completion_email(processed_items, config, skipped_count=skipped_count)
        return processed_items
    except Exception as exc:
        notify_failure(
            "定时发布流程失败",
            error=exc,
            details=f"已成功记录 {len(processed_items)} 篇；剩余 {len(publish_queue) - len(processed_items)} 篇未完成。",
            attachments=[path for path in (config.history_xlsx, config.history_csv) if path.exists()],
            dedupe_key=f"publish-flow|{type(exc).__name__}|{datetime.now():%Y%m%d%H}",
        )
        raise


def run_single_manifest(
    manifest_path: Path,
    config: PublishConfig,
    *,
    fill: bool = False,
    submit: bool = False,
    schedule_time: str | None = None,
) -> PublishItem:
    manifest = load_manifest(manifest_path)
    try:
        item = build_publish_item(
            manifest_path,
            manifest,
            config,
            schedule_time=validate_schedule_time(schedule_time) if schedule_time else None,
        )
    except ValueError as exc:
        print(f"发布校验未通过：{exc}")
        raise SystemExit(1) from exc
    issues = validate_item(item)
    if issues:
        print("发布校验未通过：")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("发布校验通过。")
    print(f"标题：{item.title}")
    print(f"图片数：{len(item.images)}")
    print("话题：", "、".join(item.topic_tags))
    print("合集：", item.collection_name)
    if item.schedule_time:
        print(f"定时时间：{item.schedule_time}")

    if not fill and not submit:
        print("仅完成 manifest 校验，未打开浏览器。")
        return item

    try:
        page, actions = connect_browser(config.chromium_port)
        publish_success = publish_one_item(page, actions, item, submit=submit)
        if submit and not publish_success:
            raise RuntimeError(f"{item.topic_folder} 未检测到发布成功提示。")
    except Exception as exc:
        notify_failure("发布脚本失败", error=exc, details=f"manifest: {manifest_path}")
        raise
    return item


def parse_slots(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_DAILY_TIME_SLOTS
    return tuple(slot.strip() for slot in raw.split(",") if slot.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run notebook-derived XHS batch publisher.")
    parser.add_argument("--materials-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--materials-dir", type=Path, default=None)
    parser.add_argument("--port", type=int, default=9209)
    parser.add_argument("--submit", action="store_true", default=True, help="点击定时发布，默认与 Notebook 一致为 True。")
    parser.add_argument("--dry-run", action="store_true", help="只填充和设置定时时间，不点击发布、不写历史。")
    parser.add_argument("--slots", help="逗号分隔的每日发布时间，例如 12:00,16:00。")
    parser.add_argument("--topic-order", help="逗号分隔的素材文件夹排序；留空则使用 Notebook 默认顺序。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    topic_order = DEFAULT_TOPIC_ORDER
    if args.topic_order is not None:
        topic_order = [item.strip() for item in args.topic_order.split(",") if item.strip()]

    config = PublishConfig(
        materials_date=args.materials_date,
        materials_dir=args.materials_dir,
        chromium_port=args.port,
        submit=False if args.dry_run else args.submit,
        daily_time_slots=parse_slots(args.slots),
        topic_order=topic_order,
    )

    print("素材目录：", config.resolved_materials_dir)
    print("浏览器端口：", config.chromium_port)
    print("是否点击定时发布：", config.submit)
    print("发布历史表：", config.history_xlsx)
    run_batch_publish(config)


if __name__ == "__main__":
    main()
