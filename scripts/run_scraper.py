#!/usr/bin/env python3
"""Run the notebook-derived formal XHS scraper."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.scraper.formal_scraper import main


if __name__ == "__main__":
    main()
