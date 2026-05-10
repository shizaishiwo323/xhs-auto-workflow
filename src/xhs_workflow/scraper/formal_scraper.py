# -*- coding: utf-8 -*-
"""Notebook-derived formal Xiaohongshu scraper.

This module is a parameterized Python version of
``notebooks/scraper/xhs_scraper_formal.ipynb``.  The scraping order,
selectors, output files, and media handling intentionally follow the
successful notebook baseline, with only a thin callable wrapper around it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import pandas as pd
from tqdm import tqdm

try:
    from xhs_notify import notify_failure, notify_failure_once, send_email
except Exception:
    try:
        from xhs_workflow.notify import notify_failure, notify_failure_once, send_email
    except Exception:
        def notify_failure(*args, **kwargs):
            return False

        def notify_failure_once(*args, **kwargs):
            return False

        def send_email(*args, **kwargs):
            return False


ROOT = Path(__file__).resolve().parents[3]

DEFAULT_KEYWORDS = [
    "数据爬虫",
    "数据采集",
    "大作业数据",
    "毕业论文数据",
    "机器学习数据",
    "小红书爬取",
    "抖音爬取",
    "公众号爬取",
    "B站爬取",
    "YouTube爬取",
    "推特爬取",
    "新闻爬取",
    "政策数据",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "*/*",
}


@dataclass
class ScraperConfig:
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    beg: int = 0
    run_at: datetime = field(default_factory=datetime.now)
    run_date: str = ""
    run_dir_name: str = ""
    output_root: Path | None = None
    chromium_port: int = 9209
    links_per_keyword: int = 30
    min_links_per_keyword: int = 20
    scroll_times_per_keyword: int = 1
    scroll_distance: int = 1500
    detail_limit: int = 20
    page_wait_range: tuple[int, int] = (2, 4)
    scroll_wait_seconds: int = 2
    cookie: str = ""
    video_quality: str = "highest"
    image_quality: str = "highest"
    image_resolution_mode: str = "best"

    def __post_init__(self) -> None:
        if not self.run_date:
            self.run_date = self.run_at.strftime("%Y-%m-%d")
        if not self.run_dir_name:
            self.run_dir_name = self.run_at.strftime("%Y-%m-%d_%H-%M")

    @property
    def resolved_output_root(self) -> Path:
        return self.output_root or (ROOT / "output" / self.run_dir_name)

    @property
    def links_dir(self) -> Path:
        return self.resolved_output_root / "links"

    @property
    def posts_dir(self) -> Path:
        return self.resolved_output_root / "posts"

    @property
    def media_root(self) -> Path:
        return self.resolved_output_root / "media"

    @property
    def summary_path(self) -> Path:
        return self.resolved_output_root / "summary.csv"


def read_lines_to_list(file_path: Path) -> list[str]:
    with Path(file_path).open("r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def clean_file_name(file_name: str) -> str:
    return re.sub(r'[<>:/\\|?*"\n\r\t]+', "", str(file_name)).strip() or "untitled"


def parse_count(value: Any) -> int:
    if pd.isna(value):
        return 0
    text = str(value).strip().replace(",", "").replace(" ", "").replace("\t", "")
    if not text:
        return 0
    multiplier = 10000 if ("万" in text or "w" in text.lower()) else 1
    text = re.sub(r"(赞|点赞|收藏|评论|评|条|万|w|W)", "", text)
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return int(float(match.group()) * multiplier)


def note_id_from_url(url: str) -> str:
    try:
        parsed = urlparse(str(url))
        parts = [p for p in parsed.path.split("/") if p]
        return parts[-1] if parts else f"note_{abs(hash(str(url)))}"
    except Exception:
        return f"note_{abs(hash(str(url)))}"


def normalize_url(url: Any) -> str:
    value = str(url or "").strip()
    if not value or value.lower() == "nan":
        return ""
    if value.startswith("//"):
        return "https:" + value
    return value


def normalize_link_table(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename_map = {
        "关键词": "keyword",
        "链接": "url",
        "标题": "title",
        "点赞": "like_count",
        "作者": "author_name",
        "作者链接": "author_url",
        "发布日期": "publish_time_text",
        "图链接": "cover_url",
    }
    df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)
    for col in ["keyword", "url", "title", "author_name", "author_url", "publish_time_text", "cover_url"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    if "like_count" not in df.columns:
        df["like_count"] = 0
    df["like_count"] = df["like_count"].apply(parse_count)
    df["url"] = df["url"].apply(normalize_url)
    df["note_id"] = df["url"].apply(note_id_from_url)
    df = df[df["url"].ne("")].copy()
    df.drop_duplicates(subset=["note_id"], keep="first", inplace=True)
    df.sort_values("like_count", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def search_url(keyword: str) -> str:
    return f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_explore_feed"


def infer_ext(url: str, default: str = ".bin") -> str:
    low = str(url).lower()
    if ".mp4" in low:
        return ".mp4"
    if ".webm" in low:
        return ".webm"
    if ".jpg" in low or ".jpeg" in low:
        return ".jpg"
    if ".png" in low:
        return ".png"
    if ".webp" in low:
        return ".webp"
    return default


def import_media_helpers():
    media_dir = ROOT / "xhs媒体下载"
    if media_dir.exists() and str(media_dir) not in sys.path:
        sys.path.insert(0, str(media_dir))
    try:
        video_downloader = importlib.import_module("视频下载")
        image_downloader = importlib.import_module("图片下载")
    except ModuleNotFoundError:
        from xhs_workflow.scraper import image_downloader, video_downloader
    return importlib.reload(video_downloader), importlib.reload(image_downloader)


class FormalScraper:
    def __init__(self, config: ScraperConfig | None = None):
        self.config = config or ScraperConfig()
        self.bro = None
        self.ac = None
        self.vd = None
        self.imgd = None

    def prepare_output_dirs(self) -> None:
        for folder in (self.config.links_dir, self.config.posts_dir, self.config.media_root):
            folder.mkdir(parents=True, exist_ok=True)

    def connect_browser(self):
        from DrissionPage import ChromiumOptions, ChromiumPage
        from DrissionPage.common import Actions

        co = ChromiumOptions().set_paths(local_port=self.config.chromium_port).mute(True).set_argument("--start-maximized")
        self.bro = ChromiumPage(co)
        self.bro.set.auto_handle_alert()
        self.bro.set.when_download_file_exists("overwrite")
        self.ac = Actions(self.bro)
        return self.bro, self.ac

    def ensure_browser(self) -> None:
        if self.bro is None or self.ac is None:
            self.connect_browser()

    def yanz(self) -> None:
        try:
            if "website-login" in self.bro.url:
                send_email(subject="遇到验证码！！！", body="注意！验证码！！！")
                input("出现验证码，通过以后继续：")
        except Exception:
            pass

    def safe_ele_text(self, ele, selector: str, default: str = "") -> str:
        try:
            return ele.ele(selector).text.strip()
        except Exception:
            return default

    def safe_ele_link(self, ele, selector: str, default: str = "") -> str:
        try:
            return normalize_url(ele.ele(selector).link)
        except Exception:
            return default

    def extract_note_cards(self, keyword: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            note_items = self.bro.s_ele().eles(".note-item")
        except Exception:
            return records

        for rank, note_item in enumerate(note_items, start=1):
            url = self.safe_ele_link(note_item, ".cover mask ld") or self.safe_ele_link(note_item, "tag=a")
            if not url:
                continue

            title = self.safe_ele_text(note_item, ".title")
            like_text = self.safe_ele_text(note_item, ".count", "0")
            author_name = ""
            author_url = ""
            publish_time_text = ""
            try:
                footer = note_item.ele(".footer")
                author_name = self.safe_ele_text(footer, ".name")
                author_url = self.safe_ele_link(footer, ".author")
                publish_time_text = self.safe_ele_text(footer, ".time")
            except Exception:
                pass
            cover_url = ""
            try:
                cover_url = normalize_url(note_item.ele(".cover mask ld").ele("tag=img").link)
            except Exception:
                pass

            records.append({
                "keyword": keyword,
                "note_id": note_id_from_url(url),
                "url": url,
                "title": title,
                "like_count": parse_count(like_text),
                "author_name": author_name,
                "author_url": author_url,
                "publish_time_text": publish_time_text,
                "cover_url": cover_url,
                "card_rank": rank,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        return records

    def collect_links_for_keyword(self, keyword: str) -> pd.DataFrame:
        self.ensure_browser()
        self.bro.get(search_url(keyword))
        self.bro.wait(*self.config.page_wait_range)
        self.yanz()

        records = self.extract_note_cards(keyword)
        for _ in range(self.config.scroll_times_per_keyword):
            self.bro.scroll.down(self.config.scroll_distance)
            sleep(self.config.scroll_wait_seconds)
            self.yanz()
            records.extend(self.extract_note_cards(keyword))

        df = pd.DataFrame(records)
        if df.empty:
            notify_failure(
                "关键词链接采集为空",
                details=f"关键词：{keyword}\n搜索页：{search_url(keyword)}",
                dedupe_key=f"collect-empty|{keyword}",
            )
            return pd.DataFrame(columns=[
                "keyword", "note_id", "url", "title", "like_count", "author_name",
                "author_url", "publish_time_text", "cover_url", "card_rank", "collected_at",
            ])

        df = normalize_link_table(df).head(self.config.links_per_keyword).copy()
        df["keyword_link_rank"] = range(1, len(df) + 1)

        safe_keyword = clean_file_name(keyword)
        csv_path = self.config.links_dir / f"{safe_keyword}_{self.config.run_date}_links.csv"
        xlsx_path = self.config.links_dir / f"{safe_keyword}_{self.config.run_date}_links.xlsx"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        df.to_excel(xlsx_path, index=False, engine="openpyxl")

        if len(df) < self.config.min_links_per_keyword:
            print(f"{keyword}: 仅采集到 {len(df)} 条，低于 {self.config.min_links_per_keyword} 条；已按“一次滚动”策略停止。")
        else:
            print(f"{keyword}: 采集 {len(df)} 条链接 -> {csv_path}")
        return df

    def collect_all_links(self) -> pd.DataFrame:
        self.prepare_output_dirs()
        all_link_frames: list[pd.DataFrame] = []
        keywords = self.config.keywords[self.config.beg:]
        for keyword in tqdm(keywords, desc="关键词链接采集"):
            try:
                all_link_frames.append(self.collect_links_for_keyword(keyword))
            except Exception as exc:
                print(f"{keyword}: 采集失败，已跳过。原因: {exc}")
                notify_failure(
                    "关键词链接采集失败",
                    error=exc,
                    details=f"关键词：{keyword}",
                    dedupe_key=f"collect-keyword|{keyword}|{type(exc).__name__}",
                )

        links_df = normalize_link_table(pd.concat(all_link_frames, ignore_index=True)) if all_link_frames else pd.DataFrame()
        if not links_df.empty:
            links_df.to_csv(self.config.links_dir / "links_all.csv", index=False, encoding="utf-8-sig")
            links_df.to_excel(self.config.links_dir / "links_all.xlsx", index=False, engine="openpyxl")
            links_df.head(self.config.detail_limit).to_csv(
                self.config.links_dir / f"links_top{self.config.detail_limit}.csv",
                index=False,
                encoding="utf-8-sig",
            )
            links_df.head(self.config.detail_limit).to_excel(
                self.config.links_dir / f"links_top{self.config.detail_limit}.xlsx",
                index=False,
                engine="openpyxl",
            )

        print(f"链接汇总: {len(links_df)} 条")
        print(f"链接总表: {self.config.links_dir / 'links_all.csv'}")
        print(f"热门链接 Top{self.config.detail_limit}: {self.config.links_dir / f'links_top{self.config.detail_limit}.csv'}")
        return links_df

    def merge_top_links(self, links_df: pd.DataFrame | None = None) -> pd.DataFrame:
        link_files = sorted(self.config.links_dir.glob(f"*_{self.config.run_date}_links.csv"))
        if links_df is not None and not links_df.empty:
            merged_links_df = normalize_link_table(links_df)
        elif link_files:
            merged_links_df = normalize_link_table(pd.concat((pd.read_csv(p) for p in link_files), ignore_index=True))
        else:
            raise ValueError(f"没有找到可合并的链接表: {self.config.links_dir}")

        merged_links_df.to_csv(self.config.links_dir / "links_all.csv", index=False, encoding="utf-8-sig")
        merged_links_df.to_excel(self.config.links_dir / "links_all.xlsx", index=False, engine="openpyxl")

        top_links_df = merged_links_df.head(self.config.detail_limit).copy()
        top_links_df["detail_rank"] = range(1, len(top_links_df) + 1)
        top_links_df.to_csv(self.config.links_dir / f"links_top{self.config.detail_limit}.csv", index=False, encoding="utf-8-sig")
        top_links_df.to_excel(self.config.links_dir / f"links_top{self.config.detail_limit}.xlsx", index=False, engine="openpyxl")

        print(f"本次链接总数: {len(merged_links_df)}")
        print(f"将抓取详情与媒体的热门内容: {len(top_links_df)}")
        print(f"链接目录: {self.config.links_dir.resolve()}")
        return top_links_df

    def download_binary(self, url: str, save_path: Path, retries: int = 2, timeout: int = 60) -> bool:
        headers = dict(HEADERS)
        if self.config.cookie.strip():
            headers["Cookie"] = self.config.cookie.strip()

        tmp = save_path.with_suffix(save_path.suffix + ".part")
        for attempt in range(retries + 1):
            try:
                req = Request(url=url, headers=headers)
                with urlopen(req, timeout=timeout) as resp, tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                if tmp.exists() and tmp.stat().st_size > 0:
                    tmp.replace(save_path)
                    return True
            except Exception as exc:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                if attempt >= retries:
                    print(f"媒体下载失败: {url} -> {save_path.name}，原因: {exc}")
                    notify_failure(
                        "详情媒体下载失败",
                        error=exc,
                        details=f"URL: {url}\n保存路径: {save_path}",
                        dedupe_key=f"detail-media|{url}",
                    )
                else:
                    sleep(1 + attempt)
        return False

    def open_note_page(self, url: str, retries: int = 2):
        last_error = None
        for attempt in range(retries + 1):
            try:
                self.yanz()
                self.bro.get(url)
                self.bro.wait(*self.config.page_wait_range)
                self.yanz()
                return self.bro.s_ele()
            except Exception as exc:
                last_error = exc
                sleep(2 + attempt)
                try:
                    self.connect_browser()
                except Exception:
                    pass
        raise last_error

    def get_script_text(self) -> str:
        chunks: list[str] = []
        try:
            for script in self.bro.eles("tag=script"):
                html = script.html or ""
                if html:
                    chunks.append(html)
        except Exception:
            pass
        if chunks:
            return "\n".join(chunks)
        try:
            return self.bro.ele("tag=script", index=-6).html or ""
        except Exception:
            return ""

    def extract_media_urls(self, script_text: str) -> tuple[list[str], list[str]]:
        if self.vd is None or self.imgd is None:
            self.vd, self.imgd = import_media_helpers()

        video_urls: list[str] = []
        image_urls: list[str] = []
        if not script_text:
            return video_urls, image_urls

        try:
            video_urls = self.vd.extract_video_urls(script_text, quality=self.config.video_quality).video_urls
        except Exception as exc:
            notify_failure_once("视频链接解析失败", error=exc, details="详情页 script 解析视频 URL 失败")

        if not video_urls:
            try:
                image_urls = self.imgd.extract_image_urls(
                    raw_text=script_text,
                    quality=self.config.image_quality,
                    resolution_mode=self.config.image_resolution_mode,
                ).image_urls
            except Exception as exc:
                notify_failure_once("图片链接解析失败", error=exc, details="详情页 script 解析图片 URL 失败")
        return video_urls, image_urls

    def extract_detail_record(self, row: pd.Series, idx: int, total: int) -> dict[str, Any]:
        url = row["url"]
        note_id = row.get("note_id") or note_id_from_url(url)
        note_dir = self.config.media_root / note_id
        record: dict[str, Any] = {
            "note_id": note_id,
            "url": url,
            "note_text": "",
            "topics": "",
            "collect_count": 0,
            "comment_count": 0,
            "media_type": "unknown",
            "media_dir": "",
            "media_file_count": 0,
            "media_files": "[]",
            "detail_status": "ok",
            "detail_error": "",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            s_bro = self.open_note_page(url)
        except Exception as exc:
            record["detail_status"] = "open_failed"
            record["detail_error"] = str(exc)
            print(f"[{idx}/{total}] {note_id} 打开失败，跳过详情。")
            notify_failure(
                "推文详情打开失败",
                error=exc,
                details=f"note_id: {note_id}\nURL: {url}",
                dedupe_key=f"open-detail|{note_id}",
            )
            return record

        try:
            note_text = s_bro.ele("#detail-desc").text.strip()
            record["note_text"] = note_text
            topics = re.findall(r"#([\w\u4e00-\u9fff-]+)", note_text)
            record["topics"] = " ".join(dict.fromkeys(topics))
        except Exception:
            pass

        try:
            record["collect_count"] = parse_count(s_bro.ele(".collect-wrapper").text)
        except Exception:
            pass

        try:
            record["comment_count"] = parse_count(s_bro.ele(".chat-wrapper").text)
        except Exception:
            pass

        video_urls, image_urls = self.extract_media_urls(self.get_script_text())
        media_paths: list[str] = []

        if not video_urls and not image_urls:
            record["detail_status"] = "no_media_found"
            record["detail_error"] = "未解析到视频或图片链接"
            notify_failure(
                "推文媒体解析为空",
                details=f"note_id: {note_id}\nURL: {url}",
                dedupe_key=f"no-media|{note_id}",
            )

        if video_urls:
            record["media_type"] = "video"
            note_dir.mkdir(parents=True, exist_ok=True)
            video_path = note_dir / f"{note_id}.mp4"
            if self.download_binary(video_urls[0], video_path):
                media_paths.append(str(video_path))
        elif image_urls:
            record["media_type"] = "image"
            note_dir.mkdir(parents=True, exist_ok=True)
            for media_idx, image_url in enumerate(image_urls, start=1):
                ext = infer_ext(image_url, default=".jpg")
                image_path = note_dir / f"{note_id}_{media_idx:02d}{ext}"
                if self.download_binary(image_url, image_path):
                    media_paths.append(str(image_path))

        if media_paths:
            record["media_dir"] = str(note_dir)
            record["media_file_count"] = len(media_paths)
            record["media_files"] = json.dumps(media_paths, ensure_ascii=False)

        print(f"[{idx}/{total}] {note_id} | {record['media_type']} | 下载{record['media_file_count']}个 | {record['detail_status']}")
        return record

    def collect_details(self, top_links_df: pd.DataFrame | None = None) -> pd.DataFrame:
        self.prepare_output_dirs()
        self.ensure_browser()

        links_top_path = self.config.links_dir / f"links_top{self.config.detail_limit}.csv"
        if top_links_df is not None and not top_links_df.empty:
            top_links_df = normalize_link_table(top_links_df).head(self.config.detail_limit)
        elif links_top_path.exists():
            top_links_df = normalize_link_table(pd.read_csv(links_top_path)).head(self.config.detail_limit)
        else:
            top_links_df = normalize_link_table(pd.read_csv(self.config.links_dir / "links_all.csv")).head(self.config.detail_limit)

        detail_records: list[dict[str, Any]] = []
        for idx, (_, row) in enumerate(top_links_df.iterrows(), start=1):
            detail_records.append(self.extract_detail_record(row, idx, len(top_links_df)))

            posts_df = pd.DataFrame(detail_records)
            posts_df.to_csv(self.config.posts_dir / f"posts_top{self.config.detail_limit}.csv", index=False, encoding="utf-8-sig")
            posts_df.to_excel(self.config.posts_dir / f"posts_top{self.config.detail_limit}.xlsx", index=False, engine="openpyxl")

            summary_df = pd.merge(top_links_df, posts_df, on=["note_id", "url"], how="left")
            summary_df.to_csv(self.config.summary_path, index=False, encoding="utf-8-sig")

        print(f"详情表: {(self.config.posts_dir / f'posts_top{self.config.detail_limit}.csv').resolve()}")
        print(f"汇总表: {self.config.summary_path.resolve()}")
        print(f"媒体目录: {self.config.media_root.resolve()}")
        return pd.DataFrame(detail_records)

    def run_all(self) -> Path:
        print(f"本次采集时间: {self.config.run_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输出目录: {self.config.resolved_output_root.resolve()}")
        self.prepare_output_dirs()
        links_df = self.collect_all_links()
        top_links_df = self.merge_top_links(links_df)
        self.collect_details(top_links_df)
        return self.config.summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the notebook-derived XHS formal scraper.")
    parser.add_argument("--keyword", action="append", dest="keywords", help="关键词，可重复传入；不传则使用 Notebook 默认关键词。")
    parser.add_argument("--keywords-file", type=Path, help="按行读取关键词。")
    parser.add_argument("--beg", type=int, default=0, help="从关键词列表的第几个开始。")
    parser.add_argument("--run-date", default="")
    parser.add_argument("--run-dir-name", default="", help="输出目录名，默认精确到分钟，例如 2026-05-10_00-27。")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--port", type=int, default=9209, help="Chromium remote debugging port.")
    parser.add_argument("--links-per-keyword", type=int, default=30)
    parser.add_argument("--detail-limit", type=int, default=20)
    parser.add_argument("--cookie", default="")
    parser.add_argument(
        "--video-quality",
        choices=("highest", "lowest"),
        default="highest",
        help="视频流选择策略，默认 highest。",
    )
    parser.add_argument(
        "--image-quality",
        choices=("highest", "lowest", "none"),
        default="highest",
        help="图片候选选择策略，默认 highest。",
    )
    parser.add_argument(
        "--image-resolution-mode",
        choices=("best", "all"),
        default="best",
        help="图片分辨率模式，best 只返回每组最佳候选，all 返回全部候选。",
    )
    parser.add_argument("--links-only", action="store_true", help="只采集/合并链接，不进入详情页下载媒体。")
    parser.add_argument("--details-only", action="store_true", help="跳过关键词搜索，直接读取 links_top/links_all 抓详情。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    keywords = list(DEFAULT_KEYWORDS)
    if args.keywords_file:
        keywords = read_lines_to_list(args.keywords_file)
    if args.keywords:
        keywords = args.keywords

    config = ScraperConfig(
        keywords=keywords,
        beg=args.beg,
        run_date=args.run_date,
        run_dir_name=args.run_dir_name,
        output_root=args.output_root,
        chromium_port=args.port,
        links_per_keyword=args.links_per_keyword,
        detail_limit=args.detail_limit,
        cookie=args.cookie,
        video_quality=args.video_quality,
        image_quality=args.image_quality,
        image_resolution_mode=args.image_resolution_mode,
    )
    scraper = FormalScraper(config)
    scraper.prepare_output_dirs()

    print(f"本次采集时间: {config.run_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"输出目录: {config.resolved_output_root.resolve()}")

    if args.details_only:
        scraper.collect_details()
    else:
        links_df = scraper.collect_all_links()
        top_links_df = scraper.merge_top_links(links_df)
        if not args.links_only:
            scraper.collect_details(top_links_df)


if __name__ == "__main__":
    main()
