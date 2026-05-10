# -*- coding: utf-8 -*-
"""
小红书视频下载模块

流程：
1) 从页面输出文本（如 <script>window.__INITIAL_STATE__=...</script>）提取视频流
2) 按每个视频选择最高/最低分辨率（或体积）
3) 下载到本地目录

支持输入来源：
- 原始文本（raw text）
- .ipynb 单元格输出
- DrissionPage 的浏览器对象 + url

Notebook 示例：
    import 视频下载 as vd
    result = vd.download_from_page(
        bro,
        url='https://www.xiaohongshu.com/search_result/xxx',
        quality='highest',  # 或 'lowest'
        output_dir='./video_downloads',
    )
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import hashlib
import time as _time
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Any, Optional, Set, List, Tuple, Dict, Literal, Union

try:
    from xhs_workflow.notify import notify_failure, notify_failure_once
except Exception:
    try:
        from xhs_notify import notify_failure, notify_failure_once
    except Exception:
        def notify_failure(*args, **kwargs):
            return False

        def notify_failure_once(*args, **kwargs):
            return False


# ========= 可按需修改默认值 =========
DEFAULT_INPUT_PATH = Path("./video.json")
DEFAULT_OUTPUT_DIR_NAME = "video_downloads"
COOKIE = ""  # 如果遇到 403，可粘贴浏览器中的 cookie
# ===================================


TIMEOUT = (10, 60)          # (连接超时, 读取超时)
CHUNK_SIZE = 1024 * 1024    # 1MB
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
PROGRESS_LOG_SECONDS = 1.0
QualityMode = Literal["lowest", "highest"]

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Accept": "*/*",
}


@dataclass
class ExtractSummary:
    all_url_count: int
    raw_video_candidate_count: int
    selected_streams: List[Dict[str, Any]]
    video_urls: List[str]
    quality: QualityMode


@dataclass
class DownloadSummary:
    total: int
    success: int
    failed: int
    output_dir: Path


def build_headers(cookie: str = "") -> Dict[str, str]:
    headers = dict(BASE_HEADERS)
    if cookie.strip():
        headers["Cookie"] = cookie.strip()
    elif COOKIE.strip():
        headers["Cookie"] = COOKIE.strip()
    return headers


def collect_strings(obj: Any, out: List[str]) -> None:
    """递归收集对象中的字符串值"""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_strings(v, out)
    elif isinstance(obj, list):
        for item in obj:
            collect_strings(item, out)


def read_input_text(path: Path) -> str:
    """读取输入文本；支持 .ipynb（仅提取输出内容）"""
    if path.suffix.lower() != ".ipynb":
        return path.read_text(encoding="utf-8")

    # .ipynb：优先提取每个 code cell 的 outputs 文本，避免把整份 notebook 源码混进来
    nb_obj = json.loads(path.read_text(encoding="utf-8"))
    chunks: List[str] = []
    for cell in nb_obj.get("cells", []):
        for output in cell.get("outputs", []):
            collect_strings(output, chunks)

    return "\n".join(chunks)


def extract_braced_object(text: str, start_pos: int) -> Optional[str]:
    """从 start_pos 后提取一个完整的 {...}（支持字符串内括号）"""
    i = text.find("{", start_pos)
    if i < 0:
        return None

    depth = 0
    in_str = False
    quote = ""
    escape = False
    for j in range(i, len(text)):
        ch = text[j]

        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            continue

        if ch in ('"', "'"):
            in_str = True
            quote = ch
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]

    return None


def js_like_to_json_text(text: str) -> str:
    """把常见 JS 字面量修正为 JSON 可解析形式"""
    fixed = text
    fixed = re.sub(r":\s*undefined(?=\s*[,}])", ": null", fixed)
    fixed = re.sub(r":\s*NaN(?=\s*[,}])", ": null", fixed)
    fixed = re.sub(r":\s*Infinity(?=\s*[,}])", ": null", fixed)
    fixed = re.sub(r":\s*-Infinity(?=\s*[,}])", ": null", fixed)
    return fixed


def extract_json_candidates_from_script(text: str) -> List[str]:
    """从 window.__INITIAL_STATE__=... 这类脚本中提取 JSON 对象候选"""
    patterns = [
        r"window\.__INITIAL_STATE__\s*=",
        r"__INITIAL_STATE__\s*=",
    ]

    candidates: List[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            obj = extract_braced_object(text, m.end())
            if obj:
                candidates.append(obj)
    return candidates


def normalize_url(raw: Optional[str]) -> Optional[str]:
    """清洗并标准化 URL"""
    if not isinstance(raw, str):
        return None

    url = raw.strip().strip('"').strip("'").strip(",")
    if not url:
        return None

    # 解码 \uXXXX（如 \u002F -> /）
    url = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), url)
    # 兼容 JSON 中的 \/ 写法
    url = url.replace("\\/", "/")

    # 修正偶发的单斜杠协议头
    if url.startswith("http:/") and not url.startswith("http://"):
        url = url.replace("http:/", "http://", 1)
    if url.startswith("https:/") and not url.startswith("https://"):
        url = url.replace("https:/", "https://", 1)

    if not url.startswith(("http://", "https://")):
        return None

    return url


def looks_like_video_url(url: str) -> bool:
    """判断是否像视频链接"""
    path_lower = urlparse(url).path.lower()
    if any(path_lower.endswith(ext) for ext in VIDEO_EXTS):
        return True

    # 小红书流地址兜底判断
    url_lower = url.lower()
    if "xhscdn.com/stream/" in url_lower and ".mp4" in url_lower:
        return True

    return False


def canonical_video_key(url: str) -> str:
    """用于去重：忽略域名差异（masterUrl / backupUrls 通常 path 相同）"""
    parsed = urlparse(url)
    return parsed.path.lower() if parsed.path else url.lower()


def dedupe_video_urls(urls: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: Set[str] = set()
    for u in urls:
        key = canonical_video_key(u)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(u)
    return deduped


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{num_bytes}B"


def to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def try_load_json(text: str) -> Optional[Any]:
    """尝试把文本解析为 JSON；片段 JSON 也尝试包裹后解析"""
    text = text.strip()
    if not text:
        return None

    script_candidates = extract_json_candidates_from_script(text)
    candidates = script_candidates + [text]
    if not (text.startswith("{") or text.startswith("[")):
        candidates.append("{" + text + "}")

    for c in candidates:
        try:
            return json.loads(js_like_to_json_text(c))
        except json.JSONDecodeError:
            continue
    return None


def collect_media_nodes(obj: Any, out: List[Dict[str, Any]]) -> None:
    """递归收集包含 stream 字段的 media 节点"""
    if isinstance(obj, dict):
        if isinstance(obj.get("stream"), dict):
            out.append(obj)
        for v in obj.values():
            collect_media_nodes(v, out)
    elif isinstance(obj, list):
        for item in obj:
            collect_media_nodes(item, out)


def media_group_id(media_node: Dict[str, Any], idx: int) -> str:
    """给每个视频分组，保证每组只取一个清晰度"""
    video_id = media_node.get("videoId")
    if video_id is not None:
        return f"videoId:{video_id}"

    video_meta = media_node.get("video")
    if isinstance(video_meta, dict):
        biz_id = video_meta.get("bizId")
        if biz_id:
            return f"bizId:{biz_id}"
        md5 = video_meta.get("md5")
        if md5:
            return f"md5:{md5}"

    return f"media:{idx}"


def pick_stream_url(stream_item: Dict[str, Any]) -> Optional[str]:
    """优先 masterUrl，不可用再退到 backupUrls"""
    master = normalize_url(stream_item.get("masterUrl"))
    if master and looks_like_video_url(master):
        return master

    backups = stream_item.get("backupUrls")
    if isinstance(backups, list):
        for b in backups:
            u = normalize_url(b)
            if u and looks_like_video_url(u):
                return u

    return None


def normalize_quality(quality: str) -> QualityMode:
    q = quality.strip().lower()
    if q not in {"lowest", "highest"}:
        raise ValueError("quality 仅支持 'lowest' 或 'highest'")
    return q  # type: ignore[return-value]


def _stream_sort_key(item: Dict[str, Any], quality: QualityMode) -> Tuple[int, int, str]:
    size = item.get("size")
    width = item.get("width")
    height = item.get("height")

    pixels = None
    if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
        pixels = width * height

    if quality == "lowest":
        size_key = size if isinstance(size, int) and size > 0 else 10**18
        pixel_key = pixels if isinstance(pixels, int) and pixels > 0 else 10**18
        return size_key, pixel_key, item["url"]

    size_key = size if isinstance(size, int) and size > 0 else -1
    pixel_key = pixels if isinstance(pixels, int) and pixels > 0 else -1
    return size_key, pixel_key, item["url"]


def extract_streams_by_quality(obj: Any, quality: QualityMode = "highest") -> List[Dict[str, Any]]:
    """从结构化 JSON 中按每个视频选择最高/最低流"""
    media_nodes: List[Dict[str, Any]] = []
    collect_media_nodes(obj, media_nodes)

    selected: List[Dict[str, Any]] = []
    for idx, media_node in enumerate(media_nodes, 1):
        stream_obj = media_node.get("stream")
        if not isinstance(stream_obj, dict):
            continue

        candidates: List[Dict[str, Any]] = []
        for codec, stream_list in stream_obj.items():
            if not isinstance(stream_list, list):
                continue
            for item in stream_list:
                if not isinstance(item, dict):
                    continue

                url = pick_stream_url(item)
                if not url:
                    continue

                candidates.append(
                    {
                        "group_id": media_group_id(media_node, idx),
                        "codec": str(codec),
                        "stream_type": item.get("streamType"),
                        "size": to_int(item.get("size")),
                        "width": to_int(item.get("width")),
                        "height": to_int(item.get("height")),
                        "url": url,
                    }
                )

        if not candidates:
            continue

        if quality == "lowest":
            best = min(candidates, key=lambda c: _stream_sort_key(c, quality="lowest"))
        else:
            best = max(candidates, key=lambda c: _stream_sort_key(c, quality="highest"))

        selected.append(best)

    # 再次去重，避免同一路径被多个节点重复引用
    deduped: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in selected:
        key = canonical_video_key(item["url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def extract_smallest_streams(obj: Any) -> List[Dict[str, Any]]:
    """兼容旧函数：按最低体积/分辨率选择"""
    return extract_streams_by_quality(obj, quality="lowest")


def collect_urls_from_obj(obj: Any, out: Set[str]) -> None:
    """递归提取 JSON 中所有 URL 值"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()

            if isinstance(v, str) and ("url" in key or "uri" in key):
                u = normalize_url(v)
                if u:
                    out.add(u)

            if isinstance(v, list) and ("url" in key or "uri" in key):
                for item in v:
                    if isinstance(item, str):
                        u = normalize_url(item)
                        if u:
                            out.add(u)

            collect_urls_from_obj(v, out)

    elif isinstance(obj, list):
        for item in obj:
            collect_urls_from_obj(item, out)

    elif isinstance(obj, str):
        u = normalize_url(obj)
        if u:
            out.add(u)


