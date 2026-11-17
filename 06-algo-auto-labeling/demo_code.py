#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_code.py —— 用本地开源大模型给中文酒店评论自动打情感标签。

任务：二分类情感标注（positive / negative）
数据：Hugging Face `dirtycomputer/ChnSentiCorp_htl_all`（7766 条中文酒店评论，自带人工标签）
模型：Qwen2.5-7B-Instruct，通过 Ollama 本地推理（HTTP API，无需 key、无数据外传）

用法示例
--------
    # 快速冒烟（20 条，三种 prompt 各跑一遍）
    python demo_code.py --n 20

    # 正式跑：300 条样本，zero-shot / few-shot / CoT 三种 prompt 对比
    python demo_code.py --n 300 --variants zero_shot,few_shot,cot

产出（默认 outputs/）
--------
    predictions_<variant>.csv    逐条预测：原文、人工标签、模型标签、置信度、理由、耗时
    predictions_all.csv          所有 variant 合并
    metrics.json                 准确率 / 宏平均 F1 / 每类 P-R-F1 / 混淆矩阵 / 延迟分位数
    prompt_comparison.csv        三种 prompt 的横向对比
    confidence_coverage.csv      按置信度阈值过滤后的覆盖率-准确率曲线
    confusion_<variant>.png      混淆矩阵图
    errors_<variant>.md          错例清单（供人工复核）
    sample_outputs.md            抽 12 条给人看的样例
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 数据集走 hf-mirror，避免 huggingface.co 在国内不可达
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

HF_DATASET = "dirtycomputer/ChnSentiCorp_htl_all"
LABEL_NAMES = ("negative", "positive")
GOLD_MAP = {0: "negative", 1: "positive"}
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# ---------------------------------------------------------------- prompt 设计

SYSTEM_PROMPT = (
    "你是一名中文酒店评论情感标注员。你的任务是判断一条酒店评论整体的情感倾向。\n"
    "判定规则：\n"
    "1. 以评论者对酒店的整体态度为准，而非个别细节；\n"
    "2. 褒贬混杂时看主要立场：先抑后扬且总体满意 -> positive；先扬后抑且总体失望 -> negative；\n"
    "3. 只陈述事实（如“房间在 3 楼”）而无褒贬时，按中性偏正面处理为 positive；\n"
    "4. 不要被评论长度、感叹号数量影响判断。\n"
    '只输出一个 JSON 对象，不要输出任何其他文字：'
    '{"label": "positive 或 negative", "confidence": 0~1 之间的小数, "reason": "不超过 20 字的中文理由"}'
)

FEW_SHOT_EXAMPLES = [
    ("酒店位置很好，离地铁站步行五分钟，房间干净整洁，早餐也很丰富，下次还会入住。",
     '{"label": "positive", "confidence": 0.95, "reason": "位置、卫生、早餐均正面"}'),
    ("隔音太差了，一晚上都被走廊的脚步声吵醒，前台态度也很冷漠，不会再来了。",
     '{"label": "negative", "confidence": 0.93, "reason": "隔音与服务均差评"}'),
    ("房间不大，设施有点旧，不过床很舒服，服务员也热情，性价比尚可。",
     '{"label": "positive", "confidence": 0.72, "reason": "虽有不足但总体满意"}'),
    ("预订时说是海景房，结果窗户对着隔壁楼，投诉也没人处理，非常失望。",
     '{"label": "negative", "confidence": 0.9, "reason": "货不对板且投诉无果"}'),
]

COT_INSTRUCTION = (
    "先在心里分析评论中的正面证据与负面证据，再给出结论。\n"
    '只输出一个 JSON 对象：{"evidence_positive": "…", "evidence_negative": "…", '
    '"label": "positive 或 negative", "confidence": 0~1 的小数}'
)


def build_messages(text: str, variant: str) -> list[dict[str, str]]:
    """按 variant 组装 chat messages。"""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    user = f"评论：\n{text}\n\n请输出 JSON。"

    if variant == "zero_shot":
        messages.append({"role": "user", "content": user})
    elif variant == "few_shot":
        for example_text, example_answer in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": f"评论：\n{example_text}\n\n请输出 JSON。"})
            messages.append({"role": "assistant", "content": example_answer})
        messages.append({"role": "user", "content": user})
    elif variant == "cot":
        messages.append({"role": "user", "content": user + "\n" + COT_INSTRUCTION})
    else:
        raise ValueError(f"未知 variant: {variant}")
    return messages


