#!/usr/bin/env python3
"""Small orchestrator for the three-step XHS workflow."""

from __future__ import annotations

import argparse
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
        choices=("validate", "publish-dry-run", "publish"),
        help="Current automation-ready stages. Crawl/generate stay in notebooks until fully scripted.",
    )
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--port", type=int, default=9209)
    args = parser.parse_args()

    manifest = args.manifest or latest_manifest()
    package = manifest.parents[1]

    if args.stage == "validate":
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


if __name__ == "__main__":
    main()
