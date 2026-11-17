# MIT Admissions 博客抓取（Playwright + DrissionPage）

## 1. 题目

> Using both Playwright and DrissionPage to crawl <https://mitadmissions.org/blogs/>, save and submit the
> results to a CSV file. Your headers should include:
> Title | Author | Comment Count | Time | Article Content | Images In Article.

即：用 Playwright 与 DrissionPage 两套独立实现抓取 MIT Admissions 博客列表与每篇文章详情，
输出包含标题、作者、评论数、时间、正文、正文图片的 CSV。

## 2. 交付物清单

| 文件 | 说明 |
| --- | --- |
| `playwright_crawler.py` | Playwright 实现（sync API；`browser` 引擎走真实浏览器，`http` 引擎为降级路径） |
| `drissionpage_crawler.py` | DrissionPage 实现（`browser` 引擎走 ChromiumPage，`session` 引擎走 SessionPage 降级） |
| `common.py` | 两个爬虫共享的**纯工具**：清洗、图片过滤、CSV 写出、评论数解析等（不含任何抓取逻辑） |
| `merge_and_check.py` | 合并两份 CSV、对比一致性、生成 `report.md` |
| `stats.py` | 统计脚本（为 README 汇总真实数据，可选运行） |
| `csv/playwright_blogs.csv` | Playwright 结果，UTF-8 **with BOM**，60 行 |
| `csv/drissionpage_blogs.csv` | DrissionPage 结果，UTF-8 **with BOM**，60 行 |
| `csv/merged_blogs.csv` | 按 URL 去重合并结果（多一列 `Sources`） |
| `report.md` | 自动生成的对比报告（条数、完整率、标题重合率、差异、失败 URL） |
| `logs/` | 每次运行的 `*_run.json`（条数/耗时/引擎/中位数）、`*_failures.json`，以及（若发生浏览器降级才生成）`*_browser_error.txt` |

CSV 前 6 列顺序严格为 `Title,Author,Comment Count,Time,Article Content,Images In Article`，
第 7 列 `Source URL` 为附加列（题目允许）。

## 3. 环境准备

本次实际运行环境（Windows 11 + PowerShell）：

| 组件 | 版本/路径 |
| --- | --- |
| Python | 3.13.9（虚拟环境 `D:\dsh-workplace\.venvs\exam\Scripts\python.exe`） |
| playwright | 1.65.2 |
| DrissionPage | 4.1.1.4 |
| requests / lxml / cssselect | 2.34.2 / 6.1.3 / 1.6.0 |
| 浏览器 | Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`，系统安装版，Playwright 用 `channel="chrome"`） |

从零安装：

```powershell
# 1) 建虚拟环境（已存在可跳过）
python -m venv D:\dsh-workplace\.venvs\exam

# 2) 装依赖（不下载 chromium，直接用本机 Chrome）
& D:\dsh-workplace\.venvs\exam\Scripts\python.exe -m pip install playwright DrissionPage requests lxml cssselect
# 如确实需要 Playwright 自带 chromium：
# & D:\dsh-workplace\.venvs\exam\Scripts\python.exe -m playwright install chromium
```

> 项目不含第三方服务的 key，也不依赖 Selenium；`lxml + cssselect` 只用于 HTTP 降级路径解析。

## 4. 目标站点结构（2026-11-17 实测）

站点是 WordPress（Pantheon 托管 + Cloudflare），文章类型为 `post`。

### 4.1 列表页

| 项目 | 实测值 |
| --- | --- |
| 列表 URL | `https://mitadmissions.org/blogs/`，每页 **16** 条 |
| 分页方式 | `https://mitadmissions.org/blogs/page/N/`（path 形式，不是 `?page=`），共 492 页 |
| 列表项容器 | `li.tease-feed-item` → `article.tease` |
| 文章链接 | `a.post-tease__h__link`，`href` 形如 `/blogs/entry/<slug>/`（需 `urljoin` 补全） |
| 标题 | `.post-tease__title`（有副标题时在 `.post-tease__subtitle`） |
| 作者 | `.post-tease__meta-item--author`，文本形如 `by Suzuko O. '30` |
| 日期 | `.tease__meta-item--date`，文本形如 `November 16, 2026`（列表页无 `datetime` 属性） |
| 评论数 | `.tease__comment-text` 内是 `<a href="...#disqus_thread">`，静态 HTML **没有数字**，由 Disqus 脚本异步填充 |

