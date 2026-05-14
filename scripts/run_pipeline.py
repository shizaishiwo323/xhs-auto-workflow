#!/usr/bin/env python3
"""Small orchestrator for the XHS workflow."""

from __future__ import annotations

import argparse
from datetime import datetime
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


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
    parser.add_argument("--links-only", action="store_true")
    parser.add_argument("--details-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = args.manifest or (
        None if args.stage in {"crawl", "account-fetch", "account-analyze", "publish-batch"} else latest_manifest()
    )
    package = manifest.parents[1] if manifest else None

    if args.stage == "crawl":
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
        run([sys.executable, "scripts/publish_from_manifest.py", str(manifest), "--port", str(args.port), "--fill"])
    elif args.stage == "publish":
        run([
            sys.executable,
            "scripts/publish_from_manifest.py",
            str(manifest),
            "--port",
            str(args.port),
            "--submit",
        ])
    elif args.stage == "publish-batch":
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
