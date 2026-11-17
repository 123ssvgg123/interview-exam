# 抓取结果对比报告

目标站点：<https://mitadmissions.org/blogs/>；两个爬虫分别用 Playwright 与 DrissionPage 独立实现，按列表页顺序各抓取 60 篇（Playwright 引擎 = browser，DrissionPage 引擎 = browser）。

## 1. 条数与耗时

| 项目 | Playwright | DrissionPage |
| --- | --- | --- |
| CSV 行数 | 60 | 60 |
| 有效行（标题+正文非空） | 60 | 60 |
| 实际引擎 | browser | browser |
| 耗时（秒） | 197.0 | 1769.4 |
| 正文长度中位数（字符） | 6492 | 6498 |
| 失败条数 | 0 | 0 |

## 2. 字段完整率（非空单元格占比）

| 字段 | Playwright | DrissionPage |
| --- | --- | --- |
| Title | 100.0% | 100.0% |
| Author | 100.0% | 100.0% |
| Comment Count | 100.0% | 100.0% |
| Time | 100.0% | 100.0% |
| Article Content | 100.0% | 100.0% |
| Images In Article | 78.3% | 78.3% |

> `Comment Count` 只要抓到数字就算完整，取不到时写 0（站点用 Disqus，计数脚本常被墙）。

## 3. 标题重合率

- Playwright 抓到 60 个不同标题，DrissionPage 抓到 60 个。
- 严格标题口径：交集 60 个，并集 60 个，重合率 **100.0%**（交集/较小集合 100.0%）。
- URL 口径：并集 60 篇，交集 60 篇，重合率 **100.0%**。

## 4. 一致性核对与差异样例

- 按 URL 对齐 60 篇：正文逐字一致：20/60；作者一致：60/60；时间一致：60/60；评论数一致：60/60；图片数一致：60/60。
- 正文长度最大差值：618 字符。
- 差异来源：两边都取渲染后的 `innerText`，但 Playwright 在取文本前先把 `.annotation` / `.annotation__number` / `.share-mod` / 脚本样式临时 `display:none`；DrissionPage 的浏览器路径直接对 `div.article__body` 取 `this.innerText`，于是 DP 正文会多出划词注释的编号（`U+2060` + `01`/`02`…），长度普遍多 200–600 字符。没有划词注释的文章两边逐字一致（本次 20/60）；作者、时间、评论数、图片数不受影响。

抽样核对（正文长度差最大的 5 条，差值为 0 表示逐字相同）：

| 标题 | 正文长度 PW / DP | 图片数 PW / DP | 评论 PW / DP | 作者是否一致 | 时间是否一致 |
| --- | --- | --- | --- | --- | --- |
| [Classes I’m Taking My Freshman Fall!(And Other Things Too)](https://mitadmissions.org/blogs/entry/classes-im-taking-my-freshman-falland-other-things-too/) | 7602 / 8220 | 2 / 2 | 0 / 0 | 是 | 是 |
| [my “first” “week” of “classes” at mit](https://mitadmissions.org/blogs/entry/my-first-week-of-classes-at-mit/) | 19377 / 19872 | 7 / 7 | 0 / 0 | 是 | 是 |
| [Something to believe in](https://mitadmissions.org/blogs/entry/something-to-believe-in/) | 55646 / 56078 | 58 / 58 | 0 / 0 | 是 | 是 |
| [good things come to those who wait](https://mitadmissions.org/blogs/entry/good-things-come-to-those-who-wait/) | 9670 / 9958 | 4 / 4 | 0 / 0 | 是 | 是 |
| [HUGE dormspam haul!!!](https://mitadmissions.org/blogs/entry/huge-dormspam-haul/) | 13022 / 13298 | 7 / 7 | 0 / 0 | 是 | 是 |

## 5. 失败 URL 列表

两个爬虫在本次运行中都没有失败项（每次失败会重试 2 次）。

## 6. 合并结果

- `csv/merged_blogs.csv` 共 **60** 行（按 Source URL 去重，额外 `Sources` 列标记来源）。
- 两边都抓到的文章：60 篇；仅一边抓到：0 篇。
