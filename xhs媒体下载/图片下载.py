# -*- coding: utf-8 -*-
"""兼容旧 Notebook 的图片下载入口。"""

from __future__ import annotations

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from xhs_workflow.scraper.image_downloader import *  # noqa: F401,F403
from xhs_workflow.scraper.image_downloader import main as _main


if __name__ == "__main__":
    _main()
