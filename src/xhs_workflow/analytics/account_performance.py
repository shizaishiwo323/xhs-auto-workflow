# -*- coding: utf-8 -*-
"""Own-account metrics and feedback loop for XHS material generation.

The browser fetcher is a thin, parameterized wrapper around the successful
notebook baseline at ``archive/备份/xhs媒体下载/获取账号数据.ipynb``.  The notebook
is intentionally left untouched.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
NOTE_MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager"
ACCOUNT_COLUMNS = ["笔记标题", "日期", "浏览量", "评论量", "点赞量", "收藏量", "转发量", "add_time"]
DEFAULT_HISTORY_PATH = ROOT / "outputs" / "publish_history" / "published_history.jsonl"


@dataclass
class AccountMetricsFetchConfig:
    chromium_port: int = 9209
    note_manager_url: str = NOTE_MANAGER_URL
    scroll_batches: int = 5
    scroll_delta: int = 2000
    scroll_wait_seconds: float = 3.0
    wait_after_open_seconds: float = 2.0
    output_path: Path | None = None

    @property
    def resolved_output_path(self) -> Path:
        if self.output_path:
            return self.output_path
        now = datetime.now()
        return (
            ROOT
            / "outputs"
            / "account_metrics"
            / now.strftime("%Y-%m-%d")
            / f"小红书笔记数据分析_{now.strftime('%H%M%S')}.xlsx"
        )


@dataclass
class PerformanceAnalysisConfig:
    account_metrics_paths: list[Path] = field(default_factory=list)
    materials_root: Path = ROOT / "outputs" / "materials"
    publish_history_path: Path | None = DEFAULT_HISTORY_PATH
    output_dir: Path | None = None

    @property
    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return self.output_dir
        return ROOT / "outputs" / "account_performance" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def parse_metric(value: Any) -> int:
    """Normalize interaction strings such as ``1.7万`` or ``2k`` to integers."""
    if value is None:
        return 0
    try:
        if pd.isna(value):
            return 0
    except Exception:
        pass
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text.lower() in {"nan", "none", "null", "-", "--"}:
        return 0

    multiplier = 1
    lowered = text.lower()
    if "亿" in text:
        multiplier = 100000000
    elif "万" in text or "w" in lowered:
        multiplier = 10000
    elif "千" in text or "k" in lowered:
        multiplier = 1000

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return int(float(match.group()) * multiplier)


def title_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def safe_read_table(path: Path) -> pd.DataFrame:
    path = Path(path).expanduser()
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return pd.DataFrame(records)
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return pd.DataFrame(data)
        if isinstance(data, dict):
            return pd.DataFrame(data.get("records") or data.get("items") or [data])
    raise ValueError(f"不支持的表格格式：{path}")


def fetch_account_metrics(config: AccountMetricsFetchConfig | None = None) -> pd.DataFrame:
    """Fetch own-account note metrics from XHS creator note manager."""
    config = config or AccountMetricsFetchConfig()

    from DrissionPage import ChromiumOptions, ChromiumPage
    from DrissionPage.common import Actions

    co = ChromiumOptions().set_paths(local_port=config.chromium_port).mute(True).set_argument("--start-maximized")
    page = ChromiumPage(co)
    page.set.auto_handle_alert()
    page.set.when_download_file_exists("overwrite")
    page.get(config.note_manager_url)
    sleep(config.wait_after_open_seconds)

    actions = Actions(page)
    for _ in range(max(0, config.scroll_batches)):
        try:
            width, height = page.run_js("return [window.innerWidth, window.innerHeight];")
            actions.move_to((width // 2, height // 2))
            actions.scroll(delta_y=config.scroll_delta)
            sleep(config.scroll_wait_seconds)
        except Exception:
            break

    cards = _note_cards(page)
    rows: list[list[Any]] = []
    for card in cards:
        rows.append(
            [
                _safe_ele_text(card, ".title", " "),
                _safe_ele_text(card, ".time", " "),
                _safe_icon_text(card, 1),
                _safe_icon_text(card, 2),
                _safe_icon_text(card, 3),
                _safe_icon_text(card, 4),
                _safe_icon_text(card, 5),
                datetime.now().strftime("%Y-%m-%d %H-%M-%S"),
            ]
        )

    df = pd.DataFrame(rows, columns=ACCOUNT_COLUMNS)
    df["笔记标题"] = df["笔记标题"].astype(str).str.strip().replace("", pd.NA)
    df.dropna(subset=["笔记标题"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    output_path = config.resolved_output_path
    config.output_path = output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, engine="openpyxl")
    return df


def _note_cards(page) -> list[Any]:
    try:
        return list(page.ele(".d-tabs-pane").s_ele().child("t:div").children("t:div"))
    except Exception:
        pass
    try:
        return list(page.eles(".note-item"))
    except Exception:
        return []


def _safe_ele_text(ele, selector: str, default: str = "") -> str:
    try:
        return ele.ele(selector).text.strip()
    except Exception:
        return default


def _safe_icon_text(ele, index: int, default: str = " ") -> str:
    try:
        return ele.ele(".icon_list").child("t:div", index=index).text.strip()
    except Exception:
        return default


def discover_latest_account_metrics(root: Path = ROOT) -> list[Path]:
    candidates = sorted((root / "outputs" / "account_metrics").glob("**/*.xlsx"))
    fallback = root / "小红书笔记数据分析.xlsx"
    if fallback.exists():
        candidates.append(fallback)
    backup = root / "archive" / "备份" / "xhs媒体下载" / "小红书笔记数据分析.xlsx"
    if backup.exists():
        candidates.append(backup)
    return candidates[-1:] if candidates else []


def normalize_account_metrics(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "title": ["笔记标题", "标题", "note_title", "title"],
        "publish_time_text": ["日期", "发布时间", "publish_time", "publish_time_text"],
        "views": ["浏览量", "阅读量", "观看量", "曝光量", "views"],
        "comments": ["评论量", "评论", "comments"],
        "likes": ["点赞量", "点赞", "likes"],
        "saves": ["收藏量", "收藏", "saves"],
        "shares": ["转发量", "转发", "shares"],
        "collected_at": ["add_time", "采集时间", "recorded_at"],
    }
    out = pd.DataFrame()
    for target, names in aliases.items():
        source = next((name for name in names if name in df.columns), None)
        out[target] = df[source] if source else ""

    out["title"] = out["title"].fillna("").astype(str).str.strip()
    out = out[out["title"].ne("")].copy()
    for col in ["views", "comments", "likes", "saves", "shares"]:
        out[col] = out[col].apply(parse_metric)
    out["title_key"] = out["title"].apply(title_key)
    out["collected_at"] = out["collected_at"].fillna("").astype(str)
    out.drop_duplicates(subset=["title_key", "collected_at"], keep="last", inplace=True)
    out.reset_index(drop=True, inplace=True)
    return out


def load_account_metrics(paths: list[Path]) -> pd.DataFrame:
    frames = [normalize_account_metrics(safe_read_table(path)) for path in paths]
    if not frames:
        return pd.DataFrame(columns=["title", "title_key", "views", "likes", "saves", "comments", "shares"])
    df = pd.concat(frames, ignore_index=True)
    df.sort_values(["title_key", "collected_at"], inplace=True)
    df.drop_duplicates(subset=["title_key"], keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def load_publish_history(path: Path | None) -> pd.DataFrame:
    if not path or not Path(path).exists():
        return pd.DataFrame()
    df = safe_read_table(Path(path))
    if "title" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["title_key"] = df["title"].apply(title_key)
    wanted = [
        col
        for col in ["title_key", "recorded_at", "status", "topic_folder", "schedule_time", "manifest_path", "image_count"]
        if col in df.columns
    ]
    df = df[wanted].copy()
    df.drop_duplicates(subset=["title_key"], keep="last", inplace=True)
    return df


def discover_material_records(materials_root: Path) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    if not materials_root.exists():
        return pd.DataFrame(records)

    for manifest_path in sorted(materials_root.rglob("00_自动发推适配/publish_manifest.json")):
        try:
            manifest = _read_json(manifest_path)
        except Exception:
            continue
        package_dir = manifest_path.parents[1]
        title = str(manifest.get("recommended_title") or manifest.get("title") or "").strip()
        row = manifest.get("publish_row") or {}
        if not title:
            title = str(row.get("标题") or "").strip()
        body = str(manifest.get("body") or row.get("推文") or "").strip()
        topics = manifest.get("topics") or manifest.get("tags") or []
        if not isinstance(topics, list):
            topics = [str(topics)]
        image_paths = _manifest_image_paths(manifest, manifest_path)
        image_summary = summarize_images(image_paths)
        records.append(
            {
                "title": title,
                "title_key": title_key(title),
                "body": body,
                "body_chars": len(body),
                "topics": topics,
                "topic_folder": package_dir.name,
                "materials_date": package_dir.parent.name,
                "manifest_path": str(manifest_path),
                "package_dir": str(package_dir),
                "reference_matrix_path": str(manifest.get("reference_matrix_path") or ""),
                "image_count": len(image_paths),
                "cover_path": str(image_paths[0]) if image_paths else "",
                "title_hook": classify_title_hook(title),
                "content_tags": extract_content_tags(title, body, topics),
                "body_structure": classify_body_structure(body),
                "image_quality": image_summary,
            }
        )

    return pd.DataFrame(records)


def summarize_images(paths: list[Path]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "count": len(paths),
        "missing": 0,
        "too_small": 0,
        "wide_composite": 0,
        "vertical_count": 0,
        "cover_width": None,
        "cover_height": None,
        "cover_label": "无图片",
    }
    if not paths:
        return summary

    try:
        from PIL import Image
    except Exception:
        existing = [path for path in paths if path.exists()]
        summary["missing"] = len(paths) - len(existing)
        summary["cover_label"] = "已找到图片，未检查尺寸" if existing else "图片缺失"
        return summary

    for index, path in enumerate(paths):
        if not path.exists():
            summary["missing"] += 1
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            summary["missing"] += 1
            continue
        ratio = width / max(height, 1)
        if height >= width:
            summary["vertical_count"] += 1
        if width < 720 or height < 960:
            summary["too_small"] += 1
        if ratio > 1.25:
            summary["wide_composite"] += 1
        if index == 0:
            summary["cover_width"] = width
            summary["cover_height"] = height

    if summary["missing"]:
        summary["cover_label"] = "需补图或修正路径"
    elif summary["too_small"] or summary["wide_composite"]:
        summary["cover_label"] = "需复查清晰度/拼版"
    elif summary["cover_width"] and summary["cover_height"] and summary["cover_height"] >= summary["cover_width"]:
        summary["cover_label"] = "竖图清晰"
    else:
        summary["cover_label"] = "需复查封面比例"
    return summary


def analyze_account_performance(config: PerformanceAnalysisConfig | None = None) -> dict[str, Any]:
    config = config or PerformanceAnalysisConfig()
    metrics_paths = config.account_metrics_paths or discover_latest_account_metrics(ROOT)
    if not metrics_paths:
        raise FileNotFoundError("未找到账号笔记数据 Excel，请先运行 fetch_account_metrics 或传入 --account-metrics。")

    account_df = load_account_metrics(metrics_paths)
    materials_df = discover_material_records(config.materials_root)
    history_df = load_publish_history(config.publish_history_path)

    merged = account_df.copy()
    if not materials_df.empty:
        material_cols = [
            "title_key",
            "body_chars",
            "topics",
            "topic_folder",
            "materials_date",
            "manifest_path",
            "package_dir",
            "reference_matrix_path",
            "image_count",
            "cover_path",
            "title_hook",
            "content_tags",
            "body_structure",
            "image_quality",
        ]
        merged = merged.merge(materials_df[material_cols], on="title_key", how="left")
    if not history_df.empty:
        merged = merged.merge(history_df, on="title_key", how="left", suffixes=("", "_history"))

    merged = enrich_missing_material_features(merged)
    merged = add_scores(merged)
    result = build_feedback_result(merged, [str(path) for path in metrics_paths], config)
    output_dir = config.resolved_output_dir
    config.output_dir = output_dir
    write_feedback_outputs(result, merged, output_dir)
    return result


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["views", "likes", "saves", "comments", "shares"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0).astype(int)

    views = df["views"].astype(float).where(df["views"].astype(float) > 0)
    df["like_rate"] = (df["likes"].astype(float) / views).fillna(0.0).astype(float)
    df["save_rate"] = (df["saves"].astype(float) / views).fillna(0.0).astype(float)
    df["comment_rate"] = (df["comments"].astype(float) / views).fillna(0.0).astype(float)
    df["share_rate"] = (df["shares"].astype(float) / views).fillna(0.0).astype(float)
    df["weighted_engagement"] = df["likes"] + df["saves"] * 2 + df["comments"] * 3 + df["shares"] * 2

    if len(df) >= 2:
        df["score"] = (
            df["views"].rank(pct=True) * 0.35
            + df["weighted_engagement"].rank(pct=True) * 0.35
            + df["save_rate"].rank(pct=True) * 0.20
            + df["comment_rate"].rank(pct=True) * 0.10
        )
    else:
        df["score"] = 0.5

    if len(df) >= 4:
        high = float(df["score"].quantile(0.75))
        low = float(df["score"].quantile(0.25))
    else:
        high = float(df["score"].max())
        low = float(df["score"].min())

    def tier(score: float) -> str:
        if len(df) == 1:
            return "观察"
        if score >= high:
            return "加固"
        if score <= low:
            return "避免/重做"
        return "观察"

    df["tier"] = df["score"].apply(tier)
    return df


def enrich_missing_material_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "body" not in df.columns:
        df["body"] = ""
    if "topics" not in df.columns:
        df["topics"] = [[] for _ in range(len(df))]
    if "title_hook" not in df.columns:
        df["title_hook"] = ""
    if "content_tags" not in df.columns:
        df["content_tags"] = [[] for _ in range(len(df))]
    if "body_structure" not in df.columns:
        df["body_structure"] = ""
    if "body_chars" not in df.columns:
        df["body_chars"] = 0
    if "image_count" not in df.columns:
        df["image_count"] = 0
    if "image_quality" not in df.columns:
        df["image_quality"] = [{} for _ in range(len(df))]

    def fill_row(row: pd.Series) -> pd.Series:
        title = _safe_text(row.get("title"))
        body = _safe_text(row.get("body"))
        topics = row.get("topics") if isinstance(row.get("topics"), list) else []
        hook = _safe_text(row.get("title_hook"))
        if not hook:
            row["title_hook"] = classify_title_hook(title)
        tags = row.get("content_tags")
        if not isinstance(tags, list) or not tags:
            row["content_tags"] = extract_content_tags(title, body, topics)
        if not _safe_text(row.get("body_structure")):
            row["body_structure"] = classify_body_structure(body)
        if _safe_int(row.get("body_chars")) == 0 and body:
            row["body_chars"] = len(body)
        if not isinstance(row.get("image_quality"), dict):
            row["image_quality"] = {}
        row["image_count"] = _safe_int(row.get("image_count"))
        return row

    return df.apply(fill_row, axis=1)


def build_feedback_result(df: pd.DataFrame, metrics_paths: list[str], config: PerformanceAnalysisConfig) -> dict[str, Any]:
    df = df.sort_values(["score", "views"], ascending=False).reset_index(drop=True)
    medians = {
        "views": float(df["views"].median()) if not df.empty else 0.0,
        "save_rate": float(df["save_rate"].median()) if not df.empty else 0.0,
        "like_rate": float(df["like_rate"].median()) if not df.empty else 0.0,
        "comment_rate": float(df["comment_rate"].median()) if not df.empty else 0.0,
    }
    top_rows = [row_to_feedback(row, medians, positive=True) for _, row in df[df["tier"].eq("加固")].head(8).iterrows()]
    weak_rows = [
        row_to_feedback(row, medians, positive=False)
        for _, row in df[df["tier"].eq("避免/重做")].sort_values(["score", "views"], ascending=True).head(8).iterrows()
    ]

    group_insights = build_group_insights(df)
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_metrics_paths": metrics_paths,
        "materials_root": str(config.materials_root),
        "publish_history_path": str(config.publish_history_path or ""),
        "note_count": int(len(df)),
        "matched_material_count": int(
            df.get("manifest_path", pd.Series(dtype=str)).fillna("").astype(str).str.len().gt(0).sum()
        )
        if not df.empty
        else 0,
        "median_metrics": medians,
        "reinforce": top_rows,
        "avoid_or_rework": weak_rows,
        "group_insights": group_insights,
        "next_generation_rules": build_next_generation_rules(top_rows, weak_rows, group_insights),
    }
    return _json_clean(result)


def row_to_feedback(row: pd.Series, medians: dict[str, float], positive: bool) -> dict[str, Any]:
    title = _safe_text(row.get("title"))
    image_quality = row.get("image_quality")
    if not isinstance(image_quality, dict):
        image_quality = {}
    content_tags = row.get("content_tags")
    if not isinstance(content_tags, list):
        content_tags = []
    base = {
        "title": title,
        "views": _safe_int(row.get("views")),
        "likes": _safe_int(row.get("likes")),
        "saves": _safe_int(row.get("saves")),
        "comments": _safe_int(row.get("comments")),
        "shares": _safe_int(row.get("shares")),
        "score": round(_safe_float(row.get("score")), 4),
        "save_rate": round(_safe_float(row.get("save_rate")), 4),
        "like_rate": round(_safe_float(row.get("like_rate")), 4),
        "title_hook": _safe_text(row.get("title_hook"), "未识别"),
        "content_tags": content_tags,
        "image_count": _safe_int(row.get("image_count")),
        "cover_label": image_quality.get("cover_label") or "",
        "topic_folder": _safe_text(row.get("topic_folder")),
        "manifest_path": _safe_text(row.get("manifest_path")),
    }
    base["why"] = reinforce_reason(row) if positive else weak_reason(row, medians)
    return base


def reinforce_reason(row: pd.Series) -> list[str]:
    reasons = []
    hook = _safe_text(row.get("title_hook"), "标题钩子")
    tags = row.get("content_tags") if isinstance(row.get("content_tags"), list) else []
    if _safe_int(row.get("views")) > 0:
        reasons.append("浏览能进来，封面/标题入口至少有效，下一次保留首屏强结论。")
    if _safe_float(row.get("save_rate")) > 0:
        reasons.append("收藏率有信号，继续做清单、流程、字段、交付物这种可保存内容。")
    if hook:
        reasons.append(f"继续复用 `{hook}` 的标题逻辑，但替换场景和数字，避免复读同一句。")
    tags = [tag for tag in tags if tag != "未识别"]
    if tags:
        reasons.append("加固内容方向：" + "、".join(tags[:4]) + "。")
    return reasons or ["作为高分样本保留结构，后续只做场景和表达二创。"]


def weak_reason(row: pd.Series, medians: dict[str, float]) -> list[str]:
    reasons = []
    image_quality = row.get("image_quality") if isinstance(row.get("image_quality"), dict) else {}
    views = _safe_int(row.get("views"))
    if views < medians["views"]:
        reasons.append("浏览低于中位数，优先怀疑封面首屏、标题具体度或选题人群不清。")
    if views > 0 and _safe_float(row.get("save_rate")) < medians["save_rate"]:
        reasons.append("收藏率偏低，内容可能缺少可复用表格、步骤、模板或明确交付物。")
    if views > 0 and _safe_float(row.get("like_rate")) < medians["like_rate"]:
        reasons.append("点赞率偏低，开头情绪/痛点不够具体，正文需要更像真实复盘。")
    if image_quality.get("too_small") or image_quality.get("wide_composite") or image_quality.get("missing"):
        reasons.append("图片质量或比例有风险，先保证封面竖图、清晰、主体明确，再谈内容。")
    body_chars = _safe_int(row.get("body_chars"))
    if body_chars and body_chars < 220:
        reasons.append("正文偏短，知识/工具类内容容易显得不够值，补上步骤、坑点和结果。")
    if body_chars > 700:
        reasons.append("正文偏长，压缩成滑读结构，把关键步骤交给轮播图承接。")
    return reasons or ["低分样本先不要照搬，下一次换封面钩子、选题角度和内容密度后再测。"]


def build_group_insights(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    group_defs = [
        ("title_hook", "标题钩子"),
        ("image_bucket", "图片数量"),
        ("content_primary", "内容方向"),
    ]
    enriched = df.copy()
    if "image_count" not in enriched.columns:
        enriched["image_count"] = 0
    if "content_tags" not in enriched.columns:
        enriched["content_tags"] = [[] for _ in range(len(enriched))]
    enriched["image_bucket"] = enriched["image_count"].apply(bucket_image_count)
    enriched["content_primary"] = enriched["content_tags"].apply(
        lambda tags: tags[0] if isinstance(tags, list) and tags else "未识别"
    )

    for column, label in group_defs:
        for value, group in enriched.groupby(column, dropna=False):
            if not value or str(value) == "nan":
                continue
            rows.append(
                {
                    "dimension": label,
                    "value": str(value),
                    "count": int(len(group)),
                    "avg_score": round(float(group["score"].mean()), 4),
                    "avg_views": round(float(group["views"].mean()), 2),
                    "avg_save_rate": round(float(group["save_rate"].mean()), 4),
                    "examples": group.sort_values("score", ascending=False)["title"].head(3).tolist(),
                }
            )
    rows.sort(key=lambda item: (item["avg_score"], item["count"]), reverse=True)
    return rows[:12]


def build_next_generation_rules(
    reinforce: list[dict[str, Any]],
    avoid_or_rework: list[dict[str, Any]],
    group_insights: list[dict[str, Any]],
) -> dict[str, list[str]]:
    good_hooks = _unique([item.get("title_hook", "") for item in reinforce if item.get("title_hook")])
    good_tags = _unique(tag for item in reinforce for tag in item.get("content_tags", []) if tag != "未识别")
    weak_titles = [item.get("title", "") for item in avoid_or_rework if item.get("title")]
    top_groups = [item for item in group_insights if item["count"] >= 1][:4]

    keep = []
    if good_hooks:
        keep.append("优先沿用高分标题钩子：" + "、".join(good_hooks[:4]) + "。")
    if good_tags:
        keep.append("优先生成这些已验证内容方向：" + "、".join(good_tags[:6]) + "。")
    if top_groups:
        keep.append("生成前复查高分分组：" + "；".join(f"{g['dimension']}={g['value']}" for g in top_groups) + "。")
    keep.append("封面必须一眼说明结果/避坑/清单价值，轮播继续承接字段、步骤、表格和交付物。")

    avoid = []
    if weak_titles:
        avoid.append("这些标题对应的方向暂不复刻：" + "、".join(weak_titles[:5]) + "。")
    avoid.append("低浏览样本不要只改正文，先重做封面首屏和标题具体度。")
    avoid.append("高浏览低收藏样本不要继续铺情绪，改成清单、模板、流程、对照表。")
    avoid.append("图片缺失、过小、横向拼版或主体不清时，不进入发布适配。")

    return {"keep": keep, "avoid": avoid}


def write_feedback_outputs(result: dict[str, Any], merged: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "account_performance_feedback.json"
    md_path = output_dir / "account_performance_report.md"
    xlsx_path = output_dir / "account_metrics_enriched.xlsx"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    md_path.write_text(render_markdown_report(result), encoding="utf-8")
    merged.to_excel(xlsx_path, index=False, engine="openpyxl")

    latest_dir = ROOT / "outputs" / "account_performance"
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_json = latest_dir / "latest_optimization.json"
    latest_md = latest_dir / "latest_optimization.md"
    with latest_json.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    latest_md.write_text(render_markdown_report(result), encoding="utf-8")


def render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# 小红书账号数据复盘",
        "",
        f"生成时间：{result.get('generated_at', '')}",
        f"账号笔记数：{result.get('note_count', 0)}",
        f"匹配到历史素材包：{result.get('matched_material_count', 0)}",
        "",
        "## 下次生成要加固",
    ]
    for item in result.get("reinforce", []):
        lines.append(f"- {item['title']}：{item['views']}浏览 / {item['likes']}赞 / {item['saves']}藏")
        for reason in item.get("why", []):
            lines.append(f"  - {reason}")
    if not result.get("reinforce"):
        lines.append("- 暂无明显高分样本，先继续积累账号数据。")

    lines.extend(["", "## 下次不要照做"])
    for item in result.get("avoid_or_rework", []):
        lines.append(f"- {item['title']}：{item['views']}浏览 / {item['likes']}赞 / {item['saves']}藏")
        for reason in item.get("why", []):
            lines.append(f"  - {reason}")
    if not result.get("avoid_or_rework"):
        lines.append("- 暂无明显低分样本。")

    rules = result.get("next_generation_rules", {})
    lines.extend(["", "## 生成规则更新", "", "### 保留"])
    for rule in rules.get("keep", []):
        lines.append(f"- {rule}")
    lines.extend(["", "### 避免"])
    for rule in rules.get("avoid", []):
        lines.append(f"- {rule}")

    lines.extend(["", "## 高信号分组"])
    for item in result.get("group_insights", [])[:8]:
        lines.append(
            f"- {item['dimension']}={item['value']}：样本{item['count']}，"
            f"平均分{item['avg_score']}，平均浏览{item['avg_views']}，例子："
            + "、".join(item.get("examples", []))
        )
    return "\n".join(lines) + "\n"


def classify_title_hook(title: str) -> str:
    text = str(title or "")
    if re.search(r"\d|一|二|三|四|五|六|七|八|九|十|0到", text):
        return "数字/步骤钩子"
    if any(word in text for word in ["别", "乱", "坑", "避坑"]):
        return "避坑纠错钩子"
    if any(word in text for word in ["怎么", "如何", "为什么"]):
        return "问题解决钩子"
    if "先" in text:
        return "顺序提醒钩子"
    if "AI" in text.upper():
        return "AI工具钩子"
    if len(text) <= 10:
        return "短强结论钩子"
    return "常规说明钩子"


def extract_content_tags(title: str, body: str, topics: list[Any]) -> list[str]:
    text = " ".join([str(title or ""), str(body or ""), " ".join(map(str, topics or []))])
    mapping = {
        "公开数据": ["公开数据", "公开来源", "数据源"],
        "论文/大作业": ["论文", "大作业", "作业", "科研"],
        "流程清单": ["流程", "步骤", "清单", "怎么做"],
        "字段/表格": ["字段", "表格", "excel", "Excel"],
        "留痕复核": ["留痕", "复核", "记录", "交付物"],
        "评论/文本分析": ["评论", "文本分析", "词频", "情感"],
        "政策数据": ["政策", "政府", "统计"],
        "AI工具": ["AI", "智能体", "助手", "Codex", "Claude"],
        "入门方法": ["入门", "先别", "基础"],
    }
    tags = [label for label, keywords in mapping.items() if any(keyword in text for keyword in keywords)]
    return tags


def classify_body_structure(body: str) -> str:
    text = str(body or "")
    has_steps = bool(re.search(r"(^|\n)\s*\d+[.、]", text))
    has_question_end = "？" in text[-100:] or "?" in text[-100:]
    if has_steps and has_question_end:
        return "步骤清单+评论提问"
    if has_steps:
        return "步骤清单"
    if has_question_end:
        return "问题引导"
    if len(text) < 220:
        return "短正文"
    return "叙述复盘"


def bucket_image_count(value: Any) -> str:
    count = _safe_int(value)
    if count <= 1:
        return "单图/缺轮播"
    if count <= 4:
        return "轻轮播"
    if count <= 7:
        return "标准轮播"
    return "长轮播"


def _manifest_image_paths(manifest: dict[str, Any], manifest_path: Path) -> list[Path]:
    package_dir = manifest_path.parents[1]
    items = sorted(manifest.get("images", []), key=lambda item: item.get("upload_order", 999))
    paths: list[Path] = []
    for item in items:
        raw = str(item.get("path") or "")
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = package_dir / path
        paths.append(path)
    return paths


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return data


def _unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _safe_int(value: Any) -> int:
    try:
        if value is None or pd.isna(value):
            return 0
    except Exception:
        pass
    try:
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return 0.0
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_text(value: Any, default: str = "") -> str:
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_clean(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value
