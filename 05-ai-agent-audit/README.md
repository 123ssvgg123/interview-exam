# AI Agent 笔试题 —— 评测任务包质量审核

对被审核的「餐厅门店客流变化归因」Agent 评测任务包（`task-package/`）做一次完整审核：
把 gold 的事实算一遍、抽查 5 份 rollout、读 3 个 probe、读评分器源码，最后给出
新 rubric 与验收结论。

- **提交物：[answer.md](answer.md)**（按 `answer-template.md` 的五节结构，另加第 0 节工具声明）
- 被审材料：`task-package/restaurant-portfolio-traffic-change-audit/`
  （question / rubric / materials / gold / rollouts / probes / scorer）

## 目录

```
answer.md                  审核报告（提交物）
task-package/              被审核的任务包原件（题目、台账、gold、5 份 rollout、3 个 probe、评分器源码）
verify_ledger.py           复现脚本：从 completion 向量重算每份 rollout 的分数
.gitignore
```

## 怎么读

`answer.md` 六节：

| 节 | 内容 |
|---|---|
| 0 | 工具与口径声明（用 openpyxl 读单元格、脚本复算，不依赖模型打分） |
| 1 | 任务可行性与事实基线：全品牌 374→422→481（+48 / +59）的复算，桥接与餐段各一条链的逐步验证 |
| 2 | 5 份 rollout 抽查表：每份 1 条核心数值链 + 1 条控制链，逐格给证据 |
| 3 | 3 个 probe 的判定：各自抓什么缺陷、应保留/应失信什么、根因去重、当前评分器的误判 |
| 4 | 评分器诊断：有效权重 vs 声明权重、frozen 哈希回放、死代码（R1/R2/R3/R7/R8/R6A/C/D）、`credit()` 悬崖；新 rubric C1–C9（权重合计 100%）+ 门槛 G1–G6；程序化/人工分工 |
| 5 | 验收结论：**需返修**（不是不可用），附 4 个回归测试 |

## 关键结论（摘要）

1. **事实层面没有问题**：gold 与源台账逐格一致，5 份 rollout 的数值链 0 处算错。
2. **评分器与声明不一致**：`fresh_owner_policy.py` 的有效权重只有
   `R4 23.45% + R5 5.56% + R6B 30% + R6E 35% + R9 5.99%`，而 rubric 声明是
   R2 8% / R3 18% / R4 25% / R5 25% / R6 10% / R7 9%；R1/R2/R3/R7/R8 全为死代码。
3. **哈希回放绕过内容判定**：`validator.py` 对 sha256 命中的 artifact 直接返回冻结奖励，
   把 gold 用 openpyxl 原样另存（内容不变）就变成 `PENDING_JUDGE_ERROR`（缺
   `llm_judge/runtime/workbook.py` 等模块），说明"冻结表"成了唯一的评分路径。
4. **R9 可被空壳刷分**：probe-03 是 20 行纯标签 + `=1+1`，因为它有公式而拿到 R9 满分。
5. **奖励悬崖**：`credit()` 在 `c=1` 处硬切到 1.0，`5/6` 只得 0.667，导致
   "差一格"和"差一半"几乎同分；且 5 份 rollout 的分数（0.294/0.294/0.944/0.35/1.0）
   与人工阅读质量（≈9–9.5/10）严重不匹配。

## 复现

```bash
pip install openpyxl
# 重算 5 份 rollout 的分数（读 frozen_owner_policy.json 的 completion 向量）
python verify_ledger.py
```

命题方若要看评分器对单份工作簿的判定，可直接在其仓库内跑
`python scorer/validator.py <xlsx>`；注意该快照缺少 `llm_judge/` 依赖，未命中 frozen 表时会
报 `PENDING_JUDGE_ERROR`（这一点已写进 answer.md 第 4 节）。
