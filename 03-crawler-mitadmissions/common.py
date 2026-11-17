#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""两个爬虫共用的纯工具函数。

只放与"用什么浏览器/什么 HTTP 库"无关的东西：常量、文本清洗、
图片 URL 过滤、CSV 写出、失败记录、限速。抓取流程与解析逻辑
分别写在 playwright_crawler.py / drissionpage_crawler.py 里，
两条实现互不调用。
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

BASE_URL = "https://mitadmissions.org"
LIST_URL = BASE_URL + "/blogs/"
LIST_PAGE_URL = BASE_URL + "/blogs/page/{page}/"

CSV_HEADERS = [
    "Title",
    "Author",
    "Comment Count",
    "Time",
    "Article Content",
    "Images In Article",
    "Source URL",
]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 正文里的块级标签，提取纯文本时用来补换行
BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "figure", "figcaption", "table", "tr", "td", "th", "section",
    "article", "pre", "hr", "details", "summary",
}

# 正文里需要剔除的装饰性节点（划词注释气泡、分享栏、脚本）
NOISE_CLASSES = (
    "annotation",
    "annotation-mod",
    "annotation__number",
    "annotation-link",
    "share-mod",
    "share-item",
)

# 图片 URL 里出现这些片段就认为是头像/图标/统计像素，不是正文配图
BAD_IMAGE_PARTS = (
    "avatar", "gravatar", "/mug", "author-mug", "icon", "logo", "emoji",
    "spinner", "blank.gif", "pixel", "1x1", "spacer", "sprite", "loading",
)

IMAGE_ATTRS = (
    "data-flickity-lazyload-src",
    "data-lazy-src",
    "data-src",
    "src",
)


def clean_text(raw: Optional[str]) -> str:
    """压缩空白、去掉空行，保留段落换行。"""
    if not raw:
        return ""
    s = (
        raw.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def element_text(el: Any) -> str:
    """把 lxml 元素转成带换行的纯文本（stdlib 之外的零依赖实现）。"""
    if el is None:
        return ""
    chunks: List[str] = []

    def walk(node: Any) -> None:
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag in ("script", "style", "noscript"):
            return
        if tag in BLOCK_TAGS:
            chunks.append("\n")
        if node.text:
            chunks.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                chunks.append(child.tail)
        if tag in BLOCK_TAGS:
            chunks.append("\n")

    walk(el)
    return clean_text("".join(chunks))


def strip_noise(root: Any) -> None:
    """就地删除注释气泡、分享栏等非正文节点（lxml）。"""
    for el in root.xpath(
        ".//*[contains(@class,'annotation') or contains(@class,'share-') "
        "or self::script or self::style or self::noscript]"
    ):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def image_url_from_element(img: Any, base_url: str = BASE_URL) -> str:
    for attr in IMAGE_ATTRS:
        value = img.get(attr)
        if value and value.strip():
            return urljoin(base_url, value.strip())
    return ""


def is_content_image(url: str) -> bool:
    if not url or url.startswith("data:"):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    low = url.lower()
    if any(part in low for part in BAD_IMAGE_PARTS):
        return False
    return True


def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def filter_images(urls: Iterable[str]) -> List[str]:
    """去掉头像/图标/重复，保持正文出现顺序。"""
    return dedupe(u for u in urls if is_content_image(u))


def images_to_cell(urls: List[str]) -> str:
    """CSV 里用 " | " 分隔存图片列表，Excel 里也只是一格，且可直接数 URL。"""
    return " | ".join(urls)


def parse_comment_count(text: Optional[str]) -> int:
    if not text:
        return 0
    match = re.search(r"\d[\d,]*", text)
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0


def polite_sleep(low: float = 0.5, high: float = 1.0) -> None:
    time.sleep(random.uniform(low, high))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_HEADERS})


def write_failures(path: str, failures: List[Dict[str, Any]]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(failures, fh, ensure_ascii=False, indent=2)


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def content_median(rows: List[Dict[str, Any]]) -> float:
    import statistics

    lengths = [len(row.get("Article Content") or "") for row in rows]
    return float(statistics.median(lengths)) if lengths else 0.0


def build_row(
    title: str,
    author: str,
    comment_count: int,
    when: str,
    content: str,
    images: List[str],
    url: str,
) -> Dict[str, Any]:
    return {
        "Title": clean_text(title),
        "Author": clean_text(author),
        "Comment Count": int(comment_count or 0),
        "Time": (when or "").strip(),
        "Article Content": clean_text(content),
        "Images In Article": images_to_cell(images),
        "Source URL": url,
    }