def collect_urls_from_text(raw_text: str) -> Set[str]:
    """JSON 解析失败时，从原始文本用正则兜底提取 URL"""
    urls = set()
    patterns = [
        r"https?:\\/\\/[^\s\"'\\]+",
        r"https?:\\u002F\\u002F[^\s\"'\\]+",
        r"https?://[^\s\"'\\]+",
    ]
    for p in patterns:
        for m in re.findall(p, raw_text):
            u = normalize_url(m)
            if u:
                urls.add(u)
    return urls


def build_filename(url: str, idx: int) -> str:
    parsed = urlparse(url)
    base = Path(unquote(parsed.path)).name

    if not base:
        base = f"video_{idx:03d}.mp4"

    # 文件名非法字符处理
    base = re.sub(r'[<>:"/\\|?*]+', "_", base)

    # 无后缀时补 .mp4
    if not any(base.lower().endswith(ext) for ext in VIDEO_EXTS):
        base += ".mp4"

    short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{idx:03d}_{short_hash}_{base}"


def download_one(
    url: str,
    save_path: Path,
    headers: Optional[Dict[str, str]] = None,
    timeout: Tuple[int, int] = TIMEOUT,
) -> Tuple[bool, str]:
    tmp_path = save_path.with_suffix(save_path.suffix + ".part")
    request_headers = headers or build_headers()

    for attempt in range(1, MAX_RETRIES + 1):
        downloaded = 0
        last_log_ts = 0.0
        start_ts = _time.time()
        try:
            req = Request(url=url, headers=request_headers)
            with urlopen(req, timeout=max(timeout)) as resp:
                total_bytes = int(resp.headers.get("Content-Length", "0") or 0)

                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = _time.time()
                        if now - last_log_ts >= PROGRESS_LOG_SECONDS:
                            if total_bytes > 0:
                                pct = downloaded * 100 / total_bytes
                                print(
                                    f"    进度 {pct:6.2f}% ({format_bytes(downloaded)}/{format_bytes(total_bytes)})",
                                    end="\r",
                                    flush=True,
                                )
                            else:
                                print(f"    已下载 {format_bytes(downloaded)}", end="\r", flush=True)
                            last_log_ts = now

            elapsed = max(_time.time() - start_ts, 1e-6)
            speed = downloaded / elapsed
            print(" " * 100, end="\r", flush=True)
            print(f"    完成 {format_bytes(downloaded)}，平均速度 {format_bytes(int(speed))}/s")
            tmp_path.replace(save_path)
            return True, ""
        except KeyboardInterrupt:
            print("\n⏹️ 收到中断信号，正在安全停止...")
            # 保留已有 .part 文件，避免重复下载大量已完成数据
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
            if tmp_path.exists() and tmp_path.stat().st_size == 0:
                tmp_path.unlink()
            if attempt < MAX_RETRIES:
                wait_s = RETRY_BACKOFF_SECONDS ** attempt
                print(f"    下载失败（第{attempt}/{MAX_RETRIES}次）：{e}；{wait_s}s 后重试...")
                _time.sleep(wait_s)
                continue
            return False, f"重试 {MAX_RETRIES} 次后失败：{e}"

    return False, "未知错误"


