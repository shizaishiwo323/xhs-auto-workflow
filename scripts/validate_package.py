#!/usr/bin/env python3
"""Validate a generated XHS material package."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.materials.validate_xhs_package import main


if __name__ == "__main__":
    main()

