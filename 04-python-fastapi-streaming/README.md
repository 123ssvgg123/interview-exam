# FastAPI 流式输出 Demo（SSE / NDJSON / 模拟 LLM）

> 笔试题：用 FastAPI 实现 streaming API 的 demo。核心不是"能吐数据"，而是把流式接口的工程细节做对：
> 帧协议、反代缓冲、心跳、超时、异常事件、客户端断开后的取消。

## 1. 题目与目标

实现一个 FastAPI 服务，提供三种流式输出能力，并配一个可直接操作的网页：

| 目标 | 实现 |
| --- | --- |
| SSE 逐 token 推送，带 `event`/`id` | `GET /stream/sse` |
| NDJSON 每行一个 JSON | `GET /stream/ndjson` |
| 模拟 LLM 逐字生成（假 tokenizer + 延迟） | `POST /chat/stream` |
| 打字机效果页面，fetch + ReadableStream | `app/static/index.html` |
| 测试：顺序完整 + `[DONE]`、NDJSON 合法、断开不报错 | `tests/test_streaming.py`（5 个用例，真实 uvicorn） |

## 2. 目录结构

```
04-python-fastapi-streaming/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app：三个流接口 + 统一事件源 + 统计
│   └── static/
│       └── index.html     # 打字机页面（SSE / NDJSON / 模拟 LLM 三个面板）
├── tests/
│   └── test_streaming.py  # 5 个集成测试，真起 uvicorn + httpx 流式读取
├── pytest.ini
├── requirements.txt
├── Dockerfile
├── .gitignore
└── README.md
```

## 3. 接口表

| 方法 | 路径 | 说明 | Content-Type |
| --- | --- | --- | --- |
| GET | `/` | Demo 页面 | `text/html; charset=utf-8` |
| GET | `/health` | 健康检查 | `application/json` |
| GET | `/api/stats` | 进程内流指标（started/completed/cancelled/errors/active） | `application/json` |
| GET | `/stream/sse` | SSE 逐 token，带 `id`/`event`，以 `[DONE]` 结束 | `text/event-stream; charset=utf-8` |
| GET | `/stream/ndjson` | NDJSON，每行一个 JSON，最后一行 `{"type":"done"}` | `application/x-ndjson; charset=utf-8` |
| POST | `/chat/stream` | 模拟 LLM 逐 token 生成，`mode=sse` 或 `mode=text` | `text/event-stream` 或 `text/plain` |

### `/stream/sse`、`/stream/ndjson` 查询参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `text` | 内置示例句 | 要推送的文本 |
| `tokens` | `0` | 最多推送多少个 token，0 = 全部 |
| `delay` | `0.05` | 每个 token 的模拟延迟（秒） |
| `heartbeat` | `1.0` | 心跳间隔（秒），0 = 关闭 |
| `timeout` | `30` | 整条流最长时长（秒），超时发 `error` 事件 |
| `fail_at` | `0` | 在第 N 个 token 处模拟上游异常，用于演示 error 事件 |

### `POST /chat/stream` 请求体

```json
{ "prompt": "用三句话解释什么是流式输出。", "mode": "sse", "delay": 0.03, "max_tokens": 200 }
```

## 4. 如何运行

环境：Python 3.10（本机 `D:\ruanjian\anaconda\envs\system\python.exe`），依赖见 `requirements.txt`
（fastapi 0.115.12 / uvicorn 0.41.0 / httpx 0.28.1 / pytest 9.1.1）。

```powershell
cd D:\dsh-workplace\interview-exam\04-python-fastapi-streaming
D:\ruanjian\anaconda\envs\system\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/ 即可看到三个面板
```

跑测试（测试自己会在随机端口起 uvicorn，不需要先手动启动服务）：

```powershell
D:\ruanjian\anaconda\envs\system\python.exe -m pytest -q
```

## 5. curl 实测

### 5.1 NDJSON（真实输出）

```powershell
curl.exe -N -sS -G --data-urlencode "text=流式输出 Streaming 演示" --data-urlencode "delay=0.06" `
  "http://127.0.0.1:8777/stream/ndjson"
```

```
{"type": "token", "index": 1, "delta": "流"}
{"type": "token", "index": 2, "delta": "式"}
{"type": "token", "index": 3, "delta": "输"}
{"type": "token", "index": 4, "delta": "出"}
{"type": "token", "index": 5, "delta": " "}
{"type": "token", "index": 6, "delta": "Streaming"}
{"type": "token", "index": 7, "delta": " "}
{"type": "token", "index": 8, "delta": "演"}
{"type": "token", "index": 9, "delta": "示"}
{"type": "done"}
```

### 5.2 SSE（真实输出，截取）

```powershell
curl.exe -N -sS -G --data-urlencode "text=流式 SSE" --data-urlencode "delay=0.06" `
  "http://127.0.0.1:8777/stream/sse"
```