def extract_video_urls(
    raw_text: str,
    quality: QualityMode = "highest",
) -> ExtractSummary:
    """从原始文本中提取最终可下载视频 URL（按 quality 选择）"""
    q = normalize_quality(quality)
    all_urls: Set[str] = set()

    obj = try_load_json(raw_text)
    selected_streams: List[Dict[str, Any]] = []
    if obj is not None:
        collect_urls_from_obj(obj, all_urls)
        selected_streams = extract_streams_by_quality(obj, quality=q)

    # 正则兜底（有些文本不是完整 JSON）
    all_urls.update(collect_urls_from_text(raw_text))

    raw_video_urls: List[str] = sorted({u for u in all_urls if looks_like_video_url(u)})

    # 优先使用结构化 stream 的精确选择结果；没有则走通用去重兜底
    if selected_streams:
        video_urls = [x["url"] for x in selected_streams]
    else:
        video_urls = dedupe_video_urls(raw_video_urls)

    return ExtractSummary(
        all_url_count=len(all_urls),
        raw_video_candidate_count=len(raw_video_urls),
        selected_streams=selected_streams,
        video_urls=video_urls,
        quality=q,
    )


def print_extract_summary(summary: ExtractSummary) -> None:
    print(f"共提取到 URL: {summary.all_url_count}")
    if summary.selected_streams:
        print(
            f"其中视频 URL: {len(summary.video_urls)} "
            f"（按每个视频{('最低' if summary.quality == 'lowest' else '最高')}质量自动选择；"
            f"原始候选 {summary.raw_video_candidate_count}）"
        )
        for i, item in enumerate(summary.selected_streams, 1):
            size_txt = format_bytes(item["size"]) if item.get("size") else "未知"
            wh = ""
            if item.get("width") and item.get("height"):
                wh = f" {item['width']}x{item['height']}"
            print(
                f"  选择[{i}] {item.get('group_id', '-') } | codec={item.get('codec')} "
                f"| streamType={item.get('stream_type')} | size={size_txt}{wh}"
            )
    else:
        print(
            f"其中视频 URL: {len(summary.video_urls)} "
            f"（原始 {summary.raw_video_candidate_count}，"
            f"去重 {summary.raw_video_candidate_count - len(summary.video_urls)}）"
        )


