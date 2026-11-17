#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Playwright 版博客爬虫。

流程：
  1. 打开 https://mitadmissions.org/blogs/ 以及 /blogs/page/2/、/blogs/page/3/，
     用 DOM 选择器收集文章条目（URL / 标题 / 作者 / 日期 / 评论数占位）。
  2. 逐篇打开详情页，等待 div.article__body 出现，用 page.evaluate 取
     标题、作者、time[datetime]、#disqus_thread 文本、正文 innerText、正文图片。
  3. 每篇之间随机 sleep 0.5~1.0s；单篇失败重试 2 次，仍失败则记入
     logs/playwright_failures.json。

浏览器不可用时（例如受限沙箱里 Chromium 的命名管道被拒绝），
--engine auto 会打印原因并降级到 HTTP 模式（requests + lxml），
保证 CSV 仍能产出真实数据。--engine browser 则强制要求浏览器。

用法：
  python playwright_crawler.py                 # auto，优先浏览器
  python playwright_crawler.py --engine http   # 只用 HTTP
  python playwright_crawler.py --engine browser --max-articles 40
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from lxml import html as lxml_html

from common import (
    BASE_URL,
    CSV_HEADERS,
    DEFAULT_UA,
    LIST_PAGE_URL,
    LIST_URL,
    build_row,
    clean_text,
    content_median,
    element_text,
    filter_images,
    image_url_from_element,
    now_iso,
    parse_comment_count,
    polite_sleep,
    strip_noise,
    write_csv,
    write_failures,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "csv", "playwright_blogs.csv")
FAIL_PATH = os.path.join(HERE, "logs", "playwright_failures.json")
META_PATH = os.path.join(HERE, "logs", "playwright_run.json")

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TMP_DIR = r"D:\dsh-workplace\tmp"
PROFILE_DIR = os.path.join(TMP_DIR, "pw_profile_mitblogs")

# 受限环境下系统 Temp 不可写（node 驱动 mkdtemp 报 EPERM），统一把临时目录指到工作区
for _env_key in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_env_key] = TMP_DIR
os.makedirs(TMP_DIR, exist_ok=True)

MAX_ATTEMPTS = 3  # 首次 + 2 次重试


# --------------------------------------------------------------------------
# 浏览器模式
# --------------------------------------------------------------------------
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]

LIST_JS = """
() => Array.from(document.querySelectorAll('li.tease-feed-item')).map(li => {
  const a = li.querySelector('a.post-tease__h__link');
  const title = li.querySelector('.post-tease__title');
  const author = li.querySelector('.post-tease__meta-item--author');
  const date = li.querySelector('.tease__meta-item--date');
  return {
    url: a ? a.href : '',
    title: title ? title.textContent.trim() : '',
    author: author ? author.textContent.replace(/^\\s*by\\s+/i, '').trim() : '',
    date: date ? date.textContent.trim() : ''
  };
}).filter(item => item.url)
"""

DETAIL_JS = """
() => {
  const h1 = document.querySelector('h1.page-topper__title');
  if (!h1) return null;
  const nameEl = h1.querySelector('.page-topper__title__name');
  const authorRaw = nameEl ? nameEl.textContent.trim() : '';
  let title = h1.textContent || '';
  if (nameEl) title = title.replace(nameEl.textContent, '');
  title = title.replace(/\\s+/g, ' ').trim();
  const timeEl = document.querySelector('time.page-topper__date');
  const when = timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '';
  const thread = document.getElementById('disqus_thread');
  const comments = thread ? (thread.innerText || '').trim() : '';
  return {title: title, authorRaw: authorRaw, when: when, comments: comments};
}
"""

BODY_JS = """
() => {
  const body = document.querySelector('div.article__body');
  if (!body) return '';
  const hidden = [];
  const sel = '.annotation, .annotation__number, .annotation-link, .share-mod, script, style, noscript';
  body.querySelectorAll(sel).forEach(el => {
    hidden.push([el, el.style.display]);
    el.style.display = 'none';
  });
  const text = body.innerText || '';
  hidden.forEach(pair => { pair[0].style.display = pair[1]; });
  return text;
}
"""

IMAGES_JS = """
() => Array.from(document.querySelectorAll('div.article__body img')).map(img => {
  return img.getAttribute('data-flickity-lazyload-src')
      || img.getAttribute('data-lazy-src')
      || img.getAttribute('data-src')
      || img.currentSrc
      || img.src
      || '';
})
"""


def launch_browser(playwright):
    """优先用本机 Chrome（channel），失败再退回 executable_path。"""
    errors = []
    for kwargs in (
        {"channel": "chrome"},
        {"executable_path": CHROME_PATH},
    ):
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=True,
                args=LAUNCH_ARGS,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
                **kwargs,
            )
            return context
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{kwargs}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Playwright 启动 Chromium 失败：\n" + "\n".join(errors))


