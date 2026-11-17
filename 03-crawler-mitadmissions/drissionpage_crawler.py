#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DrissionPage 版博客爬虫（与 playwright_crawler.py 相互独立）。

两条执行路径，均使用 DrissionPage 自身的元素 API：
  * 浏览器路径：ChromiumPage + ChromiumOptions（指定本机 Chrome、独立
    user-data 目录、headless），元素定位主要用 XPath，正文文本用
    elem.run_js('return this.innerText') 取渲染后的文本。
  * 降级路径：DrissionPage 的 SessionPage（自带 requests 封装）直接请求
    HTML，再用同一套 XPath 定位；正文改用 outerHTML + lxml 递归取文本，
    以保留段落换行。

浏览器起不来时（本沙箱的 Chromium 因命名管道被拒绝而崩溃），
--engine auto 会写 logs/drissionpage_browser_error.txt 并自动降级。

用法：
  python drissionpage_crawler.py
  python drissionpage_crawler.py --engine browser
  python drissionpage_crawler.py --engine session --max-articles 40
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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
    images_to_cell,
    now_iso,
    parse_comment_count,
    polite_sleep,
    strip_noise,
    write_csv,
    write_failures,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "csv", "drissionpage_blogs.csv")
FAIL_PATH = os.path.join(HERE, "logs", "drissionpage_failures.json")
META_PATH = os.path.join(HERE, "logs", "drissionpage_run.json")
ERR_PATH = os.path.join(HERE, "logs", "drissionpage_browser_error.txt")

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_TMP = r"D:\dsh-workplace\tmp"
PROFILE_DIR = os.path.join(BASE_TMP, "dp_profile_mitblogs")
TMP_DIR = os.path.join(BASE_TMP, "dp_tmp")
LOCAL_PORT = 9444

# 受限环境下系统 Temp 不可写，统一把临时目录指到工作区
for _env_key in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_env_key] = BASE_TMP
os.makedirs(BASE_TMP, exist_ok=True)

MAX_ATTEMPTS = 3

# XPath 定位器（与 Playwright 版的 CSS 策略形成对照）
XP_LIST_ITEM = "xpath://li[contains(@class,'tease-feed-item')]"
XP_LIST_LINK = "xpath:.//a[contains(@class,'post-tease__h__link')]"
XP_LIST_TITLE = "xpath:.//*[contains(@class,'post-tease__title')]"
XP_LIST_AUTHOR = "xpath:.//*[contains(@class,'post-tease__meta-item--author')]"
XP_LIST_DATE = "xpath:.//*[contains(@class,'tease__meta-item--date')]"
XP_H1 = "xpath://h1[contains(@class,'page-topper__title')]"
XP_H1_NAME = "xpath:.//*[contains(@class,'page-topper__title__name')]"
XP_TIME = "xpath://time[contains(@class,'page-topper__date')]"
# 注意：不能写 contains(@class,'article__body')，否则会先命中外层
# <div class="article__body-mod">（含页头日期、分类、tag、分享栏）。
# 这里用 class token 精确匹配真正的正文容器。
XP_BODY = "xpath://div[contains(concat(' ', normalize-space(@class), ' '), ' article__body ')]"
XP_DISQUS = "xpath://div[@id='disqus_thread']"


def find(parent, locator: str, timeout: float = 2.0):
    """统一 ele() 调用，兼容不同版本是否接受 timeout。"""
    try:
        return parent.ele(locator, timeout=timeout)
    except TypeError:
        return parent.ele(locator)


def find_all(parent, locator: str) -> list:
    try:
        return parent.eles(locator)
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------
# 页面解析（ChromiumPage / SessionPage 共用同一套元素定位）
# --------------------------------------------------------------------------
def parse_list(page) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for li in find_all(page, XP_LIST_ITEM):
        link = find(li, XP_LIST_LINK)
        if link is None:
            continue
        href = link.attr("href") or ""
        if not href:
            continue
        title_el = find(li, XP_LIST_TITLE)
        author_el = find(li, XP_LIST_AUTHOR)
        date_el = find(li, XP_LIST_DATE)
        author = clean_text(author_el.text if author_el is not None else "")
        items.append(
            {
                "url": href if href.startswith("http") else BASE_URL + href,
                "title": clean_text(title_el.text) if title_el is not None else "",
                "author": re.sub(r"^\s*by\s+", "", author, flags=re.I),
                "date": clean_text(date_el.text) if date_el is not None else "",
            }
        )
    return items