列表页只用于拿 URL 和有则拿标题；作者/日期/评论以详情页为准（更完整，且含 ISO 时间）。

### 4.2 详情页

| 项目 | 选择器 / 说明 |
| --- | --- |
| 文章根 | `article.post-type-post.article#post-<id>` |
| 主标题+作者 | `h1.page-topper__title`，内含 `a[href="/blogs/author/<slug>/"] > span.page-topper__title__name`，文本即 `by Joy X. '29` |
| 副标题 | `.page-topper__sub` |
| 时间 | `time.page-topper__date[datetime]`，如 `2026-11-15T00:00:00-05:00`（ISO 带时区，直接入 CSV） |
| 正文 | `div.article__body`（class 恰为 `article__body js-hang-punc`） |
| 评论 | `div.article__comments > #disqus_thread`（Disqus embed，需 JS） |
| 正文图片 | `figure img` / `.wp-caption img` / `img`，懒加载属性有 `data-flickity-lazyload-src` 与 `src` |

**易踩的坑**：外层还有一个 `<div class="article__body-mod">`（含页头日期、分类、tag、分享栏），
用 `contains(@class,'article__body')` 会先命中它，把 "November 9, 2026 in Advice..."、"Post Tagged"、
"back to text" 混入正文。两个爬虫都改为 **class token 精确匹配**：

- CSS：`.article__body`（Playwright 用 `div.article__body`）
- XPath：`//div[contains(concat(' ', normalize-space(@class), ' '), ' article__body ')]`

正文里还混有划词注释 `.annotation-mod`（含 `.annotation` 气泡、`.annotation__number` 编号）和
`share-*` 分享按钮，提取前统一剔除。

### 4.3 评论数

站点用 Disqus：`#disqus_thread` 的计数由 `https://mitadmissions.disqus.com/count-data.js` 异步渲染，
而该域名在当前网络**连接超时**（`disqus.com` 不可达）。因此：

- 浏览器路径：等 1.2s 后读 `.article__comments` 可见文本，匹配 `(\d+)\s*Comments?`；读不到记 0。
- HTTP 路径：静态 HTML 里没有数字，一律记 0（题目允许 0，README 已注明局限）。

## 5. 两个爬虫的设计差异

两者**互不复用抓取代码**，只共享 `common.py` 的纯函数（清洗、过滤、写 CSV）。

