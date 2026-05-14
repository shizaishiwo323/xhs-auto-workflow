#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze own-account metrics against historical XHS material packages."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.analytics.account_performance import PerformanceAnalysisConfig, analyze_account_performance


def main() -> None:
    parser = argparse.ArgumentParser(description="基于自己账号数据和历史素材包生成下一轮素材优化建议。")
    parser.add_argument(
        "--account-metrics",
        action="append",
        type=Path,
        default=[],
        help="账号笔记数据 Excel/CSV/JSONL，可重复传入；不传时自动找最新 outputs/account_metrics 或备份文件",
    )
    parser.add_argument("--materials-root", type=Path, default=ROOT / "outputs" / "materials")
    parser.add_argument("--publish-history", type=Path, default=ROOT / "outputs" / "publish_history" / "published_history.jsonl")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    config = PerformanceAnalysisConfig(
        account_metrics_paths=args.account_metrics,
        materials_root=args.materials_root,
        publish_history_path=args.publish_history,
        output_dir=args.output_dir,
    )
    result = analyze_account_performance(config)
    output_dir = config.resolved_output_dir
    print(f"账号复盘已生成：{output_dir / 'account_performance_report.md'}")
    print(f"优化规则 JSON：{output_dir / 'account_performance_feedback.json'}")
    print(f"稳定入口：{ROOT / 'outputs' / 'account_performance' / 'latest_optimization.json'}")
    print(f"分析笔记数：{result['note_count']}，匹配素材包：{result['matched_material_count']}")


if __name__ == "__main__":
    main()