def download_video_urls(
    video_urls: List[str],
    output_dir: Union[str, Path],
    cookie: str = "",
) -> DownloadSummary:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    headers = build_headers(cookie=cookie)
    success = 0
    total = len(video_urls)

    for i, url in enumerate(video_urls, 1):
        filename = build_filename(url, i)
        save_path = output_path / filename

        if save_path.exists() and save_path.stat().st_size > 0:
            print(f"[{i}/{total}] 已存在，跳过：{filename}")
            success += 1
            continue

        print(f"[{i}/{total}] 开始下载：{filename}")
        try:
            ok, err = download_one(url, save_path, headers=headers)
        except KeyboardInterrupt:
            print("\n⏹️ 任务已由用户中断，脚本安全退出。")
            break

        if ok:
            success += 1
            print(f"[{i}/{total}] 下载成功：{filename}")
        else:
            print(f"[{i}/{total}] 下载失败：{url}\n  原因：{err}")
            notify_failure(
                "视频下载失败",
                details=f"URL: {url}\n保存路径: {save_path}\n原因: {err}",
                dedupe_key=f"video-download|{url}",
            )

    return DownloadSummary(
        total=total,
        success=success,
        failed=max(total - success, 0),
        output_dir=output_path,
    )


def download_from_text(
    raw_text: str,
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME,
    quality: QualityMode = "highest",
    cookie: str = "",
) -> Dict[str, Any]:
    """从页面状态文本直接提取并下载视频"""
    summary = extract_video_urls(raw_text=raw_text, quality=quality)
    print_extract_summary(summary)

    if not summary.video_urls:
        print("未发现可下载的视频链接，请检查文本内容是否完整。")
        notify_failure_once(
            "视频链接提取失败",
            details=f"输出目录: {output_dir}\n原始文本长度: {len(raw_text)}",
        )
        return {
            "extract": summary,
            "download": DownloadSummary(total=0, success=0, failed=0, output_dir=Path(output_dir)),
        }

    download_summary = download_video_urls(
        video_urls=summary.video_urls,
        output_dir=output_dir,
        cookie=cookie,
    )
    print(f"\n完成：成功 {download_summary.success}/{download_summary.total}")
    print(f"下载目录：{download_summary.output_dir}")

    return {"extract": summary, "download": download_summary}


