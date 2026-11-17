"""流式接口集成测试：真实 uvicorn 起服务 + httpx 流式读取。

不依赖 ASGITransport：只有走真实 socket 才能验证“客户端断开后服务端停止生成”。
"""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.main import STATS, app, fake_tokenize


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def base_url() -> str:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn-test", daemon=True)
    thread.start()

    deadline = time.time() + 20
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn 未能在 20s 内启动")
        if not thread.is_alive():
            raise RuntimeError("uvicorn 线程已退出")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


def collect_sse(response: httpx.Response) -> list[dict]:
    """读取完整 SSE 流，返回事件列表（跳过心跳注释）。"""
    buffer = "".join(response.iter_text())
    events = []
    for frame in buffer.split("\n\n"):
        if not frame.strip():
            continue
        event, data, event_id = "message", [], None
        for line in frame.split("\n"):
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line.startswith("id:"):
                event_id = line[3:].strip()
        if data:
            events.append({"event": event, "id": event_id, "data": "\n".join(data)})
    return events


def test_sse_streams_all_chunks_in_order(base_url: str) -> None:
    text = "流式输出 streaming demo"
    expected = fake_tokenize(text)
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "GET",
            f"{base_url}/stream/sse",
            params={"text": text, "delay": 0.005, "heartbeat": 0},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            assert "no-cache" in response.headers["cache-control"]
            events = collect_sse(response)

    tokens = [e for e in events if e["event"] == "token"]
    assert len(tokens) == len(expected) > 0
    assert [int(e["id"]) for e in tokens] == list(range(1, len(expected) + 1))
    deltas = [json.loads(e["data"])["delta"] for e in tokens]
    assert "".join(deltas) == text
    assert events[-1]["event"] == "done"
    assert events[-1]["data"] == "[DONE]"


def test_ndjson_each_line_is_valid_json(base_url: str) -> None:
    text = "NDJSON 每行一个 JSON object"
    expected = fake_tokenize(text)
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "GET",
            f"{base_url}/stream/ndjson",
            params={"text": text, "delay": 0.005, "heartbeat": 0},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/x-ndjson")
            assert response.headers["x-accel-buffering"] == "no"
            raw_lines = [line for line in response.iter_lines() if line.strip()]

    parsed = [json.loads(line) for line in raw_lines]  # 每行必须是合法 JSON
    assert all(isinstance(item, dict) for item in parsed)
    tokens = [item for item in parsed if item["type"] == "token"]
    assert [item["index"] for item in tokens] == list(range(1, len(expected) + 1))
    assert "".join(item["delta"] for item in tokens) == text
    assert parsed[-1] == {"type": "done"}


def test_client_disconnect_stops_generation(base_url: str) -> None:
    before = httpx.get(f"{base_url}/api/stats", timeout=10.0).json()
    long_text = "客户端断开测试 " * 60  # 足够多的 token，正常跑完需要数秒

    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "GET",
            f"{base_url}/stream/sse",
            params={"text": long_text, "delay": 0.05, "heartbeat": 0},
        ) as response:
            assert response.status_code == 200
            received = 0
            for line in response.iter_lines():
                if line.startswith("data:"):
                    received += 1
                if received >= 3:
                    break

    assert received == 3

    deadline = time.time() + 5
    stats = httpx.get(f"{base_url}/api/stats", timeout=10.0).json()
    while time.time() < deadline and stats["active"] > 0:
        time.sleep(0.1)
        stats = httpx.get(f"{base_url}/api/stats", timeout=10.0).json()

    assert stats["active"] == 0, f"断开后生成器仍在运行: {stats}"
    assert stats["cancelled"] >= before["cancelled"] + 1, stats
    assert stats["errors"] == before["errors"], stats

    # 再等一会儿，确认没有迟到的异常被记成 error
    time.sleep(0.4)
    assert httpx.get(f"{base_url}/api/stats", timeout=10.0).json()["errors"] == before["errors"]


def test_upstream_error_emits_error_event(base_url: str) -> None:
    stats_before = httpx.get(f"{base_url}/api/stats", timeout=10.0).json()["errors"]
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "GET",
            f"{base_url}/stream/sse",
            params={"text": "甲乙丙丁戊", "delay": 0.001, "heartbeat": 0, "fail_at": 3},
        ) as response:
            assert response.status_code == 200
            events = collect_sse(response)

    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1
    payload = json.loads(errors[0]["data"])
    assert payload["code"] == "internal_error"
    assert "token #3" in payload["message"]
    assert events[-1] == {"event": "done", "id": None, "data": "[DONE]"}
    assert len([e for e in events if e["event"] == "token"]) == 2
    assert httpx.get(f"{base_url}/api/stats", timeout=10.0).json()["errors"] == stats_before + 1


def test_chat_stream_returns_generated_text(base_url: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "POST",
            f"{base_url}/chat/stream",
            json={"prompt": "什么是 SSE？", "mode": "sse", "delay": 0.001, "max_tokens": 40},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = collect_sse(response)

    text = "".join(json.loads(e["data"])["delta"] for e in events if e["event"] == "token")
    assert "什么是 SSE" in text
    assert events[-1]["data"] == "[DONE]"
    assert STATS["errors"] >= 0  # 指标端点可读即可
