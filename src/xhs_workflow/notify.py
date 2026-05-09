# -*- coding: utf-8 -*-
"""小红书自动化流程的邮件通知工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Optional, Sequence

import os
import platform
import smtplib
import ssl
import traceback


SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
_SENT_KEYS: set[str] = set()


@dataclass(frozen=True)
class EmailConfig:
    sender: str
    auth_code: str
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
    sender = _load_setting("SMTP_EMAIL")
    auth_code = _load_setting("SMTP_AUTH_CODE")
    configured_receivers = receivers or [
        item.strip()
        for item in _load_setting("SMTP_RECEIVERS", sender).split(",")
        if item.strip()
    ]

    if not sender:
        raise ValueError("未配置 SMTP_EMAIL")
    if not auth_code:
        raise ValueError("未配置 SMTP_AUTH_CODE")
    if not configured_receivers:
        raise ValueError("未配置 SMTP_RECEIVERS")

    return EmailConfig(
        sender=sender,
        auth_code=auth_code,
        receivers=tuple(configured_receivers),
    )


def send_email(
    subject: str = "小红书自动化通知",
    body: str = "",
    jieshou: Optional[Sequence[str]] = None,
    attachments: Optional[Iterable[str | Path]] = None,
) -> bool:
    """发送邮件；失败时只打印错误，不中断主流程。"""
    try:
        config = get_email_config(receivers=jieshou)
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = config.sender
        msg["To"] = ", ".join(config.receivers)
        msg.attach(MIMEText(body or subject, "plain", "utf-8"))

        for attachment in attachments or []:
            attachment_path = Path(attachment)
            if not attachment_path.exists() or not attachment_path.is_file():
                continue
            with attachment_path.open("rb") as file:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(file.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_path.name}"')
            msg.attach(part)

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as smtp:
            smtp.login(config.sender, config.auth_code)
            smtp.send_message(msg)
        print(f"邮件成功发送至 {msg['To']}，主题为：{msg['Subject']}")
        return True
    except Exception as exc:
        print(f"邮件发送失败: {exc}")
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