def download_from_notebook_output(
    notebook_path: Union[str, Path],
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME,
    quality: QualityMode = "highest",
    cookie: str = "",
) -> Dict[str, Any]:
    """从 .ipynb 的 code cell 输出中提取并下载视频"""
    nb_path = Path(notebook_path)
    raw_text = read_input_text(nb_path)
    print(f"输入来源：{nb_path}")
    return download_from_text(raw_text=raw_text, output_dir=output_dir, quality=quality, cookie=cookie)


def get_page_script_text(
    bro: Any,
    url: str,
    start_listen: bool = True,
    script_index: int = -6,
    wait_min: int = 3,
    wait_max: int = 5,
) -> str:
    """按你的流程进入页面，并取 script 内容"""
    if start_listen:
        try:
            bro.listen.start(url)
        except Exception:
            pass

    bro.get(url)
    try:
        bro.wait(wait_min, wait_max)
    except Exception:
        pass

    ele = bro.ele("tag=script", index=script_index).html
    if not isinstance(ele, str) or not ele.strip():
        raise ValueError("未获取到可解析的 script 文本，请调整 script_index 或检查页面是否加载完成。")
    return ele


def download_from_page(
    bro: Any,
    url: str,
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME,
    quality: QualityMode = "highest",
    start_listen: bool = True,
    script_index: int = -6,
    cookie: str = "",
) -> Dict[str, Any]:
    """在 Notebook 中直接用浏览器对象完成：打开页面 -> 提取 -> 下载"""
    q = normalize_quality(quality)
    try:
        script_text = get_page_script_text(
            bro=bro,
            url=url,
            start_listen=start_listen,
            script_index=script_index,
        )
    except Exception as exc:
        notify_failure(
            "视频页面解析失败",
            error=exc,
            details=f"URL: {url}\nscript_index: {script_index}",
            dedupe_key=f"video-page|{url}",
        )
        raise
    return download_from_text(
        raw_text=script_text,
        output_dir=output_dir,
        quality=q,
        cookie=cookie,
    )


def main(
    input_path: Union[str, Path] = DEFAULT_INPUT_PATH,
    output_dir: Optional[Union[str, Path]] = None,
    quality: QualityMode = "highest",
    cookie: str = "",
) -> None:
    """
    脚本入口：从文件读取后下载

    input_path 支持：
    - .ipynb（自动读取代码单元格输出）
    - 纯文本 / JSON 文件
    """
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"找不到文件：{input_file}")

    resolved_output = Path(output_dir) if output_dir else input_file.with_name(DEFAULT_OUTPUT_DIR_NAME)

    result = download_from_notebook_output(
        notebook_path=input_file,
        output_dir=resolved_output,
        quality=quality,
        cookie=cookie,
    ) if input_file.suffix.lower() == ".ipynb" else download_from_text(
        raw_text=read_input_text(input_file),
        output_dir=resolved_output,
        quality=quality,
        cookie=cookie,
    )

    print(f"输入来源：{input_file}")
    print(f"质量策略：{result['extract'].quality}")


if __name__ == "__main__":
    try:
        main(
            input_path=DEFAULT_INPUT_PATH,
            output_dir=None,
            quality="highest",
            cookie="",
        )
    except KeyboardInterrupt:
        print("\n程序已中断退出。")
