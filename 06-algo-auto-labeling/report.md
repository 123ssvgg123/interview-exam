# 用本地大模型给酒店评论打情感标签 —— 自动标注 Demo

> 数据集：ChnSentiCorp 酒店评论（`dirtycomputer/ChnSentiCorp_htl_all`，7 766 条，二分类）
> 模型：Ollama 本地部署的 `qwen2.5:7b`（零 API 费用，全程离线）
> 代码：`demo_code.py`；结果：`outputs/`

---

## 1. 数据集与任务

| 项 | 说明 |
|---|---|
| 数据集 | ChnSentiCorp 中文酒店评论（谭松波酒店评论语料，HF 上的 `dirtycomputer/ChnSentiCorp_htl_all`） |
| 规模 | 7 766 条，正 5 322 / 负 2 444 |
| 输入特征 | 一段自由文本评论（几十到上千字，含错别字、口语、中英混排） |
| 标注目标 | 二分类情感极性：`positive` / `negative` |
| 抽样方式 | 分层抽样 300 条（正 150 / 负 150，`random_state=42`），保证两类都被充分评估 |
| 评测方式 | 与数据集自带的人工标签逐条比对，算 accuracy / macro-F1 / 混淆矩阵 |

选它的原因：这是一个「人工标签本身就不完美」的经典语料（原始标签来自携程的"推荐/不推荐"按钮，而非对评论逐句判读），正好能用来讨论自动标注的**上限**与**噪声**问题——而这正是工业界真做自动标注时最常踩的坑。

## 2. 模型与方法

- **模型**：`qwen2.5:7b`，通过 Ollama 提供的 OpenAI 兼容接口 `/v1/chat/completions` 调用（本机 GPU，无需联网、无需 API Key）。代码里模型名、`base_url` 都是 CLI 参数，换成 `gpt-4o-mini`、`qwen-plus` 或任意 OpenAI 兼容端点只需改 `--model/--host`。
- **推理方式**：本地推理，`temperature=0`（追求可复现），`format="json"` 约束输出为 JSON。
- **Prompt 设计**（三种，可用 `--variants` 任选）：

  1. `zero_shot`：角色设定 + 判定标准（区分"对酒店的负面评价"与"对周边/他人的负面描述"）+ 3 条 few-shot 反例说明常见陷阱（反讽、比较句、只吐槽一处但整体推荐）+ 要求输出 `{"label": "...", "confidence": 0~1, "reason": "..."}`；
  2. `few_shot`：在 zero_shot 之前再拼 4 条带标签示例（2 正 2 负，覆盖长文与短文）；
  3. `cot`：要求先写"正面证据 / 负面证据"两行，再给结论。

- **工程处理**：JSON 解析失败会做一次修复（截取首个 `{...}`、去掉 ```json 围栏、单引号转双引号），仍失败则重试一次；`--votes k` 可开 k 次自一致性投票（本报告的数字均为单次 `temperature=0`）。

## 3. 可运行代码

```bash
# 1) 起模型（一次性）
ollama serve            # 已后台常驻
ollama pull qwen2.5:7b

# 2) 跑标注（默认 300 条分层抽样 + 三种 prompt）
python demo_code.py --n 300 --variants zero_shot few_shot cot

# 3) 单条试一下
python demo_code.py --n 1 --variants zero_shot --out outputs/smoke
```

核心流程（`demo_code.py` 内）：

```python
rows = load_dataset("dirtycomputer/ChnSentiCorp_htl_all", split="train")   # 读数据
sample = stratified_sample(rows, n=args.n, seed=args.seed)                  # 分层抽样
for item in sample:
    raw = chat(model, build_prompt(item["review"], variant))                # 调模型
    parsed = parse_json_loose(raw)                                          # 容错解析
    records.append({"id": item["id"], "gold": item["label"],
                    "model_label": parsed["label"],
                    "confidence": parsed.get("confidence"), "reason": parsed.get("reason")})
