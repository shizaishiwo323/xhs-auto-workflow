#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch own-account XHS note metrics from creator note manager."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.analytics.account_performance import AccountMetricsFetchConfig, fetch_account_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取自己账号的小红书笔记浏览、点赞、收藏、评论等数据。")
    parser.add_argument("--port", type=int, default=9209, help="Chromium remote debugging port")
    parser.add_argument("--scroll-batches", type=int, default=5, help="滚动加载次数，默认沿用 notebook 的 5 次")
    parser.add_argument("--scroll-wait", type=float, default=3.0, help="每次滚动后的等待秒数")
    parser.add_argument("--output", type=Path, default=None, help="输出 Excel 路径")
    args = parser.parse_args()

    config = AccountMetricsFetchConfig(
        chromium_port=args.port,
        scroll_batches=args.scroll_batches,
        scroll_wait_seconds=args.scroll_wait,
        output_path=args.output,
    )
    df = fetch_account_metrics(config)
    print(f"账号数据已保存：{config.resolved_output_path}")
    print(f"共获得 {len(df)} 条笔记数据")


if __name__ == "__main__":
    main()