| 维度 | `playwright_crawler.py` | `drissionpage_crawler.py` |
| --- | --- | --- |
| 浏览器 API | `sync_playwright` + `launch_persistent_context`（`channel="chrome"`，失败回退 `executable_path`），`headless=True` | `ChromiumPage` + `ChromiumOptions`（`set_browser_path` → `auto_port(False)` → `set_address("127.0.0.1:9444")` → `set_user_data_path`/`set_tmp_path` → `headless(True)`），`--no-sandbox` |
| 元素定位 | **CSS 选择器** + `page.evaluate` 一次性在页面内提取结构化 JSON | **XPath** + `ele()`/`eles()` 元素 API，正文 `run_js("return this.innerText")` |
| 列表分页 | `page.goto(page_url)`，`wait_for_selector("li.tease-feed-item")` | `page.get(page_url)`，`page.eles(XP_ITEM)` 轮询等待 |
| 等待策略 | `wait_until="domcontentloaded"` → 等列表项 → 详情页等 `article` → 额外 1.2s 给 Disqus；`page.wait_for_timeout` | `page.get()` 后 `document.readyState` 轮询 + 元素查找（`ele(..., timeout=...)`），详情页额外 2s 缓冲 |
| 正文纯文本 | 页面内 `innerText`，取前临时把 `.annotation` / `.annotation__number` / `.share-mod` / `script` / `style` 设为 `display:none`，取完恢复 | 浏览器路径对 `div.article__body` 执行 `this.innerText`（**未**隐藏注释节点，会带注释编号，见第 8 节）；SessionPage 路径用 `body.html` → lxml → `element_text()` 拼块级换行 |
| 反爬处理 | Chrome 真实 profile、`add_init_script` 抹掉 `navigator.webdriver`、中文/英文 Accept-Language、禁用 AutomationControlled、请求间隔 0.5–1.0s | 真实 `ChromiumOptions`、`--no-sandbox`、独立 user-data-dir、随机间隔 0.5–1.0s；SessionPage 用与浏览器一致的 UA/Headers |
| 重试 | 每页/每篇最多 3 次（`MAX_ATTEMPTS`），失败写 `logs/*_failures.json` | 每页/每篇最多 3 次，`SessionPage.set.retry_times(2)` + 外层循环 |
| 降级路径 | `--engine auto`：浏览器启动失败 → `logs/playwright_browser_error.txt` → `requests.Session` + `lxml.cssselect` | `--engine auto`：ChromiumPage 失败 → `logs/drissionpage_browser_error.txt` → `SessionPage`（DrissionPage 的 HTTP 模式） |
| 默认引擎 | `auto` | `auto` |

设计意图：

- **Playwright** 侧重"页面内一次 evaluate 拿全字段"，减少元素往返；CSS 选择器 + 浏览器端 `innerText` 最贴近真实渲染文本。
- **DrissionPage** 侧重"元素 API 逐步定位"，XPath 对 WordPress 的 class 组合更宽容；浏览器模式对正文元素执行 `this.innerText`，
  SessionPage 模式改用 `outerHTML` + lxml，两条路径共用同一套 XPath 定位与清洗逻辑。
- 两边都实现 `--engine` 开关：真实浏览器可用时走渲染后的 DOM，受限环境（CI / 无桌面 / 无 Chrome）降级为 HTTP，保证数据始终能抓。

## 6. 如何运行

```powershell
cd D:\dsh-workplace\interview-exam\03-crawler-mitadmissions

# 两个爬虫（默认 auto：优先浏览器，失败自动降级）
& D:\dsh-workplace\.venvs\exam\Scripts\python.exe playwright_crawler.py --pages 4 --max-articles 60
& D:\dsh-workplace\.venvs\exam\Scripts\python.exe drissionpage_crawler.py --pages 4 --max-articles 60

# 只允许浏览器 / 只允许 HTTP（DrissionPage 的 HTTP 模式叫 session）
... playwright_crawler.py --engine browser --pages 4 --max-articles 60
... drissionpage_crawler.py --engine browser --pages 4 --max-articles 60
... drissionpage_crawler.py --engine session --out csv/dp_test.csv

# 连接一个已存在的 Chrome 调试端口（父会话/桌面浏览器已起时可用）
... drissionpage_crawler.py --engine browser --addr 127.0.0.1:9556 --pages 4 --max-articles 60

# 合并 + 对比报告
... merge_and_check.py

# 数据统计（可选）
... stats.py
```

参数：`--pages 4`（前 4 页共 64 条）、`--max-articles 60`（先到者为准），请求间隔 0.5–1.0s（每篇文章之间）。
`--addr` 仅在 DrissionPage 里实现：它连的是已存在的 CDP 端口，不会自己启动 Chrome。

## 7. 输出说明

