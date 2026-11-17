#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_errors.py —— 对 demo_code.py 产出的错例做人工复核统计。

`outputs/manual_audit_zero_shot.csv` 是我逐条阅读 zero_shot 全部 35 条错例后
给出的第三方判定（label_noise / ambiguous / model_error），本脚本把它汇总成
「扣掉标注噪声后的模型准确率」，供报告引用。
"""

import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "outputs"


def main() -> None:
    gold = pd.read_csv(OUT / "predictions_zero_shot.csv")
    audit = pd.read_csv(OUT / "manual_audit_zero_shot.csv")

    n = len(gold)
    strict_correct = int((gold["gold"] == gold["model_label"]).sum())
    counts = audit["my_judgment"].value_counts().to_dict()

    noise = counts.get("label_noise", 0)
    ambiguous = counts.get("ambiguous", 0)
    model_error = counts.get("model_error", 0)

    # 去掉「标签本身就是错的」样本后的准确率（模型在这些题上其实是对的）
    adjusted_denominator = n - noise
    adjusted_accuracy = strict_correct / adjusted_denominator if adjusted_denominator else 0
    # 再乐观一点：把 ambiguous 也算作可接受（模型与人工都有道理）
    lenient_accuracy = (strict_correct + ambiguous) / n if n else 0

    summary = {
        "n": n,
        "strict_correct": strict_correct,
        "strict_accuracy": round(strict_correct / n, 4),
        "disagreements": len(audit),
        "error_taxonomy": {
            "label_noise": noise,
            "ambiguous": ambiguous,
            "model_error": model_error,
        },
        "accuracy_excluding_label_noise": round(adjusted_accuracy, 4),
        "accuracy_if_ambiguous_counted_as_ok": round(lenient_accuracy, 4),
        "manual_error_rate_on_disagreements": round(model_error / len(audit), 4),
    }
    (OUT / "error_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