def crawl_browser(max_articles: int, max_pages: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    started = time.time()

    with sync_playwright() as p:
        context = launch_browser(p)
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        links: List[Dict[str, str]] = []
        seen = set()
        for page_no in range(1, max_pages + 1):
            url = LIST_URL if page_no == 1 else LIST_PAGE_URL.format(page=page_no)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("li.tease-feed-item", timeout=15000)
            except Exception:
                print(f"[playwright] 列表页 {url} 没有条目，停止翻页")
                break
            items = page.evaluate(LIST_JS)
            for item in items:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    links.append(item)
            print(f"[playwright] 列表第 {page_no} 页：{len(items)} 条，累计 {len(links)}")
            if len(links) >= max_articles:
                break
            polite_sleep()

        links = links[:max_articles]
        print(f"[playwright] 待抓详情 {len(links)} 篇")

        for index, item in enumerate(links, 1):
            url = item["url"]
            last_error = ""
            detail = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_selector("div.article__body", timeout=20000)
                    detail = page.evaluate(DETAIL_JS)
                    if not detail:
                        raise RuntimeError("详情页缺少 h1.page-topper__title")
                    # 给 Disqus 的 count.js 一点加载时间；拿不到就是 0
                    page.wait_for_timeout(1200)
                    detail = page.evaluate(DETAIL_JS)
                    body_text = page.evaluate(BODY_JS)
                    raw_images = page.evaluate(IMAGES_JS)
                    detail["body"] = body_text
                    detail["images"] = raw_images
                    last_error = ""
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
                    print(f"[playwright] 第 {index} 篇第 {attempt} 次失败：{url} -> {last_error[:160]}")
                    if attempt < MAX_ATTEMPTS:
                        time.sleep(1.5 * attempt)

            if detail is None:
                failures.append(
                    {
                        "url": url,
                        "list_title": item.get("title", ""),
                        "stage": "detail",
                        "error": last_error,
                        "attempts": MAX_ATTEMPTS,
                    }
                )
                polite_sleep()
                continue

            author = clean_text(detail.get("authorRaw", ""))
            author = re.sub(r"^\s*by\s+", "", author, flags=re.I)
            if not author:
                author = clean_text(item.get("author", ""))

            title = clean_text(detail.get("title", "")) or clean_text(item.get("title", ""))
            when = clean_text(detail.get("when", "")) or clean_text(item.get("date", ""))
            comments = parse_comment_count(detail.get("comments", ""))
            images = filter_images(detail.get("images", []))

            rows.append(
                build_row(
                    title=title,
                    author=author,
                    comment_count=comments,
                    when=when,
                    content=detail.get("body", ""),
                    images=images,
                    url=url,
                )
            )
            print(
                f"[playwright] {index}/{len(links)} 正文 {len(rows[-1]['Article Content'])} 字，"
                f"图片 {len(images)} 张"
            )
            polite_sleep()

        context.close()

    meta = {
        "engine": "browser",
        "started_at": now_iso(),
        "elapsed_sec": round(time.time() - started, 1),
        "articles": len(rows),
        "failures": len(failures),
        "median_content_len": content_median(rows),
    }
    return rows, failures, meta


# --------------------------------------------------------------------------
# HTTP 降级模式（requests + lxml.cssselect）
# --------------------------------------------------------------------------
def http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": LIST_URL,
            "Connection": "keep-alive",
        }
    )
    session.verify = False
    return session


def fetch_html(session: requests.Session, url: str) -> str:
    last: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = session.get(url, timeout=35)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[playwright/http] GET 失败（{attempt}/{MAX_ATTEMPTS}）{url}: {type(exc).__name__}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"GET 失败 {url}: {last}")


def parse_list_css(doc, page_no: int) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for li in doc.cssselect("li.tease-feed-item"):
        link = li.cssselect("a.post-tease__h__link")
        if not link:
            continue
        href = link[0].get("href") or ""
        if not href:
            continue
        title_el = li.cssselect(".post-tease__title")
        author_el = li.cssselect(".post-tease__meta-item--author")
        date_el = li.cssselect(".tease__meta-item--date")
        items.append(
            {
                "url": href if href.startswith("http") else BASE_URL + href,
                "title": clean_text(title_el[0].text_content()) if title_el else "",
                "author": re.sub(
                    r"^\s*by\s+", "", clean_text(author_el[0].text_content()), flags=re.I
                )
                if author_el
                else "",
                "date": clean_text(date_el[0].text_content()) if date_el else "",
            }
        )
    return items


def parse_detail_css(doc) -> Dict[str, Any]:
    h1 = doc.cssselect("h1.page-topper__title")
    if not h1:
        raise RuntimeError("详情页缺少 h1.page-topper__title")
    h1_el = h1[0]
    name_el = h1_el.cssselect(".page-topper__title__name")
    author_raw = clean_text(name_el[0].text_content()) if name_el else ""
    title = clean_text(h1_el.text_content())
    if author_raw:
        title = clean_text(title.replace(author_raw, "", 1))
    if not title:
        title = clean_text(h1_el.text_content())

    time_el = doc.cssselect("time.page-topper__date")
    when = ""
    if time_el:
        when = time_el[0].get("datetime") or clean_text(time_el[0].text_content())

    body = doc.cssselect("div.article__body")
    content = ""
    images: List[str] = []
    if body:
        strip_noise(body[0])
        content = element_text(body[0])
        images = filter_images(
            image_url_from_element(img) for img in body[0].cssselect("img")
        )

    thread = doc.cssselect("#disqus_thread")
    comment_text = clean_text(thread[0].text_content()) if thread else ""

    return {
        "title": title,
        "authorRaw": author_raw,
        "when": when,
        "comments": comment_text,
        "body": content,
        "images": images,
    }


