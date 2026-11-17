# -*- coding: utf-8 -*-
"""临时统计：为 README 提供真实运行数据。"""
import csv
import json
import statistics


def img_count(cell):
    cell = (cell or "").strip()
    if not cell:
        return 0
    if cell.startswith("["):
        try:
            return len(json.loads(cell))
        except Exception:  # noqa: BLE001
            pass
    return len([p for p in cell.split("|") if p.strip()])

for name in ("playwright", "drissionpage"):
    rows = list(csv.DictReader(open(f"csv/{name}_blogs.csv", encoding="utf-8-sig")))
    lens = [len(r["Article Content"]) for r in rows]
    imgs = [img_count(r["Images In Article"]) for r in rows]
    authors = {r["Author"] for r in rows}
    times = sorted(r["Time"] for r in rows)
    comments = [int(r["Comment Count"]) for r in rows]
    print(f"== {name}: rows={len(rows)}")
    print(f"   content min/median/max = {min(lens)}/{statistics.median(lens):.0f}/{max(lens)}")
    print(f"   content <200 chars: {sum(1 for n in lens if n < 200)}")
    print(f"   images total={sum(imgs)} avg={sum(imgs)/len(imgs):.1f} with_image={sum(1 for n in imgs if n)} zero_img={sum(1 for n in imgs if not n)} max={max(imgs)}")
    print(f"   authors={len(authors)} comments_nonzero={sum(1 for c in comments if c)}")
    print(f"   time range: {times[0]} .. {times[-1]}")
    print(f"   empty fields: " + ", ".join(f"{f}={sum(1 for r in rows if not (r[f] or '').strip())}" for f in ["Title","Author","Comment Count","Time","Article Content","Images In Article"]))

merged = list(csv.DictReader(open("csv/merged_blogs.csv", encoding="utf-8-sig")))
print("== merged rows:", len(merged), "headers:", list(merged[0].keys()))
print("   sources:", {r["Sources"] for r in merged})

# 两侧逐字比较
pw = {r["Source URL"]: r for r in csv.DictReader(open("csv/playwright_blogs.csv", encoding="utf-8-sig"))}
dp = {r["Source URL"]: r for r in csv.DictReader(open("csv/drissionpage_blogs.csv", encoding="utf-8-sig"))}
common = set(pw) & set(dp)
same = sum(1 for u in common if pw[u]["Article Content"] == dp[u]["Article Content"])
print(f"== common urls {len(common)}, identical body {same}")
print("== sample merged row:")
r = merged[0]
print("  ", {k: (v[:80] + "...") if len(v) > 80 else v for k, v in r.items()})
