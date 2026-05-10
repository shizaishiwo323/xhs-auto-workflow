# -*- coding: utf-8 -*-
"""小红书自动化流程的 Gmail 插件通知工具。

项目内 Python 代码不能直接调用 Codex 的 Gmail 插件；这里负责把通知
标准化并写入待发送队列。自动化线程读取队列后调用 Gmail 插件发送。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import json
import os
import platform
import traceback


_SENT_KEYS: set[str] = set()
DEFAULT_OUTBOX_DIR = Path("outputs") / "gmail_notifications"


@dataclass(frozen=True)
class EmailConfig:
    receivers: tuple[str, ...]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _candidate_env_files() -> list[Path]:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()
    candidates = [
        cwd / ".env",
        cwd / "xhs媒体下载" / ".env",
        here / ".env",
        here / "xhs媒体下载" / ".env",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _load_setting(name: str, default: str = "") -> str:
    env_value = os.environ.get(name, "").strip()
    if env_value:
        return env_value

    for env_file in _candidate_env_files():
        value = _parse_env_file(env_file).get(name, "").strip()
        if value:
            return value
    return default


def get_email_config(receivers: Optional[Sequence[str]] = None) -> EmailConfig:
    """读取 Gmail 插件收件人配置。

    优先使用调用方传入的 `jieshou`/`receivers`，其次读取 `GMAIL_RECEIVERS`。
    为了兼容旧环境，`SMTP_RECEIVERS` 只作为收件人列表的回退值，不再读取
    或使用 SMTP 发信账号、授权码。
    """
    receiver_text = (
        _load_setting("GMAIL_RECEIVERS")
        or _load_setting("GMAIL_TO")
        or _load_setting("XHS_GMAIL_RECEIVERS")
        or _load_setting("SMTP_RECEIVERS")
        or _load_setting("NOTIFY_EMAIL")
    )
    configured_receivers = list(receivers or []) or [
        item.strip()
        for item in receiver_text.split(",")
        if item.strip()
    ]

    if not configured_receivers:
        raise ValueError("未配置 Gmail 通知收件人，请设置 GMAIL_RECEIVERS")

    return EmailConfig(receivers=tuple(configured_receivers))


def _notification_outbox_dir() -> Path:
    configured = _load_setting("GMAIL_OUTBOX_DIR") or _load_setting("XHS_GMAIL_OUTBOX_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_OUTBOX_DIR


def _normalize_attachments(attachments: Optional[Iterable[str | Path]]) -> list[str]:
    paths: list[str] = []
    for attachment in attachments or []:
        path = Path(attachment).expanduser()
        if path.exists() and path.is_file():
            paths.append(str(path.resolve()))
    return paths


def _write_gmail_outbox(payload: dict[str, object]) -> Path:
    outbox_dir = _notification_outbox_dir()
    outbox_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    outbox_path = outbox_dir / f"{timestamp}_gmail_notification.json"
    outbox_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return outbox_path


def send_email(
    subject: str = "小红书自动化通知",
    body: str = "",
    jieshou: Optional[Sequence[str]] = None,
    attachments: Optional[Iterable[str | Path]] = None,
) -> bool:
    """生成一条由 Codex Gmail 插件发送的通知请求。

    真实发送动作由自动化线程调用 Gmail 插件完成；本函数不再使用 SMTP。
    """
    try:
        config = get_email_config(receivers=jieshou)
        payload = {
            "transport": "codex_gmail_plugin",
            "plugin_tool": "mcp__codex_apps__gmail._send_email",
            "to": ", ".join(config.receivers),
            "subject": subject,
            "body": body or subject,
            "attachment_files": ", ".join(_normalize_attachments(attachments)),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "pending_gmail_plugin_send",
        }
        outbox_path = _write_gmail_outbox(payload)
        print(f"Gmail 插件待发送通知已写入：{outbox_path.resolve()}")
        return True
    except Exception as exc:
        print(f"Gmail 插件通知生成失败: {exc}")
        return False


def notify_failure(
    stage: str,
    error: Optional[BaseException] = None,
    details: str = "",
    attachments: Optional[Iterable[str | Path]] = None,
    dedupe_key: Optional[str] = None,
) -> bool:
    """发送失败告警；支持 dedupe_key 防止同一错误刷屏。"""
    if dedupe_key:
        if dedupe_key in _SENT_KEYS:
            return False
        _SENT_KEYS.add(dedupe_key)

    lines = [
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"主机: {platform.node()}",
        f"工作目录: {Path.cwd()}",
        f"失败环节: {stage}",
    ]
    if details:
        lines.extend(["", "详情:", details])
    if error is not None:
        lines.extend(["", "异常:", f"{type(error).__name__}: {error}"])
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        lines.extend(["", "堆栈:", tb[-4000:]])

    return send_email(
        subject=f"[小红书自动化失败] {stage}",
        body="\n".join(lines),
        attachments=attachments,
    )


def notify_failure_once(
    stage: str,
    error: Optional[BaseException] = None,
    details: str = "",
    attachments: Optional[Iterable[str | Path]] = None,
) -> bool:
    key = f"{stage}|{type(error).__name__ if error else ''}|{str(error)[:160] if error else details[:160]}"
    return notify_failure(stage, error=error, details=details, attachments=attachments, dedupe_key=key)