def parse_detail(page, mode: str) -> Dict[str, Any]:
    h1 = find(page, XP_H1)
    if h1 is None:
        raise RuntimeError("详情页缺少 page-topper__title")

    name_el = find(h1, XP_H1_NAME)
    author_raw = clean_text(name_el.text) if name_el is not None else ""
    title = clean_text(h1.text)
    if author_raw and author_raw in title:
        title = clean_text(title.replace(author_raw, "", 1))
    if not title:
        title = clean_text(h1.text)

    time_el = find(page, XP_TIME)
    when = ""
    if time_el is not None:
        when = time_el.attr("datetime") or clean_text(time_el.text)

    body = find(page, XP_BODY)
    content = ""
    images: List[str] = []
    if body is not None:
        if mode == "browser":
            try:
                content = body.run_js("return this.innerText")
            except Exception:  # noqa: BLE001
                content = body.text
            for img in find_all(body, "xpath:.//img"):
                for attr in ("data-flickity-lazyload-src", "data-lazy-src", "data-src", "src"):
                    value = img.attr(attr)
                    if value:
                        images.append(value)
                        break
        else:
            raw = body.html or ""
            try:
                el = lxml_html.fromstring(raw)
            except Exception:  # noqa: BLE001
                el = None
            if el is not None:
                strip_noise(el)
                content = element_text(el)
                for img in el.cssselect("img"):
                    for attr in ("data-flickity-lazyload-src", "data-lazy-src", "data-src", "src"):
                        value = img.get(attr)
                        if value:
                            images.append(value)
                            break
            else:
                content = body.text
        content = clean_text(content) if mode == "browser" else content

    disqus = find(page, XP_DISQUS)
    comments = clean_text(disqus.text) if disqus is not None else ""

    return {
        "title": title,
        "authorRaw": author_raw,
        "when": when,
        "comments": comments,
        "body": content,
        "images": filter_images(images),
    }


# --------------------------------------------------------------------------
# 浏览器模式
# --------------------------------------------------------------------------
def make_page(addr: str = ""):
    """addr 非空时连接已存在的浏览器（如父会话启动的 CDP 端口），否则自行启动 Chrome。"""
    from DrissionPage import ChromiumOptions, ChromiumPage

    if addr:
        page = ChromiumPage(addr)
        page.set.timeouts(base=10, page_load=45, script=20)
        return page

    options = ChromiumOptions()
    try:
        options.set_browser_path(CHROME_PATH)
    except Exception:  # noqa: BLE001
        pass
    # auto_port(False) 必须在 set_address 之前调用，否则地址会被自动端口覆盖
    options.auto_port(False)
    options.set_address(f"127.0.0.1:{LOCAL_PORT}")
    try:
        options.set_user_data_path(PROFILE_DIR)
    except Exception:  # noqa: BLE001
        pass
    try:
        options.set_tmp_path(TMP_DIR)
    except Exception:  # noqa: BLE001
        pass
    options.headless(True)
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-gpu")
    options.set_argument("--disable-blink-features", "AutomationControlled")
    options.set_argument("--no-first-run")
    options.set_argument("--no-default-browser-check")
    options.set_argument("--disable-dev-shm-usage")
    page = ChromiumPage(options)
    page.set.timeouts(base=10, page_load=45, script=20)
    return page


