# -*- coding: utf-8 -*-
"""
小红书图片下载模块

流程：
1) 从页面输出文本（如 <script>window.__INITIAL_STATE__=...</script>）提取图片候选
2) 去除无效链接，按“同图不同分辨率”归并去重
3) 支持两种下载模式：
    - best：按每张图选择最高/最低分辨率
    - all：下载每张图的全部分辨率链接

支持输入来源：
- 原始文本（raw text）
- .ipynb 单元格输出
- DrissionPage 的浏览器对象 + url
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import hashlib
import shutil
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
DEFAULT_INPUT_PATH = Path("./image.json")
DEFAULT_OUTPUT_DIR_NAME = "image_downloads"
COOKIE = ""  # 如果遇到 403，可粘贴浏览器中的 cookie
# ===================================


TIMEOUT = (10, 60)          # (连接超时, 读取超时)
CHUNK_SIZE = 1024 * 1024    # 1MB
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".heic")
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
PROGRESS_LOG_SECONDS = 1.0
QualityMode = Literal["lowest", "highest", "none"]
ResolutionMode = Literal["best", "all"]

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
    raw_image_candidate_count: int
    selected_images: List[Dict[str, Any]]
    image_urls: List[str]
    quality: QualityMode
    resolution_mode: ResolutionMode


@dataclass
class DownloadSummary:
    total: int
    success: int
    failed: int
    output_dir: Path
    downloaded_success: int = 0
    removed_by_quality: int = 0
    group_count: int = 0
    high_count: int = 0
    low_count: int = 0
    high_dir: Optional[Path] = None
    low_dir: Optional[Path] = None


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

    if url.startswith("data:image/"):
        return None

    url = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), url)
    url = url.replace("\\/", "/")

    if url.startswith("http:/") and not url.startswith("http://"):
        url = url.replace("http:/", "http://", 1)
    if url.startswith("https:/") and not url.startswith("https://"):
        url = url.replace("https:/", "https://", 1)

    if not url.startswith(("http://", "https://")):
        return None

    return url


def looks_like_image_url(url: str) -> bool:
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    host_lower = parsed.netloc.lower()

    if any(path_lower.endswith(ext) for ext in IMAGE_EXTS):
        return True

    if "xhscdn.com" in host_lower and ("sns-webpic" in host_lower or "sns-img" in host_lower):
        if "notes_pre_post" in path_lower or "!nd_" in path_lower:
            return True

    if "format=webp" in url.lower() or "format=jpg" in url.lower() or "format=png" in url.lower():
        return True

    return False


def looks_like_note_image_url(url: str) -> bool:
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    host_lower = parsed.netloc.lower()

    if "xhscdn.com" not in host_lower:
        return False
    if "sns-webpic" not in host_lower and "sns-img" not in host_lower:
        return False

    return "notes_pre_post" in path_lower or "!nd_" in path_lower


def to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


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


def try_load_json(text: str) -> Optional[Any]:
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


def normalize_quality(quality: str) -> QualityMode:
    q = quality.strip().lower()
    if q not in {"lowest", "highest", "none"}:
        raise ValueError("quality 仅支持 'lowest'、'highest' 或 'none'")
    return q  # type: ignore[return-value]


def normalize_resolution_mode(mode: str) -> ResolutionMode:
    m = mode.strip().lower()
    if m not in {"best", "all"}:
        raise ValueError("resolution_mode 仅支持 'best' 或 'all'")
    return m  # type: ignore[return-value]


def extract_image_token_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if not path:
        return None

    last = path.rsplit("/", 1)[-1]
    last = last.split("!", 1)[0]
    stem = Path(last).stem.lower()

    if re.fullmatch(r"[0-9a-z]{20,}", stem):
        return stem
    return None


def canonical_image_key(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path).lower()

    token = extract_image_token_from_url(url)
    if token:
        return f"token:{token}"

    markers = ["/notes_pre_post/", "/notes_pre/", "/notes_post/"]
    for m in markers:
        if m in path:
            tail = path.split(m, 1)[1]
            tail = tail.split("!", 1)[0]
            seg = tail.rsplit("/", 1)[-1]
            if seg:
                return f"note:{seg}"
            return f"note:{tail}"

    base = path.split("!", 1)[0]
    return base


def dedupe_image_urls(urls: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: Set[str] = set()
    for u in urls:
        key = canonical_image_key(u)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(u)
    return deduped


def image_group_id(image_node: Dict[str, Any], idx: int) -> str:
    file_id = image_node.get("fileId")
    if isinstance(file_id, str) and file_id.strip():
        return f"fileId:{file_id.strip()}"

    for key in ("urlDefault", "urlPre", "url"):
        u = normalize_url(image_node.get(key))
        if u and looks_like_note_image_url(u):
            return canonical_image_key(u)

    info_list = image_node.get("infoList")
    if isinstance(info_list, list):
        for item in info_list:
            if not isinstance(item, dict):
                continue
            u = normalize_url(item.get("url"))
            if u and looks_like_note_image_url(u):
                return canonical_image_key(u)

    return f"image:{idx}"


def _scene_priority(scene: str, quality: QualityMode) -> int:
    s = (scene or "").upper()
    if quality == "highest":
        rank = {
            "WB_DFT": 6,
            "URL_DEFAULT": 5,
            "WB_ORI": 4,
            "WB_PRV": 3,
            "URL_PRE": 2,
            "URL": 1,
        }
    else:
        rank = {
            "WB_PRV": 1,
            "URL_PRE": 2,
            "URL": 3,
            "WB_DFT": 4,
            "URL_DEFAULT": 5,
            "WB_ORI": 6,
        }
    return rank.get(s, 99 if quality == "lowest" else 0)


def _nd_variant_priority(url: str, quality: QualityMode) -> int:
    """根据 !nd_* 后缀估算质量优先级"""
    lower = url.lower()

    # 常见类型：!nd_prv_* / !nd_dft_* / !nd_ori_*
    if quality == "highest":
        rank = {
            "nd_ori": 6,
            "nd_dft": 5,
            "nd_wg": 4,
            "nd_prv": 2,
            "nd_pre": 1,
        }
        default_rank = 0
    else:
        rank = {
            "nd_prv": 1,
            "nd_pre": 2,
            "nd_wg": 3,
            "nd_dft": 5,
            "nd_ori": 6,
        }
        default_rank = 99

    for k, v in rank.items():
        if k in lower:
            return v
    return default_rank


def _image_sort_key(item: Dict[str, Any], quality: QualityMode) -> Tuple[int, int, int, int, str]:
    width = item.get("width")
    height = item.get("height")
    pixels = None
    if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
        pixels = width * height

    scene_score = _scene_priority(str(item.get("scene", "")), quality)
    nd_score = _nd_variant_priority(item["url"], quality)

    if quality == "lowest":
        pixel_key = pixels if isinstance(pixels, int) else 10**18
        return pixel_key, scene_score, nd_score, len(item["url"]), item["url"]

    pixel_key = pixels if isinstance(pixels, int) else -1
    return pixel_key, scene_score, nd_score, len(item["url"]), item["url"]


def collect_image_nodes(obj: Any, out: List[Dict[str, Any]]) -> None:
    """递归收集 imageList 里的图片节点"""
    if isinstance(obj, dict):
        image_list = obj.get("imageList")
        if isinstance(image_list, list):
            for item in image_list:
                if isinstance(item, dict):
                    out.append(item)

        for v in obj.values():
            collect_image_nodes(v, out)

    elif isinstance(obj, list):
        for item in obj:
            collect_image_nodes(item, out)


def _collect_candidates_for_image_node(image_node: Dict[str, Any], idx: int) -> List[Dict[str, Any]]:
    width = to_int(image_node.get("width"))
    height = to_int(image_node.get("height"))
    group_id = image_group_id(image_node, idx)

    candidates: List[Dict[str, Any]] = []
    seen_url: Set[str] = set()

    def push_candidate(raw_url: Any, scene: str) -> None:
        u = normalize_url(raw_url)
        if not u:
            return
        if not looks_like_note_image_url(u):
            return
        if u in seen_url:
            return
        seen_url.add(u)
        candidates.append(
            {
                "group_id": group_id,
                "scene": scene,
                "width": width,
                "height": height,
                "url": u,
            }
        )

    info_list = image_node.get("infoList")
    if isinstance(info_list, list):
        for item in info_list:
            if not isinstance(item, dict):
                continue
            push_candidate(item.get("url"), str(item.get("imageScene") or "INFO"))

    push_candidate(image_node.get("urlDefault"), "URL_DEFAULT")
    push_candidate(image_node.get("urlPre"), "URL_PRE")
    push_candidate(image_node.get("url"), "URL")

    return candidates


def extract_images_by_quality(obj: Any, quality: QualityMode = "highest") -> List[Dict[str, Any]]:
    image_nodes: List[Dict[str, Any]] = []
    collect_image_nodes(obj, image_nodes)

    selected: List[Dict[str, Any]] = []

    for idx, image_node in enumerate(image_nodes, 1):
        candidates = _collect_candidates_for_image_node(image_node, idx)

        if not candidates:
            continue

        if quality == "lowest":
            best = min(candidates, key=lambda c: _image_sort_key(c, quality="lowest"))
        else:
            best = max(candidates, key=lambda c: _image_sort_key(c, quality="highest"))

        selected.append(best)

    deduped: List[Dict[str, Any]] = []
    seen_groups: Set[str] = set()
    for item in selected:
        g = item.get("group_id")
        if not isinstance(g, str):
            continue
        if g in seen_groups:
            continue
        seen_groups.add(g)
        deduped.append(item)

    return deduped


def extract_all_image_variants(obj: Any) -> List[Dict[str, Any]]:
    """提取每张图的所有分辨率链接（按 URL 去重，不做最佳筛选）"""
    image_nodes: List[Dict[str, Any]] = []
    collect_image_nodes(obj, image_nodes)

    all_candidates: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for idx, image_node in enumerate(image_nodes, 1):
        candidates = _collect_candidates_for_image_node(image_node, idx)
        for item in candidates:
            url = item.get("url")
            if not isinstance(url, str):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            all_candidates.append(item)

    return all_candidates


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


def extract_image_variants_by_token(raw_text: str, image_token: str) -> List[str]:
    """
    仅提取包含指定图片 token 的链接。

    image_token 示例：
    - 1040g3k031tetv5ubla0049v0hdt7b5utuhtgfa8
    - 1040g3k031tetv5ubla0049v0hdt7b5utuhtgfa8!nd_dft_wlteh_webp_3
    """
    token = image_token.strip()
    if not token:
        return []
    token = token.split("!", 1)[0]

    urls: Set[str] = set()
    obj = try_load_json(raw_text)
    if obj is not None:
        collect_urls_from_obj(obj, urls)
    urls.update(collect_urls_from_text(raw_text))

    result = [u for u in urls if token in u and looks_like_note_image_url(u)]
    return sorted(result)


def pick_best_image_variant(urls: List[str], quality: QualityMode = "highest") -> Optional[str]:
    """从同一张图的多个链接中选择最高/最低质量链接。"""
    if not urls:
        return None

    q = normalize_quality(quality)
    if q == "none":
        return urls[0]
    if q == "highest":
        return max(urls, key=lambda u: (_nd_variant_priority(u, "highest"), len(u), u))
    return min(urls, key=lambda u: (_nd_variant_priority(u, "lowest"), len(u), u))


def synthesize_quality_variants_from_known_url(known_url: str) -> List[str]:
    """
    根据已有链接尝试拼接不同 nd 质量后缀。
    注意：该方法只改后缀，不会改中间哈希目录，可能并不都可访问。
    """
    u = normalize_url(known_url)
    if not u:
        return []

    if "!nd_" not in u:
        return [u]

    variants = []
    for target in ("prv", "dft", "ori"):
        candidate = re.sub(r"!nd_[a-z]+", f"!nd_{target}", u, count=1)
        variants.append(candidate)

    # 去重保序
    dedup: List[str] = []
    seen: Set[str] = set()
    for x in variants:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup


def infer_image_extension(url: str) -> str:
    path_lower = urlparse(url).path.lower()
    for ext in IMAGE_EXTS:
        if path_lower.endswith(ext):
            return ext

    lower = url.lower()
    if "webp" in lower:
        return ".webp"
    if "png" in lower:
        return ".png"
    if "jpeg" in lower:
        return ".jpeg"
    if "jpg" in lower:
        return ".jpg"
    if "avif" in lower:
        return ".avif"

    return ".jpg"


def build_filename(url: str, idx: int) -> str:
    parsed = urlparse(url)
    raw_name = Path(unquote(parsed.path)).name
    base = raw_name.split("!", 1)[0] if raw_name else f"image_{idx:03d}"

    base = re.sub(r'[<>:"/\\|?*]+', "_", base)
    if not base:
        base = f"image_{idx:03d}"

    ext = infer_image_extension(url)
    if not base.lower().endswith(IMAGE_EXTS):
        base += ext

    short_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{idx:03d}_{short_hash}_{base}"


def build_group_folder_name(group_id: str) -> str:
    """将 group_id 转成可用目录名，避免非法字符和超长路径。"""
    gid = (group_id or "group").strip()
    label = gid.split(":", 1)[-1]
    label = re.sub(r'[^0-9a-zA-Z_\-]+', "_", label).strip("_")
    if not label:
        label = "group"
    if len(label) > 36:
        label = label[:36]

    short_hash = hashlib.md5(gid.encode("utf-8")).hexdigest()[:8]
    return f"{label}_{short_hash}"


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


def extract_image_urls(
    raw_text: str,
    quality: QualityMode = "highest",
    resolution_mode: ResolutionMode = "best",
) -> ExtractSummary:
    """从原始文本中提取最终可下载图片 URL（默认保留全分辨率候选，后续按下载文件大小筛选）"""
    q = normalize_quality(quality)
    mode = normalize_resolution_mode(resolution_mode)
    all_urls: Set[str] = set()

    obj = try_load_json(raw_text)
    selected_images: List[Dict[str, Any]] = []
    if obj is not None:
        collect_urls_from_obj(obj, all_urls)
        all_variants = extract_all_image_variants(obj)
        if all_variants:
            selected_images = all_variants
        elif mode == "best" and q != "none":
            selected_images = extract_images_by_quality(obj, quality=q if q in {"highest", "lowest"} else "highest")

    all_urls.update(collect_urls_from_text(raw_text))

    raw_image_urls: List[str] = sorted({u for u in all_urls if looks_like_note_image_url(u)})

    if selected_images:
        image_urls = [x["url"] for x in selected_images]
    else:
        image_urls = raw_image_urls if (mode == "all" or q == "none") else dedupe_image_urls(raw_image_urls)

    if not selected_images and image_urls:
        selected_images = [
            {
                "group_id": canonical_image_key(u),
                "scene": "RAW",
                "width": None,
                "height": None,
                "url": u,
            }
            for u in image_urls
        ]

    return ExtractSummary(
        all_url_count=len(all_urls),
        raw_image_candidate_count=len(raw_image_urls),
        selected_images=selected_images,
        image_urls=image_urls,
        quality=q,
        resolution_mode=mode,
    )


def print_extract_summary(summary: ExtractSummary) -> None:
    print(f"共提取到 URL: {summary.all_url_count}")
    if summary.selected_images:
        if summary.resolution_mode == "all":
            unique_groups = len({str(x.get("group_id", "")) for x in summary.selected_images})
            print(
                f"其中图片 URL: {len(summary.image_urls)} "
                f"（下载全部分辨率；覆盖图片数 {unique_groups}；"
                f"原始候选 {summary.raw_image_candidate_count}）"
            )
        else:
            print(
                f"其中图片 URL: {len(summary.image_urls)} "
                f"（先下载候选后再按文件大小分组筛选；原始候选 {summary.raw_image_candidate_count}）"
            )
        for i, item in enumerate(summary.selected_images, 1):
            wh = ""
            if item.get("width") and item.get("height"):
                wh = f" {item['width']}x{item['height']}"
            print(
                f"  选择[{i}] {item.get('group_id', '-') } | scene={item.get('scene')} | size={wh or '未知'}"
            )
    else:
        print(
            f"其中图片 URL: {len(summary.image_urls)} "
            f"（原始 {summary.raw_image_candidate_count}，"
            f"去重 {summary.raw_image_candidate_count - len(summary.image_urls)}）"
        )


def download_image_urls(
    image_urls: List[str],
    output_dir: Union[str, Path],
    quality: QualityMode = "none",
    selected_images: Optional[List[Dict[str, Any]]] = None,
    cookie: str = "",
) -> DownloadSummary:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    q = normalize_quality(quality)
    headers = build_headers(cookie=cookie)
    downloaded_success = 0
    total = len(image_urls)

    # 先下载到临时区，下载完成后再统一分拣
    run_tag = _time.strftime("%Y%m%d_%H%M%S")
    staging_dir = output_path / f"_all_downloads_{run_tag}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    url_to_group: Dict[str, str] = {}
    if selected_images:
        for item in selected_images:
            u = item.get("url")
            if not isinstance(u, str) or not u:
                continue
            gid_raw = item.get("group_id")
            gid = str(gid_raw) if isinstance(gid_raw, str) and gid_raw else canonical_image_key(u)
            url_to_group[u] = gid

    downloaded_items: List[Dict[str, Any]] = []

    for i, url in enumerate(image_urls, 1):
        filename = build_filename(url, i)
        group_id = url_to_group.get(url, canonical_image_key(url))
        save_path = staging_dir / filename

        if save_path.exists() and save_path.stat().st_size > 0:
            print(f"[{i}/{total}] 已存在，跳过：{staging_dir.name}/{filename}")
            downloaded_success += 1
            downloaded_items.append(
                {
                    "group_id": group_id,
                    "url": url,
                    "path": save_path,
                    "size": save_path.stat().st_size,
                }
            )
            continue

        print(f"[{i}/{total}] 开始下载：{staging_dir.name}/{filename}")
        try:
            ok, err = download_one(url, save_path, headers=headers)
        except KeyboardInterrupt:
            print("\n⏹️ 任务已由用户中断，脚本安全退出。")
            break

        if ok:
            downloaded_success += 1
            file_size = save_path.stat().st_size if save_path.exists() else 0
            downloaded_items.append(
                {
                    "group_id": group_id,
                    "url": url,
                    "path": save_path,
                    "size": file_size,
                }
            )
            print(f"[{i}/{total}] 下载成功：{staging_dir.name}/{filename}")
        else:
            print(f"[{i}/{total}] 下载失败：{url}\n  原因：{err}")
            notify_failure(
                "图片下载失败",
                details=f"URL: {url}\n保存路径: {save_path}\n原因: {err}",
                dedupe_key=f"image-download|{url}",
            )

    # 统一分拣到两个目录：高分辨率 / 低分辨率
    high_dir = output_path / "high_resolution"
    low_dir = output_path / "low_resolution"
    if high_dir.exists():
        shutil.rmtree(high_dir, ignore_errors=True)
    if low_dir.exists():
        shutil.rmtree(low_dir, ignore_errors=True)
    high_dir.mkdir(parents=True, exist_ok=True)
    low_dir.mkdir(parents=True, exist_ok=True)

    def move_into(target_dir: Path, src_item: Dict[str, Any]) -> bool:
        src = src_item.get("path")
        if not isinstance(src, Path) or not src.exists():
            return False
        gid = str(src_item.get("group_id", "group"))
        gid_hash = hashlib.md5(gid.encode("utf-8")).hexdigest()[:8]
        target_name = f"{gid_hash}__{src.name}"
        dst = target_dir / target_name
        if dst.exists():
            stem = dst.stem
            suffix = dst.suffix
            n = 1
            while True:
                cand = target_dir / f"{stem}_{n}{suffix}"
                if not cand.exists():
                    dst = cand
                    break
                n += 1
        src.rename(dst)
        return True

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in downloaded_items:
        grouped.setdefault(str(item["group_id"]), []).append(item)

    high_count = 0
    low_count = 0
    for gid, items in grouped.items():
        valid_items = [x for x in items if isinstance(x.get("size"), int) and int(x["size"]) > 0]
        if not valid_items:
            continue

        valid_items.sort(key=lambda x: (int(x["size"]), len(str(x.get("url", ""))), str(x.get("url", ""))))
        high_item = valid_items[-1]

        # 最大文件进 high_resolution
        if move_into(high_dir, high_item):
            high_count += 1

        # 其余进 low_resolution；若只有一个文件，则 low 不放
        for x in valid_items[:-1]:
            if move_into(low_dir, x):
                low_count += 1

    removed_by_quality = 0
    kept_after_filter = high_count + low_count

    if q == "highest":
        # 删除低分辨率目录
        if low_dir.exists():
            removed_by_quality = sum(1 for p in low_dir.rglob("*") if p.is_file())
            shutil.rmtree(low_dir, ignore_errors=True)
        kept_after_filter = high_count
        low_count = 0
        print(f"后置筛选：quality=highest，已删除 low_resolution，保留 high_resolution {high_count} 张")
    elif q == "lowest":
        # 删除高分辨率目录
        if high_dir.exists():
            removed_by_quality = sum(1 for p in high_dir.rglob("*") if p.is_file())
            shutil.rmtree(high_dir, ignore_errors=True)
        kept_after_filter = low_count
        high_count = 0
        print(f"后置筛选：quality=lowest，已删除 high_resolution，保留 low_resolution {low_count} 张")
    elif q == "none":
        print("后置筛选：quality=none，保留 high_resolution + low_resolution 两个目录。")

    # 清理临时下载目录
    if staging_dir.exists():
        for p in staging_dir.rglob("*"):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        shutil.rmtree(staging_dir, ignore_errors=True)

    print(f"目录输出：{output_path}")
    print(f"高分辨率目录：{high_dir}（文件数 {high_count}）")
    print(f"低分辨率目录：{low_dir}（文件数 {low_count}）")

    return DownloadSummary(
        total=total,
        success=max(kept_after_filter, 0),
        failed=max(total - downloaded_success, 0),
        output_dir=output_path,
        downloaded_success=downloaded_success,
        removed_by_quality=removed_by_quality,
        group_count=len(grouped),
        high_count=high_count,
        low_count=low_count,
        high_dir=high_dir,
        low_dir=low_dir,
    )


def download_from_text(
    raw_text: str,
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME,
    quality: QualityMode = "highest",
    resolution_mode: ResolutionMode = "best",
    cookie: str = "",
) -> Dict[str, Any]:
    """从页面状态文本直接提取并下载图片"""
    summary = extract_image_urls(
        raw_text=raw_text,
        quality=quality,
        resolution_mode=resolution_mode,
    )
    print_extract_summary(summary)

    if not summary.image_urls:
        print("未发现可下载的图片链接，请检查文本内容是否完整。")
        notify_failure_once(
            "图片链接提取失败",
            details=f"输出目录: {output_dir}\n原始文本长度: {len(raw_text)}",
        )
        return {
            "extract": summary,
            "download": DownloadSummary(total=0, success=0, failed=0, output_dir=Path(output_dir)),
        }

    download_summary = download_image_urls(
        image_urls=summary.image_urls,
        output_dir=output_dir,
        quality=summary.quality,
        selected_images=summary.selected_images,
        cookie=cookie,
    )
    print(
        f"\n完成：保留 {download_summary.success}/{download_summary.total}，"
        f"下载成功 {download_summary.downloaded_success}/{download_summary.total}，"
        f"后置删除 {download_summary.removed_by_quality}，"
        f"图片组 {download_summary.group_count}，"
        f"高分目录 {download_summary.high_count}，"
        f"低分目录 {download_summary.low_count}"
    )
    print(f"下载目录：{download_summary.output_dir}")

    return {"extract": summary, "download": download_summary}


def download_from_notebook_output(
    notebook_path: Union[str, Path],
    output_dir: Union[str, Path] = DEFAULT_OUTPUT_DIR_NAME,
    quality: QualityMode = "highest",
    resolution_mode: ResolutionMode = "best",
    cookie: str = "",
) -> Dict[str, Any]:
    """从 .ipynb 的 code cell 输出中提取并下载图片"""
    nb_path = Path(notebook_path)
    raw_text = read_input_text(nb_path)
    print(f"输入来源：{nb_path}")
    return download_from_text(
        raw_text=raw_text,
        output_dir=output_dir,
        quality=quality,
        resolution_mode=resolution_mode,
        cookie=cookie,
    )


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
    resolution_mode: ResolutionMode = "best",
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
            "图片页面解析失败",
            error=exc,
            details=f"URL: {url}\nscript_index: {script_index}",
            dedupe_key=f"image-page|{url}",
        )
        raise
    return download_from_text(
        raw_text=script_text,
        output_dir=output_dir,
        quality=q,
        resolution_mode=resolution_mode,
        cookie=cookie,
    )


def main(
    input_path: Union[str, Path] = DEFAULT_INPUT_PATH,
    output_dir: Optional[Union[str, Path]] = None,
    quality: QualityMode = "highest",
    resolution_mode: ResolutionMode = "best",
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
        resolution_mode=resolution_mode,
        cookie=cookie,
    ) if input_file.suffix.lower() == ".ipynb" else download_from_text(
        raw_text=read_input_text(input_file),
        output_dir=resolved_output,
        quality=quality,
        resolution_mode=resolution_mode,
        cookie=cookie,
    )

    print(f"输入来源：{input_file}")
    print(f"质量策略：{result['extract'].quality}")
    print(f"分辨率模式：{result['extract'].resolution_mode}")


if __name__ == "__main__":
    try:
        main(
            input_path=DEFAULT_INPUT_PATH,
            output_dir=None,
            quality="highest",
            resolution_mode="best",
            cookie="",
        )
    except KeyboardInterrupt:
        print("\n程序已中断退出。")
