#!/usr/bin/env python3
"""Publish one XHS package using the notebook-derived publisher module."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.publisher.auto_publish import PublishConfig, run_single_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish XHS note from publish_manifest.json",
        epilog=(
            "话题规则：manifest 需提供 recommended_topics/topic_tags/topics/tags。"
            "发布器会在正文末尾逐个输入 #话题、等待 0.5 秒、再回车。"
            "合集规则：可提供 collection_name/collection_title/target_collection；"
            "发布器会归一到塔罗牌合集、数据资源的合集、随便发发合集，"
            "声明原创后只选择已存在合集，不再自动创建。"
        ),
    )
    parser.add_argument("manifest", type=Path, help="Path to publish_manifest.json")
    parser.add_argument("--port", type=int, default=9209, help="Chromium remote debugging port")
    parser.add_argument("--fill", action="store_true", help="Fill the browser page but do not publish")
    parser.add_argument("--submit", action="store_true", help="Fill the browser page and click publish")
    parser.add_argument("--schedule-time", help="Schedule publish time, format: YYYY-MM-DD HH:MM")
    parser.add_argument("--materials-date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    if args.fill and args.submit:
        parser.error("--fill 和 --submit 只能选择一个。")

    config = PublishConfig(
        root=ROOT,
        materials_date=args.materials_date,
        chromium_port=args.port,
        submit=args.submit,
    )
    run_single_manifest(
        args.manifest,
        config,
        fill=args.fill,
        submit=args.submit,
        schedule_time=args.schedule_time,
    )


if __name__ == "__main__":
    main()