```
id: 1
event: token
data: {"index": 1, "delta": "流", "total": 4}

id: 2
event: token
data: {"index": 2, "delta": "式", "total": 4}

event: done
data: [DONE]
```

### 5.3 增量到达验证（httpx 记录每行到达时刻）

```
-- /stream/ndjson  status=200 ct=application/x-ndjson; charset=utf-8
   cache-control=no-cache, no-transform x-accel-buffering=no transfer-encoding=chunked
   +  137.4ms  {"type": "token", "index": 1, "delta": "流"}
   +  184.5ms  {"type": "token", "index": 2, "delta": "式"}
   +  246.3ms  {"type": "token", "index": 3, "delta": "输"}
   +  292.8ms  {"type": "token", "index": 4, "delta": "出"}
   ...
   +  574.4ms  {"type": "done"}
```

`delay=0.06`，行与行间隔约 50~60ms，说明服务端是**逐块 flush** 的，而不是攒完一次返回
（否则所有行会在同一毫秒到达）。响应头同时确认 `Transfer-Encoding: chunked`、
`X-Accel-Buffering: no`、`Cache-Control: no-cache, no-transform`。

### 5.4 心跳（`delay=1.3s`、`heartbeat=1s`）

```
: ping 7166.941

id: 1
event: token
data: {"index": 1, "delta": "AB", "total": 1}

event: done
data: [DONE]
```

`: ping` 是 SSE 注释行，浏览器 `EventSource` 会忽略，只用于保活。

### 5.5 异常事件

```powershell
curl.exe -N -s "http://127.0.0.1:8777/stream/sse?text=甲乙丙丁戊&delay=0.01&fail_at=3"
```

```
id: 1
event: token
data: {"index": 1, "delta": "甲", "total": 5}

id: 2
event: token
data: {"index": 2, "delta": "乙", "total": 5}

event: error
data: {"code": "internal_error", "message": "simulated upstream failure at token #3"}

event: done
data: [DONE]
```

第 3 个 token 之前抛出异常，所以 `甲`、`乙` 之后直接是 `error`（没有 `id`——错误不是 token，不带序号），
再补一个 `done` 让客户端能正常收尾；此时响应状态码仍是 200（headers 早已发出，无法再改）。

## 6. 测试结果（真实运行）

```
$ python -m pytest -q
.....                                                                    [100%]
5 passed, 2 warnings in 2.57s
```

两个 warning 来自第三方库（`websockets.legacy` 与 uvicorn 的 websockets 协议实现的弃用提示），与本项目代码无关。

| 用例 | 验证点 |
| --- | --- |
| `test_sse_streams_all_chunks_in_order` | 200；`text/event-stream`；`X-Accel-Buffering: no`；`Cache-Control` 含 `no-cache`；token 数量与顺序（id 1..N）正确；拼接后等于原文；最后一帧 `event: done` + `data: [DONE]` |
| `test_ndjson_each_line_is_valid_json` | `application/x-ndjson`；**每一行**都能 `json.loads`；index 连续；拼接等于原文；最后一行为 `{"type":"done"}` |
| `test_client_disconnect_stops_generation` | 读到 3 个 token 后直接关闭连接；`/api/stats` 的 `active` 回到 0、`cancelled` +1、`errors` 不变（说明生成器被真正终止，且没有把断开当成异常） |
| `test_upstream_error_emits_error_event` | `fail_at=3` 时第 3 个 token 前抛出异常；客户端收到 1 个 `event: error`（`code=internal_error`）后仍收到 `[DONE]`；`errors` 计数 +1 |
| `test_chat_stream_returns_generated_text` | `POST /chat/stream` 返回 SSE，delta 拼接包含 prompt 内容，正常以 `[DONE]` 结束 |

测试没有用 `ASGITransport`，而是用 `uvicorn.Server` 在线程里起真实服务：
只有真实 socket 才能验证"客户端断开 → 服务端停止生成"（ASGITransport 会在进程内收集完整响应，看不到断开）。

## 7. 设计说明

### 7.1 统一事件源，三种序列化

`token_events()` 是唯一的生成逻辑，产出 `token / ping / error / done / client_disconnect` 五类事件；
`stream_sse` 用 `sse_encode()` 编码成 SSE 帧，`stream_ndjson` 用 `ndjson_encode()` 编码成行，
`/chat/stream` 的 text 模式直接把 `delta` 拼出去。改协议只需要改编码层，不必复制生成逻辑。

### 7.2 帧格式

- SSE：`id` + `event` + `data`，空行分隔；心跳用 `: ping <ts>` 注释；结束用 `data: [DONE]`（OpenAI 风格，前端可统一判断）。
- NDJSON：一行一个 JSON 对象，`type` 字段区分 `token/ping/error/done`；相比 SSE 更省字节，适合日志/批处理消费，但浏览器侧要自己切行。
- text/plain：没有任何帧协议，纯增量文本，最省事但无法表达"结束/错误"，只适合 `curl` 演示。

