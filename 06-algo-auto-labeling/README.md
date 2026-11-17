# Auto Labeling with LLM —— 酒店评论情感自动标注

用本地部署的 `qwen2.5:7b`（Ollama）给 ChnSentiCorp 中文酒店评论自动打情感标签，
并和数据集自带的人工标签做对比评估。

- 数据集：`dirtycomputer/ChnSentiCorp_htl_all`（7 766 条，正 5 322 / 负 2 444）
- 任务：二分类情感（positive / negative），分层抽样 300 条评测（150/150）
- 结果：strict accuracy **88.33%**，macro-F1 0.8828；剔除人工复核确认的 16 条标签噪声后 **93.31%**

详细分析见 [report.md](report.md)，逐条结果见 `outputs/`。

## 环境

```bash
# Python 3.10+，需要：datasets / openpyxl? / requests / scikit-learn / matplotlib
pip install datasets requests scikit-learn matplotlib pandas

# 模型（本地，无需 API Key）
ollama serve
ollama pull qwen2.5:7b
```

数据集下载走 HuggingFace；国内网络请先设置镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com     # Windows PowerShell: $env:HF_ENDPOINT="https://hf-mirror.com"
```

## 运行

```bash
# 完整评测：300 条分层抽样，跑三种 prompt
python demo_code.py --n 300 --variants zero_shot few_shot cot

# 只要 zero-shot，换成本地/远端任意 OpenAI 兼容模型
python demo_code.py --n 100 --variants zero_shot --model qwen2.5:14b
python demo_code.py --n 100 --variants zero_shot \
    --model gpt-4o-mini --host https://api.openai.com/v1 --api-key $OPENAI_API_KEY

# 自一致性投票（同一个 prompt 采 3 次取多数票）
python demo_code.py --n 60 --variants zero_shot --votes 3 --temperature 0.7
```

常用参数：`--n`（抽样条数）、`--seed`（默认 42）、`--model`、`--host`（Ollama 默认
`http://127.0.0.1:11434/v1`）、`--variants`（可多选）、`--out`（输出目录，默认
`outputs`）、`--votes`、`--temperature`。

## 输出文件

| 文件 | 内容 |
|---|---|
| `outputs/predictions_<variant>.csv` | 逐条结果：id / gold / model_label / confidence / reason / 文本 |
| `outputs/metrics_<variant>.json` | accuracy、macro-F1、各类 P/R/F1、混淆矩阵、延迟 |
| `outputs/confusion_<variant>.png` | 混淆矩阵图 |
| `outputs/confidence_coverage.csv` | 置信度阈值 → 覆盖率 / 准确率（做人工复核闸门用） |
| `outputs/errors_<variant>.md` | 按置信度排序的错例摘录 |
| `outputs/sample_outputs_<variant>.md` | 报告用样例表 |
| `outputs/prompt_comparison.csv` | 三种 prompt 的横向对比 |
| `outputs/manual_audit_zero_shot.csv` | 35 条错例的**人工复核**判定 |
| `outputs/error_analysis.json` | 复核汇总（噪声/歧义/真错 各自条数与修正后准确率） |

`analyze_errors.py` 负责把人工复核结果汇总成上面的 json：

```bash
python analyze_errors.py
```

## 目录

```
06-algo-auto-labeling/
├── demo_code.py            # 主程序：抽样 → 调模型 → 解析 → 评测 → 出图
├── analyze_errors.py       # 错例人工复核统计
├── report.md               # 1-2 页报告（数据/方法/结果/分析/改进）
├── outputs/                # 结果（已在仓库内，可直接查看）
└── README.md
```

## 说明

- 模型输出被 `format=json` 约束并要求 `{"label","confidence","reason"}`；解析失败会做一次修复
  并重试，仍失败则记 `parse_failure`（本次 zero_shot 为 0）。
- 本次所有数字均为 `temperature=0`、单次采样的结果；`--votes` 打开后为多数票。
- 单卡 0.58 s/条，300 条约 3 分钟；换 API 模型只需改 `--model/--host`。
