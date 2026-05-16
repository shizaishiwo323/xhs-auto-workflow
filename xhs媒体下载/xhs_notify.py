# -*- coding: utf-8 -*-
"""兼容从 xhs媒体下载 目录直接运行 Notebook/脚本时的通知工具入口。"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_IMPL_PATH = Path(__file__).resolve().parent.parent / "xhs_notify.py"
_SPEC = spec_from_file_location("_xhs_notify_impl", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"无法加载通知模块：{_IMPL_PATH}")

_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

send_email = _MODULE.send_email
notify_failure = _MODULE.notify_failure
notify_failure_once = _MODULE.notify_failure_once
get_email_config = _MODULE.get_email_config
