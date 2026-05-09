#!/usr/bin/env python3
"""Publish one generated XHS package from publish_manifest.json.

Default mode only validates the manifest. Pass --fill to fill the browser page
without publishing, or --submit to click the publish button. Pass
--schedule-time to schedule a note instead of publishing immediately.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from time import sleep
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xhs_workflow.notify import notify_failure


TITLE_LIMIT = 20
BODY_LIMIT = 1000
IMAGE_LIMIT = 18


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest 格式不正确：{path}")
    return data


def ordered_images(manifest: dict[str, Any]) -> list[Path]:
    items = sorted(manifest.get("images", []), key=lambda item: item.get("upload_order", 999))
    return [Path(str(item.get("path", ""))).expanduser() for item in items]


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    title = str(manifest.get("recommended_title") or manifest.get("publish_row", {}).get("标题", ""))
    body = str(manifest.get("body") or manifest.get("publish_row", {}).get("推文", ""))
    images = ordered_images(manifest)
    issues: list[str] = []

    if not title:
        issues.append("缺少标题。")
    if len(title) > TITLE_LIMIT:
        issues.append(f"标题超过 {TITLE_LIMIT} 字：{len(title)}")
    if not body:
        issues.append("缺少正文。")
    if len(body) > BODY_LIMIT:
        issues.append(f"正文超过 {BODY_LIMIT} 字：{len(body)}")
    if not images:
        issues.append("缺少发布图片。")
    if len(images) > IMAGE_LIMIT:
        issues.append(f"图片超过 {IMAGE_LIMIT} 张：{len(images)}")
    for image in images:
        if not image.exists():
            issues.append(f"图片不存在：{image}")

    return issues


def pick_text(manifest: dict[str, Any]) -> tuple[str, str]:
    title = str(manifest.get("recommended_title") or manifest.get("publish_row", {}).get("标题", ""))
    body = str(manifest.get("body") or manifest.get("publish_row", {}).get("推文", ""))
    return title[:TITLE_LIMIT], body[:BODY_LIMIT]


def open_publish_page(port: int):
    from DrissionPage import ChromiumOptions, ChromiumPage
    from DrissionPage.common import Actions

    co = (
        ChromiumOptions()
        .set_paths(local_port=port)
        .mute(True)
        .set_argument("--start-maximized")
        .ignore_certificate_errors(True)
    )
    page = ChromiumPage(co)
    page.set.auto_handle_alert()
    actions = Actions(page)
    try:
        page.get("https://creator.xiaohongshu.com/publish/publish?from=menu&target=image")
    except Exception:
        page.get("https://creator.xiaohongshu.com/publish/publish")
    sleep(2)
    try:
        tab = page.ele("text=上传图文", timeout=2)
        actions.move_to(ele_or_loc=tab).click()
    except Exception:
        pass
    return page, actions


def validate_schedule_time(value: str) -> str:
    try:
        publish_at = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("定时时间格式应为 YYYY-MM-DD HH:MM，例如 2026-05-10 20:30") from exc
    if publish_at <= datetime.now():
        raise ValueError(f"定时时间必须晚于当前时间：{value}")
    return publish_at.strftime("%Y-%m-%d %H:%M")


def scroll_down(page, actions, distance: int = 700) -> None:
    try:
        size = page.run_js("return {w: window.innerWidth, h: window.innerHeight};")
        actions.move_to((size["w"] // 2, size["h"] // 2))
    except Exception:
        pass
    total = 0
    while total < distance:
        actions.scroll(delta_y=70)
        total += 70
        sleep(0.08)


def select_recommended_topics(page, actions) -> None:
    scroll_down(page, actions, 500)
    for _ in range(10):
        try:
            topic = page.ele(".tag-group", timeout=1).child("t:span", index=1)
            actions.move_to(ele_or_loc=topic).click()
            sleep(1)
        except Exception:
            continue


def set_schedule_time(page, actions, schedule_time: str) -> None:
    from DrissionPage.common import Keys

    scroll_down(page, actions, 700)

    last_error: Exception | None = None
    try:
        switch = page.ele(".custom-switch-switch", index=-1, timeout=3).ele(".d-switch-box", timeout=1)
        switch.click(by_js=None)
    except Exception as exc:
        last_error = exc
        try:
            switch = page.ele(".d-switch-box", index=-1, timeout=3)
            actions.move_to(ele_or_loc=switch).click()
            last_error = None
        except Exception as fallback_exc:
            last_error = fallback_exc
    if last_error is not None:
        raise RuntimeError("找不到定时发布开关。") from last_error

    sleep(3)

    input_selectors = (
        ".d-datepicker-suffix --color-text-description d-datepicker-suffix-indicator",
        ".d-datepicker input",
        "@placeholder=请选择时间",
        "@placeholder:请选择时间",
    )
    last_error = None
    for selector in input_selectors:
        try:
            date_input = page.ele(selector, timeout=3)
            actions.move_to(ele_or_loc=date_input).click()
            actions.key_down(Keys.SHIFT)
            for _ in range(24):
                actions.key_down(Keys.LEFT).key_up(Keys.LEFT)
                sleep(0.03)
            actions.key_up(Keys.SHIFT)
            date_input.input(schedule_time)
            return
        except Exception as exc:
            last_error = exc
            try:
                actions.key_up(Keys.SHIFT)
            except Exception:
                pass
    raise RuntimeError("找不到定时发布时间输入框。") from last_error


def find_upload_control(page):
    selectors = ("tx=上传图片", ".upload-wrapper", ".entry")
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=3)
            if selector == ".upload-wrapper":
                try:
                    return ele.ele(".upload-input", timeout=1)
                except Exception:
                    return ele
            return ele
        except Exception:
            continue
    raise RuntimeError("找不到上传图片控件。")


def fill_field(page, selectors: tuple[str, ...], value: str, field_name: str) -> None:
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=3)
            ele.input(value)
            return
        except Exception:
            continue
    raise RuntimeError(f"找不到{field_name}输入框。")


def publish_manifest(manifest: dict[str, Any], port: int, submit: bool, schedule_time: str | None) -> None:
    page, actions = open_publish_page(port)
    title, body = pick_text(manifest)
    images = ordered_images(manifest)

    upload = find_upload_control(page)
    upload.click.to_upload(str(images[0]))
    page.wait(2, 3)
    for image in images[1:]:
        upload = find_upload_control(page)
        upload.click.to_upload(str(image))
        page.wait(1, 2)

    fill_field(page, ("@placeholder:填写标题", "@placeholder=填写标题会有更多赞哦～"), title, "标题")
    fill_field(
        page,
        ("@data-placeholder:输入正文描述", "@data-placeholder=输入正文描述，真诚有价值的分享予人温暖"),
        body,
        "正文",
    )
    sleep(1)

    select_recommended_topics(page, actions)

    if schedule_time:
        set_schedule_time(page, actions, schedule_time)

    if not submit:
        if schedule_time:
            print(f"已完成页面填充和定时时间设置校验：{schedule_time}。当前为 dry-run，未点击定时发布。")
        else:
            print("已完成页面填充校验，当前为 dry-run，未点击发布。")
        return

    if schedule_time:
        try:
            button = page.ele("tx=定时发布", index=-1, timeout=5)
        except Exception:
            button = page.ele(".:publishBtn", timeout=5)
    else:
        try:
            button = page.ele(".:publishBtn", timeout=5)
        except Exception:
            button = page.ele("tx=发布", timeout=5)
    actions.move_to(ele_or_loc=button).click()
    if schedule_time:
        print(f"已点击定时发布按钮：{schedule_time}")
    else:
        print("已点击发布按钮。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish XHS note from publish_manifest.json")
    parser.add_argument("manifest", type=Path, help="Path to publish_manifest.json")
    parser.add_argument("--port", type=int, default=9209, help="Chromium remote debugging port")
    parser.add_argument("--fill", action="store_true", help="Fill the browser page but do not publish")
    parser.add_argument("--submit", action="store_true", help="Fill the browser page and click publish")
    parser.add_argument("--schedule-time", help="Schedule publish time, format: YYYY-MM-DD HH:MM")
    args = parser.parse_args()
    if args.fill and args.submit:
        parser.error("--fill 和 --submit 只能选择一个。")
    schedule_time = validate_schedule_time(args.schedule_time) if args.schedule_time else None

    manifest = load_manifest(args.manifest)
    issues = validate_manifest(manifest)
    if issues:
        print("发布校验未通过：")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("发布校验通过。")
    print(f"标题：{pick_text(manifest)[0]}")
    print(f"图片数：{len(ordered_images(manifest))}")
    if schedule_time:
        print(f"定时时间：{schedule_time}")

    if not args.fill and not args.submit:
        print("仅完成 manifest 校验，未打开浏览器。")
        return

    try:
        publish_manifest(manifest, port=args.port, submit=args.submit, schedule_time=schedule_time)
    except Exception as exc:
        notify_failure("发布脚本失败", error=exc, details=f"manifest: {args.manifest}")
        raise


if __name__ == "__main__":
    main()