# ---------------------------------------------------------------- Ollama 客户端


@dataclass
class Prediction:
    """单条预测结果。"""

    id: int
    text: str
    gold: str
    variant: str
    label: str = ""
    confidence: float = 0.0
    reason: str = ""
    latency_s: float = 0.0
    parse_ok: bool = False
    raw: str = ""
    error: str = ""


class OllamaTagger:
    """封装 Ollama /api/chat，做 JSON 解析、重试与计时。"""

    def __init__(self, model: str, host: str = OLLAMA_HOST, temperature: float = 0.0,
                 seed: int = 42, timeout: int = 180, retries: int = 2, api_key: str = ""):
        self.model = model
        self.host = host.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        # host 以 /v1 结尾（或显式给了 api_key）时走 OpenAI 兼容的 /chat/completions
        self.openai_mode = self.host.endswith("/v1") or bool(self.api_key)
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.retries = retries
        self._session = None

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        import urllib.request

        if self.openai_mode:                      # OpenAI 兼容端点（vLLM / DeepSeek / OpenAI / ...）
            body = {
                "model": payload["model"],
                "messages": payload["messages"],
                "temperature": self.temperature,
                "max_tokens": payload["options"]["num_predict"],
                "response_format": {"type": "json_object"},
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            req = urllib.request.Request(
                f"{self.host}/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            return {"message": {"content": content}}   # 统一成 Ollama 的返回形状

        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def tag(self, text: str, variant: str, item_id: int = 0, gold: str = "") -> Prediction:
        """单次标注；votes>1 时做自一致性多数投票（用于改进实验）。"""
        votes = max(1, int(getattr(self, "votes", 1)))
        if votes == 1:
            return self._tag_once(text, variant, item_id, gold, seed_offset=0)

        collected = [self._tag_once(text, variant, item_id, gold, seed_offset=i) for i in range(votes)]
        valid = [p for p in collected if p.parse_ok]
        if not valid:
            return collected[0]
        tally: dict[str, list[Prediction]] = {"positive": [], "negative": []}
        for p in valid:
            tally[p.label].append(p)
        winner = max(tally, key=lambda k: len(tally[k]))
        chosen = tally[winner][0]
        chosen.confidence = round(sum(p.confidence for p in tally[winner]) / len(tally[winner]), 4)
        chosen.reason = f"[{len(tally[winner])}/{len(valid)} 票] " + chosen.reason[:60]
        chosen.latency_s = round(sum(p.latency_s for p in collected), 3)
        chosen.raw = chosen.raw
        return chosen

    def _tag_once(self, text: str, variant: str, item_id: int, gold: str, seed_offset: int = 0) -> Prediction:
        pred = Prediction(id=item_id, text=text, gold=gold, variant=variant)
        payload = {
            "model": self.model,
            "messages": build_messages(text, variant),
            "stream": False,
            "format": "json",          # 让 Ollama 保证输出是合法 JSON
            "options": {
                "temperature": self.temperature,
                "seed": self.seed + seed_offset,
                "num_predict": 220 if variant == "cot" else 120,
                "top_p": 0.9,
            },
        }
        last_error = ""
        for attempt in range(self.retries + 1):
            start = time.perf_counter()
            try:
                data = self._post(payload)
                pred.latency_s = time.perf_counter() - start
                pred.raw = (data.get("message") or {}).get("content", "") or ""
                parsed = parse_model_output(pred.raw, variant)
                pred.label = parsed["label"]
                pred.confidence = parsed["confidence"]
                pred.reason = parsed["reason"]
                pred.parse_ok = bool(pred.label)
                if pred.parse_ok:
                    return pred
                last_error = f"无法从输出中解析标签: {pred.raw[:120]!r}"
            except Exception as exc:  # 网络/超时/JSON 错误都重试
                pred.latency_s = time.perf_counter() - start
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                time.sleep(1.0 + attempt)
        pred.error = last_error
        pred.label = "unparsed"      # 计为错分，但不猜标签
        pred.confidence = 0.0
        pred.reason = last_error[:80]
        return pred


# ---------------------------------------------------------------- 输出解析

_JSON_OBJ = re.compile(r"\{.*\}", re.S)
_POSITIVE_HINTS = ("positive", "正面", "好评", "满意", "推荐")
_NEGATIVE_HINTS = ("negative", "负面", "差评", "不满", "失望")


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def normalize_label(value: Any) -> str:
    """把模型可能给出的各种写法统一成 positive / negative。"""
    if value is None:
        return ""
    text = str(value).strip().lower()
    if text in ("positive", "pos", "1", "正面", "好评"):
        return "positive"
    if text in ("negative", "neg", "0", "负面", "差评"):
        return "negative"
    if any(h in text for h in _POSITIVE_HINTS) and not any(h in text for h in _NEGATIVE_HINTS):
        return "positive"
    if any(h in text for h in _NEGATIVE_HINTS) and not any(h in text for h in _POSITIVE_HINTS):
        return "negative"
    return ""


def normalize_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    # 兼容 0-100 的写法
    if conf > 1.0:
        conf = conf / 100.0
    return max(0.0, min(1.0, conf))


def parse_model_output(raw: str, variant: str) -> dict[str, Any]:
    """尽最大努力把模型输出解析成 {label, confidence, reason}。"""
    cleaned = _strip_code_fence(raw)
    obj: dict[str, Any] = {}
    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            obj = loaded
    except json.JSONDecodeError:
        match = _JSON_OBJ.search(cleaned)
        if match:
            try:
                loaded = json.loads(match.group(0))
                if isinstance(loaded, dict):
                    obj = loaded
            except json.JSONDecodeError:
                obj = {}

    label = normalize_label(obj.get("label"))
    if not label:
        # 退化路径：JSON 里没有 label，就在整段文本里找线索
        label = normalize_label(cleaned)

    reason = obj.get("reason") or obj.get("evidence") or ""
    if not reason and variant == "cot":
        pos = obj.get("evidence_positive") or ""
        neg = obj.get("evidence_negative") or ""
        reason = f"正:{pos} 负:{neg}"[:80]
    return {
        "label": label,
        "confidence": normalize_confidence(obj.get("confidence")),
        "reason": str(reason)[:120],
    }


# ---------------------------------------------------------------- 数据加载


def load_reviews(n: int, seed: int, min_chars: int = 8) -> list[dict[str, Any]]:
    """从 HF 拉数据，按标签分层抽样 n 条，返回 [{id, text, gold}]。"""
    from datasets import load_dataset

    last_error: Exception | None = None
    ds = None
    for attempt in range(3):
        try:
            ds = load_dataset(HF_DATASET, split="train")
            break
        except Exception as exc:  # 网络抖动重试
            last_error = exc
            print(f"[warn] 数据集加载失败（第 {attempt + 1} 次）：{exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    if ds is None:
        raise RuntimeError(f"无法加载数据集 {HF_DATASET}: {last_error}")

    frame = ds.to_pandas()[["review", "label"]]
    frame["text"] = frame["review"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    frame = frame[frame["text"].str.len() >= min_chars]
    frame["gold"] = frame["label"].map(GOLD_MAP)
    frame = frame.dropna(subset=["gold"])

    rng = random.Random(seed)
    per_class = {label: frame[frame.gold == label].index.tolist() for label in LABEL_NAMES}
    take = {label: rng.sample(idxs, min(len(idxs), n // len(LABEL_NAMES))) for label, idxs in per_class.items()}
    picked = [(idx, label) for label, idxs in take.items() for idx in idxs]
    rng.shuffle(picked)

    rows: list[dict[str, Any]] = []
    for i, (idx, label) in enumerate(picked, start=1):
        rows.append({"id": i, "text": frame.at[idx, "text"], "gold": label})
    return rows


# ---------------------------------------------------------------- 评估


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """准确率、每类 P/R/F1、宏平均、混淆矩阵。"""
    import numpy as np
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    gold = [r["gold"] for r in rows]
    pred = [r["label"] for r in rows]
    labels = list(LABEL_NAMES)
    precision, recall, f1, support = precision_recall_fscore_support(
        gold, pred, labels=labels, zero_division=0
    )
    cm = confusion_matrix(gold, pred, labels=labels)
    accuracy = float(np.mean([g == p for g, p in zip(gold, pred)]))
    latencies = sorted(r["latency_s"] for r in rows)

    def pct(q: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(round(q * (len(latencies) - 1))))
        return round(latencies[idx], 3)

    return {
        "n": len(rows),
        "accuracy": round(accuracy, 4),
        "macro_f1": round(float(np.mean(f1)), 4),
        "per_class": {
            label: {
                "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(support[i]),
            }
            for i, label in enumerate(labels)
        },
        "confusion_matrix": {"labels": labels, "matrix": cm.tolist()},
        "parse_failure_rate": round(sum(1 for r in rows if not r["parse_ok"]) / max(1, len(rows)), 4),
        "latency_s": {"mean": round(sum(latencies) / max(1, len(latencies)), 3), "p50": pct(0.5), "p95": pct(0.95)},
        "avg_confidence": round(sum(r["confidence"] for r in rows) / max(1, len(rows)), 4),
    }


def confidence_coverage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按置信度降序，逐档给出覆盖率与准确率——用于论证“置信度过滤”这一改进方向。"""
    ordered = sorted(rows, key=lambda r: r["confidence"], reverse=True)
    curve = []
    for cutoff in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        kept = [r for r in ordered if r["confidence"] >= cutoff]
        if not kept:
            continue
        acc = sum(1 for r in kept if r["label"] == r["gold"]) / len(kept)
        curve.append({
            "min_confidence": cutoff,
            "coverage": round(len(kept) / len(ordered), 4),
            "accuracy": round(acc, 4),
            "kept": len(kept),
        })
    return curve


def plot_confusion(metrics: dict[str, Any], title: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    matrix = np.array(metrics["confusion_matrix"]["matrix"])
    labels = metrics["confusion_matrix"]["labels"]
    fig, ax = plt.subplots(figsize=(4.2, 3.6), dpi=140)
    im = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("model label")
    ax.set_ylabel("human label")
    ax.set_title(f"{title}  (acc={metrics['accuracy']:.3f})")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, str(matrix[i, j]), ha="center", va="center",
                    color="white" if matrix[i, j] > matrix.max() / 2 else "#1f2937")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------- 写文件


def write_predictions(rows: list[dict[str, Any]], path: Path) -> None:
    import pandas as pd

    frame = pd.DataFrame([
        {
            "id": r["id"],
            "text": r["text"],
            "gold": r["gold"],
            "model_label": r["label"],
            "confidence": r["confidence"],
            "reason": r["reason"],
            "latency_s": round(r["latency_s"], 3),
            "parse_ok": r["parse_ok"],
            "correct": r["label"] == r["gold"],
            "variant": r["variant"],
        }
        for r in rows
    ])
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_error_report(rows: list[dict[str, Any]], variant: str, path: Path, top: int = 20) -> None:
    """按“置信度高但判错”排序，挑最值得人工复核的错例。"""
    errors = [r for r in rows if r["label"] != r["gold"]]
    errors.sort(key=lambda r: r["confidence"], reverse=True)
    lines = [f"# {variant} 错例（共 {len(errors)} 条，以下按模型置信度从高到低）", ""]
    for r in errors[:top]:
        lines += [
            f"## #{r['id']}  人工={r['gold']}  模型={r['label']}  conf={r['confidence']:.2f}",
            f"- 评论：{r['text'][:160]}",
            f"- 模型理由：{r['reason']}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_sample_outputs(rows: list[dict[str, Any]], variant: str, path: Path, count: int = 12) -> None:
    lines = [f"# {variant} 样例输出", "", "| # | 评论（截断） | 人工标签 | 模型标签 | 置信度 | 理由 |", "|---|---|---|---|---|---|"]
    for r in rows[:count]:
        text = r["text"].replace("|", "｜")[:60]
        reason = r["reason"].replace("|", "｜")[:40]
        mark = "✅" if r["label"] == r["gold"] else "❌"
        lines.append(f"| {r['id']} | {text} | {r['gold']} | {mark} {r['label']} | {r['confidence']:.2f} | {reason} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 主流程


def run_variant(tagger: OllamaTagger, data: list[dict[str, Any]], variant: str,
                out_dir: Path, verbose: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = time.perf_counter()
    for i, item in enumerate(data, start=1):
        pred = tagger.tag(item["text"], variant, item_id=item["id"], gold=item["gold"])
        row = asdict(pred)
        rows.append(row)
        if verbose and (i % 10 == 0 or i == len(data)):
            acc = sum(1 for r in rows if r["label"] == r["gold"]) / len(rows)
            print(f"  [{variant}] {i}/{len(data)}  acc={acc:.3%}  用时 {time.perf_counter() - start:.0f}s",
                  flush=True)

    metrics = compute_metrics(rows)
    metrics["variant"] = variant
    metrics["model"] = tagger.model
    metrics["total_wall_time_s"] = round(time.perf_counter() - start, 1)

    write_predictions(rows, out_dir / f"predictions_{variant}.csv")
    write_error_report(rows, variant, out_dir / f"errors_{variant}.md")
    write_sample_outputs(rows, variant, out_dir / f"sample_outputs_{variant}.md")
    plot_confusion(metrics, f"{variant}", out_dir / f"confusion_{variant}.png")
    (out_dir / f"metrics_{variant}.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows, metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用本地 LLM 给中文酒店评论自动打情感标签")
    parser.add_argument("--n", type=int, default=200, help="抽样条数（按标签分层，默认 200）")
    parser.add_argument("--seed", type=int, default=42, help="抽样与推理的随机种子")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama 模型名")
    parser.add_argument("--host", default=OLLAMA_HOST, help="Ollama 地址；以 /v1 结尾则按 OpenAI 兼容接口调用")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""), help="OpenAI 兼容端点的 key（默认读 OPENAI_API_KEY）")
    parser.add_argument("--variants", default="zero_shot,few_shot,cot",
                        help="要对比的 prompt，逗号分隔：zero_shot,few_shot,cot")
    parser.add_argument("--out", default="outputs", help="输出目录")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--votes", type=int, default=1,
                        help="自一致性投票次数（>1 时同一评论采样多次取多数票，用于改进实验）")
    args = parser.parse_args(argv)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in ("zero_shot", "few_shot", "cot")]
    if unknown:
        parser.error(f"未知 variant: {unknown}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"加载数据集 {HF_DATASET} 并抽样 {args.n} 条 …")
    data = load_reviews(args.n, args.seed)
    dist = {}
    for item in data:
        dist[item["gold"]] = dist.get(item["gold"], 0) + 1
    print(f"样本分布：{dist}")

    tagger = OllamaTagger(model=args.model, host=args.host, temperature=args.temperature,
                          seed=args.seed, api_key=args.api_key)
    tagger.votes = args.votes
    all_rows: list[dict[str, Any]] = []
    metrics_by_variant: dict[str, Any] = {}

    for variant in variants:
        print(f"\n=== {variant} ===")
        rows, metrics = run_variant(tagger, data, variant, out_dir)
        all_rows.extend(rows)
        metrics_by_variant[variant] = metrics

    if len(variants) > 1:
        import pandas as pd

        comparison = pd.DataFrame([
            {
                "variant": v,
                "n": m["n"],
                "accuracy": m["accuracy"],
                "macro_f1": m["macro_f1"],
                "parse_failure_rate": m["parse_failure_rate"],
                "avg_confidence": m["avg_confidence"],
                "latency_p50_s": m["latency_s"]["p50"],
                "latency_p95_s": m["latency_s"]["p95"],
                "wall_time_s": m["total_wall_time_s"],
            }
            for v, m in metrics_by_variant.items()
        ])
        comparison.to_csv(out_dir / "prompt_comparison.csv", index=False, encoding="utf-8-sig")
        print("\n" + comparison.to_string(index=False))

    # 置信度-覆盖率曲线（以准确率最高的 variant 为准）
    best_variant = max(metrics_by_variant, key=lambda v: metrics_by_variant[v]["accuracy"])
    best_rows = [r for r in all_rows if r["variant"] == best_variant]
    curve = confidence_coverage(best_rows)
    if curve:
        import pandas as pd

        pd.DataFrame(curve).to_csv(out_dir / "confidence_coverage.csv", index=False, encoding="utf-8-sig")
        print(f"\n置信度过滤（{best_variant}）：")
        for point in curve:
            print(f"  conf>={point['min_confidence']:.2f}  覆盖 {point['coverage']:.0%}  "
                  f"准确率 {point['accuracy']:.2%}  ({point['kept']} 条)")

    write_predictions(all_rows, out_dir / "predictions_all.csv")
    (out_dir / "metrics.json").write_text(
        json.dumps({"dataset": HF_DATASET, "model": args.model, "n": len(data),
                    "variants": metrics_by_variant}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n全部产出已写入 {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