def crawl_browser(max_articles: int, max_pages: int, addr: str = "") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    started = time.time()
    page = make_page(addr)

    links: List[Dict[str, str]] = []
    seen = set()
    for page_no in range(1, max_pages + 1):
        url = LIST_URL if page_no == 1 else LIST_PAGE_URL.format(page=page_no)
        page.get(url)
        items = parse_list(page)
        if not items:
            print(f"[drissionpage] 列表页 {url} 无条目，停止翻页")
            break
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                links.append(item)
        print(f"[drissionpage] 列表第 {page_no} 页：{len(items)} 条，累计 {len(links)}")
        if len(links) >= max_articles:
            break
        polite_sleep()

    links = links[:max_articles]
    print(f"[drissionpage] 待抓详情 {len(links)} 篇")

    for index, item in enumerate(links, 1):
        url = item["url"]
        detail = None
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                page.get(url)
                page.wait.ele_displayed(XP_BODY, timeout=15)
                detail = parse_detail(page, "browser")
                page.wait(1.2)  # 等 Disqus 计数脚本
                detail = parse_detail(page, "browser")
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"[drissionpage] 第 {index} 篇第 {attempt} 次失败：{url} -> {last_error[:160]}")
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

        author = re.sub(r"^\s*by\s+", "", clean_text(detail["authorRaw"]), flags=re.I) or item["author"]
        rows.append(
            build_row(
                title=detail["title"] or item["title"],
                author=author,
                comment_count=parse_comment_count(detail["comments"]),
                when=detail["when"] or item["date"],
                content=detail["body"],
                images=detail["images"],
                url=url,
            )
        )
        print(
            f"[drissionpage] {index}/{len(links)} 正文 {len(rows[-1]['Article Content'])} 字，"
            f"图片 {len(detail['images'])} 张"
        )
        polite_sleep()

    try:
        page.quit()
    except Exception:  # noqa: BLE001
        pass

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
# SessionPage 模式
# --------------------------------------------------------------------------
def make_session():
    from DrissionPage import SessionPage

    page = SessionPage()
    # 注意：不要把 Referer 写进 set.headers。DrissionPage 4.1.1.4 的
    # SessionPage._make_response() 在 kwargs 无 headers 时会执行
    # kwargs['headers']['Referer']（此时是空 dict）→ KeyError: 'referer'。
    # 让 DrissionPage 自己按 self.url 推导 Referer 即可。
    page.set.headers(
        {
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    try:
        page.set.retry_times(MAX_ATTEMPTS - 1)
    except Exception:  # noqa: BLE001
        pass
    page.set.timeout(35)
    return page


def crawl_session(max_articles: int, max_pages: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    started = time.time()
    page = make_session()

    links: List[Dict[str, str]] = []
    seen = set()
    for page_no in range(1, max_pages + 1):
        url = LIST_URL if page_no == 1 else LIST_PAGE_URL.format(page=page_no)
        ok = False
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                page.get(url)
                ok = True
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"[drissionpage/session] 列表页失败（{attempt}）{url}: {last_error[:120]}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(1.5 * attempt)
        if not ok:
            failures.append({"url": url, "stage": "list", "error": last_error})
            break
        items = parse_list(page)
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                links.append(item)
        print(f"[drissionpage/session] 列表第 {page_no} 页：{len(items)} 条，累计 {len(links)}")
        if len(links) >= max_articles:
            break
        polite_sleep()

    links = links[:max_articles]
    print(f"[drissionpage/session] 待抓详情 {len(links)} 篇")

    for index, item in enumerate(links, 1):
        url = item["url"]
        detail = None
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                page.get(url)
                detail = parse_detail(page, "session")
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                print(f"[drissionpage/session] 第 {index} 篇第 {attempt} 次失败：{url} -> {last_error[:160]}")
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

        author = re.sub(r"^\s*by\s+", "", clean_text(detail["authorRaw"]), flags=re.I) or item["author"]
        rows.append(
            build_row(
                title=detail["title"] or item["title"],
                author=author,
                comment_count=parse_comment_count(detail["comments"]),
                when=detail["when"] or item["date"],
                content=detail["body"],
                images=detail["images"],
                url=url,
            )
        )
        print(
            f"[drissionpage/session] {index}/{len(links)} 正文 {len(rows[-1]['Article Content'])} 字，"
            f"图片 {len(detail['images'])} 张"
        )
        polite_sleep()

    meta = {
        "engine": "session",
        "started_at": now_iso(),
        "elapsed_sec": round(time.time() - started, 1),
        "articles": len(rows),
        "failures": len(failures),
        "median_content_len": content_median(rows),
    }
    return rows, failures, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="DrissionPage 抓取 mit admissions 博客")
    parser.add_argument("--engine", choices=["auto", "browser", "session"], default="auto")
    parser.add_argument("--max-articles", type=int, default=40)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--out", default=CSV_PATH)
    parser.add_argument("--addr", default="", help="连接已存在的浏览器 CDP 地址，如 127.0.0.1:9556")
    args = parser.parse_args()

    if args.engine == "browser":
        rows, failures, meta = crawl_browser(args.max_articles, args.pages, args.addr)
    elif args.engine == "session":
        rows, failures, meta = crawl_session(args.max_articles, args.pages)
    else:
        try:
            rows, failures, meta = crawl_browser(args.max_articles, args.pages, args.addr)
        except Exception as exc:  # noqa: BLE001
            print(f"[drissionpage] 浏览器模式不可用，降级到 SessionPage：{type(exc).__name__}: {exc}")
            with open(ERR_PATH, "w", encoding="utf-8") as fh:
                fh.write(f"{now_iso()}\n{type(exc).__name__}: {exc}\n")
            rows, failures, meta = crawl_session(args.max_articles, args.pages)

    write_csv(args.out, rows)
    write_failures(FAIL_PATH, failures)
    meta["csv"] = os.path.abspath(args.out)
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(
        f"[drissionpage] 完成：{meta['articles']} 行，失败 {meta['failures']} 条，"
        f"正文中位数 {meta['median_content_len']:.0f} 字，耗时 {meta['elapsed_sec']}s"
    )
    print(f"[drissionpage] CSV -> {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
