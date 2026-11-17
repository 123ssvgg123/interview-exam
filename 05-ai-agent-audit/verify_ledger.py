# -*- coding: utf-8 -*-
from openpyxl import load_workbook

path = r"D:\dsh-workplace\interview-exam\05-ai-agent-audit\task-package\restaurant-portfolio-traffic-change-audit\rollouts\rollout-01.xlsx"
wv = load_workbook(path, data_only=True)

def leaves(sheet):
    ws = wv[sheet]
    rows = []
    for r in range(4, 22):
        rows.append((ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 3).value,
                     ws.cell(r, 4).value, ws.cell(r, 5).value or 0, ws.cell(r, 6).value or 0,
                     ws.cell(r, 7).value))
    return rows

def status_norm(s):
    return {"持续经营": "持续经营", "新开": "新开门店", "关闭": "关闭门店"}[s]

for sheet, prev, cur in (("源台账_2024", 2023, 2024), ("源台账_2025", 2024, 2025)):
    rows = leaves(sheet)
    print("==", sheet)
    print("  sum prev=%s cur=%s  (stated total prev=%s cur=%s)" % (
        sum(r[5] for r in rows), sum(r[4] for r in rows),
        wv[sheet]["F22"].value, wv[sheet]["E22"].value))
    # per store
    stores = {}
    for name, biz, seg, st, cv, pv, yoy in rows:
        stores.setdefault(name, {"st": set(), "p": 0, "c": 0, "segs": {}})
        stores[name]["st"].add(status_norm(st))
        stores[name]["p"] += pv; stores[name]["c"] += cv
        stores[name]["segs"][seg] = (pv, cv)
    for n, d in stores.items():
        print("   %s st=%s prev=%s cur=%s delta=%s segs=%s" % (
            n, "|".join(sorted(d["st"])), d["p"], d["c"], d["c"] - d["p"], d["segs"]))
    # meal segments
    for seg in ("早餐", "午餐", "晚餐"):
        p = sum(r[5] for r in rows if r[2] == seg)
        c = sum(r[4] for r in rows if r[2] == seg)
        comp = {}
        for r in rows:
            if r[2] == seg:
                k = status_norm(r[3])
                comp[k] = comp.get(k, 0) + (r[4] - r[5] if k == "持续经营" else (r[4] if k == "新开门店" else -r[5]))
        print("   %s prev=%s cur=%s delta=%s comp=%s" % (seg, p, c, c - p, comp))
    # composition
    comp = {}
    for r in rows:
        k = status_norm(r[3])
        comp[k] = comp.get(k, 0) + (r[4] - r[5] if k == "持续经营" else (r[4] if k == "新开门店" else -r[5]))
    net = sum(r[4] for r in rows) - sum(r[5] for r in rows)
    print("   composition=%s net=%s rates=%s" % (
        comp, net, {k: round(v / net, 6) for k, v in comp.items()}))
