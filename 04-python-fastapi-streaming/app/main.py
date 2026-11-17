"""FastAPI 流式输出 Demo。

三种流式接口：
  - GET  /stream/sse      SSE（text/event-stream），带 id/event 字段
  - GET  /stream/ndjson   NDJSON（application/x-ndjson），每行一个 JSON
  - POST /chat/stream     模拟 LLM 逐 token 生成（SSE 或 text/plain）

工程点：反代缓冲关闭、缓存关闭、心跳、超时、客户端断开检测与取消、错误事件。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"
NDJSON_MEDIA_TYPE = "application/x-ndjson; charset=utf-8"
TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"

# 简单的进程内指标，方便演示/测试“断开后是否真的停止生成”
STATS: dict[str, int] = {
    "started": 0,
    "completed": 0,
    "cancelled": 0,
    "errors": 0,
    "active": 0,
}

DEMO_TEXT = "流式输出 Streaming 让首 token 更快到达：边生成、边发送、边渲染。"

# 假 tokenizer：中文按字、英文/数字按词、空白与标点各自成 token
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:'[A-Za-z]+)?|\s+|[\u4e00-\u9fff]|[^\sA-Za-z0-9\u4e00-\u9fff]")


def fake_tokenize(text: str) -> list[str]:
    """把一段文本切成“模型 token”粒度的片段，用于模拟逐字生成。"""
    if not text:
        return []
    return _TOKEN_RE.findall(text)


def _limit(tokens: list[str], limit: int) -> list[str]:
    return tokens[:limit] if limit and limit > 0 else tokens


def _stream_headers() -> dict[str, str]:
    """关闭各级缓冲 + 禁止缓存，保证代理/浏览器不攒包。"""
    return {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # Nginx: 不缓冲
        "Connection": "keep-alive",
    }


async def token_events(
    request: Request,
    tokens: list[str],
    *,
    delay: float,
    heartbeat: float,
    timeout: float,
    fail_at: int = 0,
) -> AsyncIterator[dict]:
    """统一的 token 事件源，供 SSE / NDJSON / text 三种序列化复用。

    产出事件：token / ping / error / done / client_disconnect。
    每个 token 前的等待被切成 100ms 小片，片间检查客户端是否断开并按时发心跳，
    这样即使单 token 延迟很长也不会“假死”。
    """
    started = time.perf_counter()
    last_heartbeat = started
    total = len(tokens)
    try:
        for index, token in enumerate(tokens, start=1):
            if fail_at and index == fail_at:
                raise RuntimeError(f"simulated upstream failure at token #{index}")
            remaining = delay
            while remaining > 0:
                if await request.is_disconnected():
                    yield {"kind": "client_disconnect"}
                    return
                step = min(0.1, remaining)
                await asyncio.sleep(step)
                remaining -= step
                now = time.perf_counter()
                if heartbeat > 0 and now - last_heartbeat >= heartbeat:
                    last_heartbeat = now
                    yield {"kind": "ping", "ts": round(now, 3)}
            if await request.is_disconnected():
                yield {"kind": "client_disconnect"}
                return
            elapsed = time.perf_counter() - started
            if timeout and elapsed > timeout:
                yield {
                    "kind": "error",
                    "code": "stream_timeout",
                    "message": f"stream exceeded {timeout}s",
                    "elapsed_ms": round(elapsed * 1000, 1),
                }
                yield {"kind": "done"}
                return
            last_heartbeat = time.perf_counter()
            yield {
                "kind": "token",
                "index": index,
                "text": token,
                "total": total,
                "elapsed_ms": round(elapsed * 1000, 1),
            }
        yield {"kind": "done", "total": total}
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 上游异常要转成 error 事件而不是 500
        STATS["errors"] += 1
        yield {"kind": "error", "code": "internal_error", "message": str(exc)}
        yield {"kind": "done"}


async def tracked_stream(request: Request, tokens: list[str], **kwargs) -> AsyncIterator[dict]:
    """包一层统计：正常结束 / 断开取消 / 异常各自计数。"""
    STATS["started"] += 1
    STATS["active"] += 1
    status = "error"
    try:
        async for event in token_events(request, tokens, **kwargs):
            if event["kind"] in {"error", "done"}:
                status = "completed"
            elif event["kind"] == "client_disconnect":
                status = "cancelled"
                return
            yield event
        else:
            status = "completed"
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        STATS["active"] -= 1
        STATS[status] += 1


def sse_encode(event: dict) -> str:
    """把事件编码成 SSE 帧；ping 用注释行，浏览器 EventSource 会自动忽略。"""
    kind = event["kind"]
    if kind == "ping":
        return f": ping {event['ts']}\n\n"
    if kind == "token":
        payload = {
            "index": event["index"],
            "delta": event["text"],
            "total": event["total"],
        }
        return (
            f"id: {event['index']}\n"
            f"event: token\n"
            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        )
    if kind == "error":
        payload = {"code": event["code"], "message": event["message"]}
        return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    if kind == "done":
        # 终止标记沿用 OpenAI 风格，便于前端统一判断
        return "event: done\ndata: [DONE]\n\n"
    return ""


def ndjson_encode(event: dict) -> str:
    kind = event["kind"]
    if kind == "token":
        payload = {"type": "token", "index": event["index"], "delta": event["text"]}
    elif kind == "ping":
        payload = {"type": "ping", "ts": event["ts"]}
    elif kind == "error":
        payload = {"type": "error", "code": event["code"], "message": event["message"]}
    elif kind == "done":
        payload = {"type": "done"}
    else:
        return ""
    return json.dumps(payload, ensure_ascii=False) + "\n"


app = FastAPI(
    title="FastAPI Streaming Demo",
    description="SSE / NDJSON / 模拟 LLM 流式输出",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
async def stats() -> dict:
    return dict(STATS)


@app.get("/stream/sse")
async def stream_sse(
    request: Request,
    text: str = Query(DEMO_TEXT, description="要逐 token 推送的文本"),
    tokens: int = Query(0, ge=0, le=5000, description="最多推送多少个 token，0 表示全部"),
    delay: float = Query(0.05, ge=0, le=2, description="每个 token 的模拟延迟（秒）"),
    heartbeat: float = Query(1.0, ge=0, le=60, description="心跳间隔（秒），0 关闭"),
    timeout: float = Query(30.0, gt=0, le=300, description="整条流的最长时长（秒）"),
    fail_at: int = Query(0, ge=0, le=10000, description="在第 N 个 token 处模拟上游异常，0 关闭"),
) -> StreamingResponse:
    parts = _limit(fake_tokenize(text), tokens)

    async def gen() -> AsyncIterator[str]:
        async for event in tracked_stream(
            request,
            parts,
            delay=delay,
            heartbeat=heartbeat,
            timeout=timeout,
            fail_at=fail_at,
        ):
            frame = sse_encode(event)
            if frame:
                yield frame

    return StreamingResponse(gen(), media_type=SSE_MEDIA_TYPE, headers=_stream_headers())


@app.get("/stream/ndjson")
async def stream_ndjson(
    request: Request,
    text: str = Query(DEMO_TEXT),
    tokens: int = Query(0, ge=0, le=5000),
    delay: float = Query(0.05, ge=0, le=2),
    heartbeat: float = Query(1.0, ge=0, le=60),
    timeout: float = Query(30.0, gt=0, le=300),
    fail_at: int = Query(0, ge=0, le=10000),
) -> StreamingResponse:
    parts = _limit(fake_tokenize(text), tokens)

    async def gen() -> AsyncIterator[str]:
        async for event in tracked_stream(
            request,
            parts,
            delay=delay,
            heartbeat=heartbeat,
            timeout=timeout,
            fail_at=fail_at,
        ):
            line = ndjson_encode(event)
            if line:
                yield line

    return StreamingResponse(gen(), media_type=NDJSON_MEDIA_TYPE, headers=_stream_headers())


class ChatRequest(BaseModel):
    prompt: str = Field(default="用三句话解释什么是流式输出。", max_length=2000)
    mode: Literal["sse", "text"] = "sse"
    delay: float = Field(default=0.03, ge=0, le=1)
    max_tokens: int = Field(default=200, ge=1, le=2000)


def fake_llm_answer(prompt: str) -> str:
    """模拟 LLM 的完整回答（真实场景换成上游 SDK 的流式迭代器）。"""
    return (
        f"你问的是「{prompt}」。\n\n"
        "简单说，流式输出（streaming）是指服务端边生成边发送、客户端边接收边渲染，"
        "而不是等全部算完再一次性返回。它把端到端时间拆成首 token 延迟（TTFT）和后续增量，"
        "体感上就像打字机。\n\n"
        "工程上要处理四件事：分块与帧边界、心跳保活、背压、以及客户端断开后的取消；"
        "如果前面有 Nginx，还要用 X-Accel-Buffering: no 关掉响应缓冲。"
    )


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    answer = fake_llm_answer(payload.prompt)
    parts = _limit(fake_tokenize(answer), payload.max_tokens)
    headers = _stream_headers()

    if payload.mode == "text":

        async def text_gen() -> AsyncIterator[str]:
            async for event in tracked_stream(
                request,
                parts,
                delay=payload.delay,
                heartbeat=0.0,
                timeout=60.0,
            ):
                if event["kind"] == "token":
                    yield event["text"]
                elif event["kind"] == "error":
                    yield f"\n[stream error] {event['message']}\n"

        return StreamingResponse(text_gen(), media_type=TEXT_MEDIA_TYPE, headers=headers)

    async def sse_gen() -> AsyncIterator[str]:
        async for event in tracked_stream(
            request,
            parts,
            delay=payload.delay,
            heartbeat=1.0,
            timeout=60.0,
        ):
            if event["kind"] == "token":
                body = json.dumps(
                    {"index": event["index"], "delta": event["text"]}, ensure_ascii=False
                )
                yield f"id: {event['index']}\nevent: token\ndata: {body}\n\n"
            elif event["kind"] == "done":
                yield "event: done\ndata: [DONE]\n\n"
            else:
                frame = sse_encode(event)
                if frame:
                    yield frame

    return StreamingResponse(sse_gen(), media_type=SSE_MEDIA_TYPE, headers=headers)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
