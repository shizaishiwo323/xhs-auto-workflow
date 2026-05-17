#!/usr/bin/env python3
"""Small orchestrator for the XHS workflow."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def print_publish_topic_hint() -> None:
    print(
        "发布话题规则：publish_manifest.json 需提供 recommended_topics/topic_tags/topics/tags；"
        "发布器会在正文末尾逐个输入 #话题、等待 0.5 秒、再回车。"
        "合集规则：可提供 collection_name/collection_title/target_collection；"
        "发布器会归一到塔罗牌合集、数据资源的合集、随便发发合集，"
        "声明原创后只选择已存在合集，不再自动创建。",
        flush=True,
    )


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def latest_crawl_summary(since: float | None = None) -> Path | None:
    summaries = sorted((ROOT / "output").glob("*/summary.csv"), key=lambda path: path.stat().st_mtime)
    if since is not None:
        summaries = [path for path in summaries if path.stat().st_mtime >= since]
    return summaries[-1] if summaries else None


def is_complete_reference(row: dict[str, str]) -> bool:
    title = str(row.get("title") or row.get("标题") or "").strip()
    body = str(row.get("note_text") or row.get("推文") or row.get("正文") or "").strip()
    status = str(row.get("detail_status") or "").strip()
    return bool(title and body and (not status or status == "ok"))


def check_crawl_reference_completeness(min_complete_references: int, since: float | None = None) -> bool:
    summary_path = latest_crawl_summary(since=since)
    if summary_path is None:
        print("爬取完整性检查：未找到本次新生成的 output/*/summary.csv，无法确认爆款参考是否完整。", file=sys.stderr)
        return False

    with summary_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    total = len(rows)
    complete_rows = [row for row in rows if is_complete_reference(row)]
    missing_body_rows = [
        row for row in rows
        if str(row.get("title") or row.get("标题") or "").strip()
        and not str(row.get("note_text") or row.get("推文") or row.get("正文") or "").strip()
    ]

    print(
        f"爬取完整性检查：{len(complete_rows)}/{total} 条参考同时包含标题和正文；"
        f"最低要求 {min_complete_references} 条。文件：{summary_path}",
        flush=True,
    )
    if len(complete_rows) >= min_complete_references:
        return True

    print(
        "参考不足：高互动笔记缺少正文，疑似详情页被风控、登录态异常或正文选择器失效。"
        "本次结果只能学习标题/封面入口，不能学习正文写法；请重新爬取、修复详情抓取，"
        "或手动补充至少 3 条包含标题和正文的爆款参考。",
        file=sys.stderr,
    )
    if missing_body_rows:
        sample_titles = [
            str(row.get("title") or row.get("标题") or "").strip()
            for row in missing_body_rows[:3]
        ]
        print("缺正文样例标题：" + "；".join(sample_titles), file=sys.stderr)
    return False


def latest_manifest() -> Path:
    manifests = sorted((ROOT / "outputs" / "materials").glob("*/*/00_自动发推适配/publish_manifest.json"))
    if not manifests:
        raise FileNotFoundError("未找到 outputs/materials 下的 publish_manifest.json")
    return manifests[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run XHS workflow stages.")
    parser.add_argument(
        "stage",
        choices=("crawl", "account-fetch", "account-analyze", "validate", "publish-dry-run", "publish", "publish-batch"),
        help="Run notebook-derived crawl/publish helpers and package validation.",
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--port", type=int, default=9209)
    parser.add_argument("--materials-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--materials-dir", type=Path, default=None)
    parser.add_argument("--materials-root", type=Path, default=None)
    parser.add_argument("--account-metrics", action="append", type=Path, default=[])
    parser.add_argument("--account-output", type=Path, default=None)
    parser.add_argument("--account-output-dir", type=Path, default=None)
    parser.add_argument("--scroll-batches", type=int, default=5)
    parser.add_argument("--keyword", action="append", dest="keywords")
    parser.add_argument("--keywords-file", type=Path, default=None)
    parser.add_argument("--detail-limit", type=int, default=20)
    parser.add_argument("--video-quality", choices=("highest", "lowest"), default="highest")
    parser.add_argument("--image-quality", choices=("highest", "lowest", "none"), default="highest")
    parser.add_argument("--image-resolution-mode", choices=("best", "all"), default="best")
    parser.add_argument("--min-complete-references", type=int, default=3)
    parser.add_argument("--allow-incomplete-references", action="store_true")
    parser.add_argument("--links-only", action="store_true")
    parser.add_argument("--details-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = args.manifest or (
        None if args.stage in {"crawl", "account-fetch", "account-analyze", "publish-batch"} else latest_manifest()
    )
    package = manifest.parents[1] if manifest else None

    if args.stage == "crawl":
        crawl_started_at = time.time()
        command = [sys.executable, "scripts/run_scraper.py", "--port", str(args.port), "--detail-limit", str(args.detail_limit)]
        command.extend(["--video-quality", args.video_quality])
        command.extend(["--image-quality", args.image_quality])
        command.extend(["--image-resolution-mode", args.image_resolution_mode])
        if args.keywords_file:
            command.extend(["--keywords-file", str(args.keywords_file)])
        for keyword in args.keywords or []:
            command.extend(["--keyword", keyword])
        if args.links_only:
            command.append("--links-only")
        if args.details_only:
            command.append("--details-only")
        run(command)
        if not args.links_only and not check_crawl_reference_completeness(args.min_complete_references, since=crawl_started_at):
            if args.allow_incomplete_references:
                print("已按 --allow-incomplete-references 放行不完整参考；后续只能学习标题/封面，不能学习正文写法。")
            else:
                raise SystemExit(2)
    elif args.stage == "account-fetch":
        command = [
            sys.executable,
            "scripts/fetch_account_metrics.py",
            "--port",
            str(args.port),
            "--scroll-batches",
            str(args.scroll_batches),
        ]
        if args.account_output:
            command.extend(["--output", str(args.account_output)])
        run(command)
    elif args.stage == "account-analyze":
        command = [sys.executable, "scripts/analyze_account_performance.py"]
        for path in args.account_metrics:
            command.extend(["--account-metrics", str(path)])
        if args.materials_root:
            command.extend(["--materials-root", str(args.materials_root)])
        if args.account_output_dir:
            command.extend(["--output-dir", str(args.account_output_dir)])
        run(command)
    elif args.stage == "validate":
        run([sys.executable, "scripts/validate_package.py", str(package)])
    elif args.stage == "publish-dry-run":
        print_publish_topic_hint()
        run([sys.executable, "scripts/publish_from_manifest.py", str(manifest), "--port", str(args.port), "--fill"])
    elif args.stage == "publish":
        print_publish_topic_hint()
        run([
            sys.executable,
            "scripts/publish_from_manifest.py",
            str(manifest),
            "--port",
            str(args.port),
            "--submit",
        ])
    elif args.stage == "publish-batch":
        print_publish_topic_hint()
        command = [
            sys.executable,
            "scripts/publish_batch.py",
            "--materials-date",
            args.materials_date,
            "--port",
            str(args.port),
        ]
        if args.materials_dir:
            command.extend(["--materials-dir", str(args.materials_dir)])
        if args.dry_run:
            command.append("--dry-run")
        run(command)


if __name__ == "__main__":
    main()