report_metrics(records)                                                     # sklearn 指标 + 图
```

示例输出（`outputs/sample_outputs_zero_shot.md` 摘录）：

| gold | model | conf | 评论（截断） | 模型理由（截断） |
|---|---|---|---|---|
| positive | positive | 0.92 | 酒店位置很好，就在西湖边，出行方便…… | 明确称赞位置与出行便利，整体正面 |
| negative | negative | 0.88 | 房间有异味，服务员态度冷淡…… | 空气质量与态度均为负面证据 |
| positive | negative | 0.70 | 只有一点，南楼没有电梯，房间还很贵 | 聚焦"贵""没有电梯"等负面描述（**模型错**） |

## 4. 结果分析

n=300，`temperature=0`：

| variant | accuracy | macro-F1 | parse 失败率 | 单条 p50 延迟 |
|---|---|---|---|---|
| zero_shot | **0.8833** | 0.8828 | 0.00 | 0.58 s |
| few_shot | 0.8733 | 0.8767 | 0.01 | 0.60 s |
| cot | 0.8667 | 0.8657 | 0.00 | 0.97 s |

zero_shot 混淆矩阵（行=gold，列=pred）： `[[143, 7], [28, 122]]`

- **类别不对称**：负类召回 0.953，正类召回仅 0.813。模型对"差评"很敏感，但对"带一点抱怨的好评"倾向于判负——中文酒店评论里"先抑后扬 / 只吐槽一处"极常见。
- **few-shot 没有更好**：4 条示例反而把模型往"逐句找负面词"推，正类召回进一步下降；**cot 更差且贵**（延迟 1.7 倍），拆解证据后模型仍按最刺眼的负面词下结论。
- **置信度校准尚可**：`conf ≥ 0.8` 覆盖 89% 样本、准确率 90.3%；`conf ≥ 0.9` 覆盖 27%、准确率 100%。说明模型的自评置信度可以用来做**低置信样本转人工**的过滤闸门。

### 4.1 错例复核：88% 是被数据集"冤枉"的

把 35 条错例逐条读过之后（`outputs/manual_audit_zero_shot.csv`），我的独立判定是：

| 判定 | 条数 | 含义 |
|---|---|---|
| `label_noise`（数据集标签错） | 16 | 正文通篇差评却标 positive（如 "名不副实/毛巾黑且硬"、"简直太失望了"），或正文明显正面却标 negative |
| `ambiguous`（人也会分歧） | 14 | 正负证据量级接近，如"房间还好但空调不暖被冻醒"、"服务不错但价格贵得没道理" |
| `model_error`（真错） | 5 | 反讽（"社会主义好啊"）、把对**别家酒店**的好评算到本店、把"开元比天清岛强太多"误读为负面 |

于是：

- 严格准确率 **88.33%**；
- 剔除 16 条确认的标签噪声后 **93.31%**（265 / 284）；
- 真正无法辩解的模型错误只有 **5 / 300 = 1.7%**。

**结论：在这份数据上，模型的瓶颈更多来自数据标签而非理解能力。** 这与 ChnSentiCorp 的标签来源一致——它继承自携程的"推荐/不推荐"行为，而不是对评论逐句判读，天然带噪声。

### 4.2 模型什么时候好、什么时候坏

- **好**：明确正/负、有成串情感词、篇幅中等（100–500 字）的评论，判得又快又准；
- **坏**：① 反讽与口语梗（"社会主义好啊""牛叉"）；② 比较句——"A 比 B 强"里 A 是本店还是别家；③ 主体错配——评论里大段夸另一家酒店；④ 只吐槽一处但整体推荐（"只有一点……"）；⑤ 超长评论中正负段落交错、结尾情绪反转。

## 5. 人工标注 vs 模型标注

| 维度 | 人工 | 本 Demo 的 LLM |
|---|---|---|
| 速度 | 约 10–30 s/条（读长文更久） | 0.58 s/条，300 条 3 分钟（单卡） |
| 成本 | ￥0.1–0.5/条（众包） | 电费，≈0；换 API 约 ￥0.001–0.01/条 |
| 一致性 | 标注者间 κ 常在 0.7–0.85，会漂移 | 同 prompt 下高度可复现（temperature=0） |
| 语义理解 | 懂反讽、行业黑话、地域常识 | 反讽/比较句/主体错配易错（本 Demo 5 例） |
| 偏见 | 受情绪、疲劳、地域偏好影响 | 受训练语料与 prompt 措辞影响，且**会自信地错** |
| 可解释 | 能说明理由 | 给出的 `reason` 未必是真实决策依据，需谨慎采信 |

一句话：LLM 适合做**海量初标 + 低置信转人工**，不适合无人值守地替代人工定标。

## 6. 改进方向

1. **Prompt 层面**：把"情感归属主体"写死（"只评价本店，忽略对他人/他店的描述"）+ 给出正负证据抽取 + 让模型先回答"评论者最终是否推荐"再判极性；针对反讽单独加 few-shot（本 Demo 的 few-shot 版本没做这类定向示例，可以再试）。
2. **多模型投票 / 自一致性**：`--votes 3` 已实现，用 3 次采样多数票 + 分歧样本降置信；也可用 qwen2.5:7b 与 14b（或 API 模型）交叉投票，只把分歧样本送人工。
3. **置信度过滤 + 主动学习**：先全量跑一遍，把 `conf < 0.8` 的样本（本 Demo 占 10.7%，准确率只有 ~72%）交人工，人工结果再回灌成 few-shot 示例，形成 human-in-the-loop 闭环。
4. **换更细的任务**：把二分类升级为"方面级情感"（位置/服务/卫生/性价比各一标），噪声标签的影响会被摊薄，也更贴近业务真正想要的结构化字段。
5. **数据侧**：先做一轮标签清洗（用模型+规则找"高置信但与人标冲突"的样本），再在其上训练小模型（如 3 亿级中文分类器），把 0.58 s/条 降到毫秒级、成本降到 0。

---

**附录：文件清单**

```
demo_code.py                     主程序（标注 + 评测 + 出图）
analyze_errors.py                错例人工复核统计
outputs/predictions_zero_shot.csv   300 条逐条结果（含置信度与理由）
outputs/predictions_few_shot.csv / predictions_cot.csv
outputs/manual_audit_zero_shot.csv  35 条错例的人工复核判定
outputs/metrics.json / error_analysis.json
outputs/confusion_zero_shot.png     混淆矩阵
outputs/confidence_coverage.csv     置信度-覆盖率曲线数据
outputs/sample_outputs_zero_shot.md 样例输出
outputs/errors_zero_shot.md         错例摘录
```
