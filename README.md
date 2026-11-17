# 前端 / 后端 / 爬虫 / Python / AI Agent / 算法 —— 六道笔试题

一个仓库装六道题，每题一个独立目录，互不依赖，可单独运行。

| # | 题目 | 目录 | 技术栈 | 一句话说明 |
|---|---|---|---|---|
| 1 | 前端：Figma 还原 | [`01-frontend-figma/`](01-frontend-figma/) | 原生 HTML / CSS / JS（零依赖） | 还原「Finish! Upload Your Resume」上传页，含拖拽、校验、进度状态与响应式 |
| 2 | 后端：SpringBoot + SpringSecurity | [`02-backend-springboot/`](02-backend-springboot/) | Spring Boot 3.2.0 / Java 17 / JWT | `POST /api/login`（test/123456）取 token，`GET /api/hello` 鉴权后返回 `Hello World` |
| 3 | 爬虫：Playwright + DrissionPage | [`03-crawler-mitadmissions/`](03-crawler-mitadmissions/) | Playwright 1.65 / DrissionPage 4.1 | 抓 `mitadmissions.org/blogs/`，输出标题/作者/评论数/时间/正文/图片 的 CSV |
| 4 | Python：FastAPI 流式 API | [`04-python-fastapi-streaming/`](04-python-fastapi-streaming/) | FastAPI / uvicorn / SSE | SSE 打字机 + NDJSON + 模拟 LLM，含断连处理与心跳 |
| 5 | AI Agent：评测任务包审核 | [`05-ai-agent-audit/`](05-ai-agent-audit/) | openpyxl / 人工复核 | 复算 gold、抽查 5 份 rollout、读 3 个 probe、诊断评分器，给出新 rubric 与验收结论 |
| 6 | 算法：LLM 自动标注 | [`06-algo-auto-labeling/`](06-algo-auto-labeling/) | Ollama + qwen2.5:7b | 给 ChnSentiCorp 酒店评论自动打情感标签，300 条评测 + 错例人工复核 |

## 快速开始

```bash
# 1) 前端：直接双击 index.html，或
cd 01-frontend-figma && python -m http.server 8080     # http://127.0.0.1:8080

# 2) 后端
cd 02-backend-springboot && mvn spring-boot:run         # 需 JDK 17+
# 或 mvn -DskipTests package && java -jar target/*.jar

# 3) 爬虫
cd 03-crawler-mitadmissions
pip install playwright DrissionPage requests lxml cssselect
python playwright_crawler.py --engine browser --pages 4 --max-articles 60
python drissionpage_crawler.py --engine browser --pages 4 --max-articles 60
python merge_and_check.py

# 4) FastAPI
cd 04-python-fastapi-streaming
pip install -r requirements.txt
uvicorn app.main:app --port 8000                        # http://127.0.0.1:8000/

# 5) AI Agent 审核：直接看 answer.md
cd 05-ai-agent-audit && cat answer.md

# 6) 算法
cd 06-algo-auto-labeling
pip install -r requirements.txt
ollama pull qwen2.5:7b
python demo_code.py --n 300 --variants zero_shot few_shot cot
```

## 目录结构

```
interview-exam/
├── 01-frontend-figma/            index.html / styles.css / app.js / README.md
├── 02-backend-springboot/        pom.xml / src/ / docs/ / README.md
├── 03-crawler-mitadmissions/     两个爬虫 + 公共工具 + 合并校验 + csv/ + README.md
├── 04-python-fastapi-streaming/  app/ / tests/ / Dockerfile / README.md
├── 05-ai-agent-audit/            answer.md（提交物）/ task-package/（被审材料）/ README.md
└── 06-algo-auto-labeling/        demo_code.py / report.md / outputs/ / README.md
```

## 环境

- 前端：任意现代浏览器，无需构建、无 CDN 依赖（插画为内联 SVG，可离线打开）。
- 后端：JDK 17+、Maven 3.9+；H2 之类外部依赖全部省略，用户信息在内存里。
- 爬虫：Python 3.10+，本机 Chrome（不下载 Chromium 也能跑）。
- FastAPI：Python 3.10+，`fastapi` + `uvicorn[standard]`。
- 算法：Ollama + `qwen2.5:7b`（也可把 `--host` 指向任意 OpenAI 兼容端点）。
- 数据集与模型下载在 `README` 里都给了国内镜像做法（`HF_ENDPOINT=https://hf-mirror.com`）。

## 说明

- 六道题都是**独立实现**，没有共用代码；每题目录下有各自的 README，写清了设计取舍、真实运行结果与已知限制。
- 所有结论都来自本机真实运行（含失败尝试），没有编造数字；截图与输出文件随仓库提交。
- 第 5 题按题目要求只交 `answer.md`（也可导出 PDF），被审核的任务包原件一并放在 `task-package/` 便于对照。

## 仓库地址

<https://github.com/123ssvgg123/interview-exam>

提交记录按题拆分（`git log --oneline` 每题一个 commit）：

```bash
git clone https://github.com/123ssvgg123/interview-exam.git
cd interview-exam
git log --oneline
```