### 7.3 反代与缓存

响应头固定带 `X-Accel-Buffering: no`（Nginx 不缓冲）、`Cache-Control: no-cache, no-transform`
（禁止中间层缓存与 gzip 转换），由 `StreamingResponse` + chunked 逐块下发。

### 7.4 心跳

每个 token 前的 `delay` 被切成 100ms 的小片：片间检查客户端是否断开，并按 `heartbeat` 间隔插入 `: ping`。
这样即使单 token 延迟很长（如 1.3s），连接也不会长时间静默被代理/LB 掐掉，同时断开能被及时发现
（最坏延迟 = 100ms + 一个片的处理时间）。

### 7.5 背压（backpressure）

`StreamingResponse` 逐个 chunk `await send()`：当客户端（或 TCP 窗口）读得慢时，`send` 会被阻塞，
生成协程随之暂停，内存里始终只有当前这一个 chunk，不会出现"客户端很慢、服务端把整段回答算完堆在内存里"。
真实 LLM 场景把上游 SDK 的迭代器包成 async generator 放进同一个 `async for` 即可继承这套背压。
代价是慢客户端会占住连接，生产上需要按用户限流 + 连接数上限。

### 7.6 客户端断开

`await request.is_disconnected()` 每 100ms 检查一次；检测到断开就 `return` 结束生成器（不抛异常），
`tracked_stream()` 的 `finally` 把 `active` 减一、`cancelled` 加一。
断开时**不抛** `ClientDisconnected` 是刻意的：异常会穿透到 uvicorn，被记成 "Exception in ASGI application"，
污染日志；静默结束更干净，且 uvicorn 对已断开的连接会忽略后续 `send`。
`/api/stats` 用来从外部证明"断开后真的停了"——测试里就是这么断言的。

### 7.7 超时与错误事件

- 整条流超过 `timeout`：发 `event: error`（`code=stream_timeout`）再发 `[DONE]`。
- 上游异常：捕获后发 `event: error`（`code=internal_error` + 原始 message）再发 `[DONE]`，并让 `errors` 计数 +1。
- 关键点：流式响应一旦发出 200 和响应头，**就无法再改 HTTP 状态码**，错误只能走流内事件；
  前端必须处理 `error` 事件，而不是只看 `response.ok`。

### 7.8 模拟 LLM

`fake_tokenize()` 用正则做"假 tokenizer"：中文按字、英文/数字按词、空白和标点各自成 token，
再用 `asyncio.sleep`（不是 `time.sleep`）模拟推理延迟，全程 `async def`，不阻塞事件循环。
`/chat/stream` 会基于 prompt 拼一段固定回答再逐 token 推送，行为和真实 LLM 的"边生成边返回"一致。

## 8. 与真实 LLM 对接的改造点

1. **替换生成函数**：把 `fake_llm_answer()` + `token_events()` 换成上游 SDK 的流式迭代器。
   OpenAI 兼容接口用 `AsyncOpenAI(...).chat.completions.create(..., stream=True)`，
   同步 SDK 则用 `asyncio.to_thread` 逐块取，绝不能直接 `for chunk in stream` 阻塞事件循环。
2. **不再自己切 token**：直接转发上游 `delta.content`，`index` 用自增序号；SSE schema 保持不变，前端零改动。
3. **断开要传导到上游**：检测到 `is_disconnected()` 后必须 `await stream.close()` / `aclose()`，
   否则模型还在生成、token 还在计费（这是流式服务最容易漏的一处）。
4. **错误映射**：上游 429/5xx/超时 → `error` 事件的 `code`（如 `rate_limited`、`upstream_timeout`），
   前端据此提示重试；不要试图改 HTTP 状态码。
5. **鉴权与限流**：按 API key / 用户维度限制并发流数量，避免慢客户端耗尽连接池。
6. **首 token 优化**：真实场景把 prompt 预处理、检索等放在流开始之前，TTFT 才是体验指标（页面已展示 TTFT）。
7. **可观测性**：把 `/api/stats` 换成 Prometheus 指标（TTFT、tokens/s、断开率、错误率），多副本下不要再用进程内字典。
8. **部署**：容器里 `--proxy-headers`，Nginx 侧 `proxy_buffering off; proxy_read_timeout` 放大；
   本项目的 `X-Accel-Buffering: no` 已经能免掉大部分缓冲问题。

## 9. 已知限制

- 假 tokenizer 是正则近似，不是真正的 BPE，token 数与真实模型不一致（仅用于演示节奏）。
- `/api/stats` 是单进程内存计数，多 worker 下不聚合。
- 页面未做 Markdown 渲染与断线重连（`EventSource` 自带重连，但本 demo 用 `fetch` + `AbortController`，重连需自行实现）。
- `pytest.ini` 里关闭了 pytest 缓存插件（`-p no:cacheprovider`），避免在受限环境写 `.pytest_cache`。