def crawl_http(max_articles: int, max_pages: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    started = time.time()
    session = http_session()

    links: List[Dict[str, str]] = []
    seen = set()
    for page_no in range(1, max_pages + 1):
        url = LIST_URL if page_no == 1 else LIST_PAGE_URL.format(page=page_no)
        try:
            doc = lxml_html.fromstring(fetch_html(session, url))
        except Exception as exc:  # noqa: BLE001
            failures.append({"url": url, "stage": "list", "error": f"{type(exc).__name__}: {exc}"})
            print(f"[playwright/http] 列表页失败 {url}: {exc}")
            break
        items = parse_list_css(doc, page_no)
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                links.append(item)
        print(f"[playwright/http] 列表第 {page_no} 页：{len(items)} 条，累计 {len(links)}")
        if len(links) >= max_articles:
            break
        polite_sleep()

    links = links[:max_articles]
    print(f"[playwright/http] 待抓详情 {len(links)} 篇")

    for index, item in enumerate(links, 1):
        url = item["url"]
        detail = None
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                doc = lxml_html.fromstring(fetch_html(session, url))
                detail = parse_detail_css(doc)
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"[playwright/http] 第 {index} 篇第 {attempt} 次失败：{url} -> {last_error[:160]}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(1.5 * attempt)

        if detail is None:
            failures.append(
                {
                    "url": url,
                    "list_title": item.get("title", ""),
                    "stage": "detail",
                    "error": last_error,
                    "attempts": MAX_ATTEMPTS,
                }
            )
            polite_sleep()
            continue

        author = re.sub(r"^\s*by\s+", "", clean_text(detail.get("authorRaw", "")), flags=re.I)
        if not author:
            author = item.get("author", "")
        rows.append(
            build_row(
                title=detail.get("title") or item.get("title", ""),
                author=author,
                comment_count=parse_comment_count(detail.get("comments", "")),
                when=detail.get("when") or item.get("date", ""),
                content=detail.get("body", ""),
                images=detail.get("images", []),
                url=url,
            )
        )
        print(
            f"[playwright/http] {index}/{len(links)} 正文 {len(rows[-1]['Article Content'])} 字，"
            f"图片 {len(detail.get('images', []))} 张"
        )
        polite_sleep()

    meta = {
        "engine": "http",
        "started_at": now_iso(),
        "elapsed_sec": round(time.time() - started, 1),
        "articles": len(rows),
        "failures": len(failures),
        "median_content_len": content_median(rows),
    }
    return rows, failures, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright 抓取 mit admissions 博客")
    parser.add_argument("--engine", choices=["auto", "browser", "http"], default="auto")
    parser.add_argument("--max-articles", type=int, default=40)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--out", default=CSV_PATH)
    args = parser.parse_args()

    if args.engine == "browser":
        rows, failures, meta = crawl_browser(args.max_articles, args.pages)
    elif args.engine == "http":
        rows, failures, meta = crawl_http(args.max_articles, args.pages)
    else:
        # auto：先试浏览器，失败降级 HTTP。
        # sync_playwright() 启动失败时，playwright 内部的 asyncio Future 会在
        # 垃圾回收阶段往 stderr 打一段 "Future exception was never retrieved"，
        # 这里把 stderr 临时接管，并在块内主动 gc，避免污染终端输出。
        err: Optional[Exception] = None
        sink = io.StringIO()
        with contextlib.redirect_stderr(sink):
            try:
                rows, failures, meta = crawl_browser(args.max_articles, args.pages)
            except Exception as exc:  # noqa: BLE001
                err = exc
                gc.collect()
        if err is not None:
            print(f"[playwright] 浏览器模式不可用，降级到 HTTP：{type(err).__name__}: {err}")
            with open(
                os.path.join(HERE, "logs", "playwright_browser_error.txt"), "w", encoding="utf-8"
            ) as fh:
                fh.write(f"{now_iso()}\n{type(err).__name__}: {err}\n")
                tail = sink.getvalue().strip().splitlines()[-12:]
                if tail:
                    fh.write("\n--- playwright stderr (tail) ---\n" + "\n".join(tail) + "\n")
            rows, failures, meta = crawl_http(args.max_articles, args.pages)

    write_csv(args.out, rows)
    write_failures(FAIL_PATH, failures)
    meta["csv"] = os.path.abspath(args.out)
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(
        f"[playwright] 完成：{meta['articles']} 行，失败 {meta['failures']} 条，"
        f"正文中位数 {meta['median_content_len']:.0f} 字，耗时 {meta['elapsed_sec']}s"
    )
    print(f"[playwright] CSV -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