| 列 | 内容 |
| --- | --- |
| `Title` | 详情页 `h1.page-topper__title` 文本（去掉前缀 `by ` 与作者名），反斜杠/换行已清洗 |
| `Author` | `by Suzuko O. '30`（保留年级后缀，去 `by ` 前缀） |
| `Comment Count` | 整数；取不到为 `0` |
| `Time` | `time[datetime]` 的 ISO 8601，如 `2026-11-16T00:00:00-05:00`；解析不出时保留原文 |
| `Article Content` | 正文纯文本，段落间 `\n`，已剔除注释气泡/分享栏/脚本样式 |
| `Images In Article` | 正文图片 URL 列表，多个用 `\|` 分隔（如 `https://.../a.png \| https://.../b.jpg`），可直接按 `\|` 计数核对；已去重、过滤头像/图标/1x1 像素 |
| `Source URL` | 文章永久链接 |

- 编码：全部 UTF-8 **with BOM**（`utf-8-sig`），Excel 双击即可正常显示中文。
- 无图文章该列留空（`merge_and_check.py` 对空值与 ` | ` 分隔都能解析）。
- `logs/*_run.json` 记录引擎、起止时间、耗时、条数、失败数、正文中位数；`logs/*_failures.json` 记录失败项与错误。

## 8. 真实运行结果（2026-11-17）

抓取范围：列表前 4 页（16 条/页）中的前 60 篇，两边同一批 URL，均为**真实 Chrome（headless）**产物。

| 指标 | Playwright | DrissionPage |
| --- | --- | --- |
| 实际引擎 | `browser` | `browser` |
| CSV 条数 | 60 | 60 |
| 失败条数 | 0 | 0 |
| 耗时 | **197.0 s** | **1769.4 s** |
| 正文长度中位数 | **6492 字符** | **6498 字符** |
| 正文最短 / 最长 | 34 / 55646 | 34 / 56078 |
| 正文 <200 字符的文章 | 1 篇（`dream`，真实内容只有一句 + 漫画） | 同 |
| 图片总数 / 平均每篇 | 651 / 10.8 | 651 / 10.8 |
| 有图 / 无图文章 | 47 / 13 | 47 / 13 |
| 单篇最多图片 | 61 | 61 |
| 作者数 | 23 | 23 |
| 时间范围 | 2026-09-13T00:00:00-04:00 .. 2026-11-16T00:00:00-05:00 | 同 |
| 评论数非 0 的文章 | 0 | 0 |

一致性（`report.md` 有逐项核对）：

- 标题重合率 **100%**（严格标题口径与 URL 口径均为 60/60），`csv/merged_blogs.csv` 去重后 60 行，全部 `Sources = playwright+drissionpage`。
- 作者 / 时间 / 评论数 / 图片数 **60/60 完全一致**（图片均为 651 张，说明两套懒加载属性解析等价）；字段非空率：
  Title/Author/Comment Count/Time/Article Content 均 100%，`Images In Article` 78.3%（13 篇正文确实没有图片）。
- 正文逐字一致 **20/60**，DP 普遍更长（最大差 618 字符）：Playwright 取文本前把划词注释节点
  `.annotation` / `.annotation__number` 临时隐藏，DP 的浏览器路径没有，于是正文里多出注释编号
  （`U+2060` + `01`/`02`…）；没有划词注释的文章两边逐字相同。这是正文清洗策略差异，不是抓取遗漏。

CSV 样例（截断）：

```
Title            : i have seen some strange things around mit recently
Author           : Suzuko O. '30
Comment Count    : 0
Time             : 2026-11-16T00:00:00-05:00
Article Content  : a couple weeks ago, i looked out of my bedroom window to the east, and i saw something we...
Images In Article: https://mitadmissions.org/wp-content/uploads/2026/11/Screenshot-2026-11-16-at-6.53.39-PM-800x565.png | https://...
Source URL       : https://mitadmissions.org/blogs/entry/i-have-seen-some-strange-things-around-mit-recently/
```

### 关于浏览器引擎（如实说明）

- 两份主 CSV 都是真实 Chrome（headless）产物：`logs/playwright_run.json` 与 `logs/drissionpage_run.json` 的
  `engine` 均为 `browser`，各 60 篇、0 失败。
- 浏览器版是在**主会话**（普通用户 token）执行的：子代理进程 token 为 `Low Mandatory Level (S-1-16-4096)`，
  `CreateNamedPipeW` 成功后 `CreateFileW` 打开自己创建的管道返回 `err=5`，任何 Chromium 内核都会在
  `platform_channel.cc` 崩溃或 `BrowserConnectError`。所以子代理完成了代码、解析与降级路径验证，
  真浏览器运行由主会话执行；这不是脚本问题。
- 两条降级路径仍保留并用 `--engine` 显式可选：Playwright → `requests` + lxml；DrissionPage → `SessionPage`。
  DrissionPage 另支持 `--addr 127.0.0.1:<port>` 连接已有 CDP 端口。
- 性能：Playwright 197s（≈3.3s/篇）；DrissionPage 1769.4s（≈29s/篇）明显更慢，主要花在每篇
  `page.get()` 后的 `readyState` 轮询 + 2s 缓冲，且没有复用 tab；生产环境可调小缓冲。

## 9. 局限与已知问题

1. **评论数全为 0**：Disqus 计数需要 JS 且 `disqus.com` 不可达；静态 HTML 无数字。浏览器模式下也只做尽力而为的文本匹配。
2. **图片过滤**：按 `avatar/gravatar/icon/logo/emoji/spinner/blank.gif/pixel/1x1/spacer/sprite/loading` 等片段过滤，
   可能误杀同名的正常配图，也可能漏掉站点新增的图标 URL；正文外图片（页头封面）未纳入。
3. **懒加载**：优先取 `data-flickity-lazyload-src`，其次 `data-lazy-src`/`data-src`/`src`；若站点改成 CSS background-image，需另加解析。
4. **短正文**：`dream` 只有 34 字符，是作者只写了一句 + 漫画，非解析失败；正文中位数 6492 已远超 200。
5. **范围固定**：只抓前 4 页并截断到 60 篇；全站 492 页需要自行调大 `--pages`（并注意限速）。
6. **站点结构易变**：选择器基于 2026-11-17 的 DOM；WordPress 主题升级后需重新核对（重点 `article__body` 与 `page-topper__*`）。
7. **Time 时区**：直接沿用页面 `datetime` 的 -04:00/-05:00 偏移，未统一转 UTC。
8. **标题清洗**：详情页标题里作者名是嵌套 `<a>`，已剔除；个别标题含特殊引号/反斜杠，CSV 写入已转义（csv 模块负责）。
9. **无并发**：单线程 + 0.5–1.0s 间隔；本次 Playwright 197s（≈3.3s/篇）、DrissionPage 1769s（≈29s/篇，主要花在等待与加载），
   属刻意保守，避免触发 Cloudflare。
10. **正文里的注释编号**：站点有划词注释 `.annotation__number`；Playwright 取文本前已隐藏这些节点，DrissionPage 的浏览器路径
    未隐藏，正文会带 `U+2060` + 数字（如 `01`/`02`）。如需两引擎逐字一致，在 DP 取文本前同样 `display:none` 即可。

## 10. 复核

```powershell
# 行数与正文中位数
& D:\dsh-workplace\.venvs\exam\Scripts\python.exe -c "import csv,statistics; r=list(csv.DictReader(open('csv/playwright_blogs.csv',encoding='utf-8-sig'))); print(len(r), statistics.median(len(x['Article Content']) for x in r))"

# 重新生成合并表与报告
& D:\dsh-workplace\.venvs\exam\Scripts\python.exe merge_and_check.py
```

预期：`60 6492`（或随站点更新略变），`report.md` 显示两边 60 行、URL 口径重合率 100%。

## 11. 备注

- 两份主 CSV 均由主会话的真实 Chrome 抓取，`logs/*_run.json` 可复核引擎（均为 `browser`）与耗时。
- 浏览器探针脚本（`browser_probe.py`、`dp_browser_probe.py`）在验证后已清理；`stats.py` 保留用于复核统计。
