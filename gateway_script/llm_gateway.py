import os
import asyncio
from itertools import cycle
from typing import List

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from contextlib import asynccontextmanager


# 后端实例列表（逗号分隔），均为 OpenAI 风格基址（通常以 /v1 结尾）
LLM_BACKENDS: List[str] = os.getenv(
    "LLM_BACKENDS",
    "http://192.168.31.98:1234/v1,http://192.168.31.231:1234/v1",
).split(",")

# 公共前缀：保持 OpenAI 风格 /v1/*
PUBLIC_PREFIX = "/v1"

# 网关监听地址
HOST = os.getenv("LLM_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("LLM_GATEWAY_PORT", "7995"))

# 超时
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT", "600"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)

# 轮询器（并发安全）
_backend_cycle = cycle([b.rstrip("/") for b in LLM_BACKENDS])
_cycle_lock = asyncio.Lock()

# 复用 httpx 客户端
client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=min(10.0, TIMEOUT_S)))


async def pick_backend() -> str:
    async with _cycle_lock:
        return next(_backend_cycle)


def _filter_request_headers(src: dict) -> dict:
    # 过滤 hop-by-hop 头，避免重复设置
    drop = {"host", "content-length", "connection"}
    out = {k: v for k, v in src.items() if k.lower() not in drop}
    # 默认 JSON
    out.setdefault("content-type", "application/json")
    return out


def _filter_response_headers(src: httpx.Headers) -> dict:
    # 仅透传少量安全的响应头；其他如 transfer-encoding 由 ASGI 层处理
    allow = {"content-type", "x-request-id", "cache-control", "openai-model", "openai-processing-ms"}
    return {k: v for k, v in src.items() if k.lower() in allow}


async def _stream_forward(resp: httpx.Response):
    async for chunk in resp.aiter_raw():
        # 原样透传字节（适用于 text/event-stream 或分块传输）
        if chunk:
            yield chunk


def _build_upstream_url(base: str, path: str, query: str) -> str:
    # base 已含 /v1；path 类似 /v1/chat/completions
    # 这里将下游请求的 /v1/* 直接拼接到上游 base 之后（避免重复 /v1）：
    # 去掉 path 的公共前缀 /v1
    assert path.startswith(PUBLIC_PREFIX)
    sub = path[len(PUBLIC_PREFIX):]
    # 构造最终 URL：base + sub
    url = base + sub
    if query:
        url += ("?" + query)
    return url


async def _forward(req: Request, backend_base: str) -> Response:
    method = req.method
    raw_path = req.url.path
    raw_query = req.url.query
    body = await req.body()
    headers = _filter_request_headers(dict(req.headers))

    upstream_url = _build_upstream_url(backend_base, raw_path, raw_query)

    # 使用流式响应以支持 SSE/分块
    upstream_resp = await client.request(method, upstream_url, content=body, headers=headers)

    media_type = upstream_resp.headers.get("content-type", "application/json")
    response_headers = _filter_response_headers(upstream_resp.headers)

    # 判断是否为流式（SSE 或 chunked），通过 content-type 或 transfer-encoding
    is_stream = (
        media_type.startswith("text/event-stream")
        or upstream_resp.headers.get("transfer-encoding", "").lower() == "chunked"
    )

    if is_stream:
        return StreamingResponse(_stream_forward(upstream_resp), media_type=media_type, headers=response_headers, status_code=upstream_resp.status_code)
    else:
        return Response(content=upstream_resp.content, media_type=media_type, headers=response_headers, status_code=upstream_resp.status_code)


async def _try_all_backends(req: Request) -> Response:
    tried: List[str] = []
    last_err = None
    for _ in range(len(LLM_BACKENDS)):
        backend = await pick_backend()
        if backend in tried:
            continue
        tried.append(backend)
        try:
            return await _forward(req, backend)
        except Exception as e:
            last_err = e
            continue
    return JSONResponse(status_code=502, content={"detail": "All LLM backends unavailable", "backends": tried, "error": str(last_err)})


# 捕获所有 /v1/* 路由并转发（POST/GET/DELETE/PATCH/PUT 等都支持）
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_all(req: Request, path: str):
    return await _try_all_backends(req)


@app.get("/health")
async def health():
    return {"ok": True, "backends": LLM_BACKENDS}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("llm_gateway:app", host=HOST, port=PORT, reload=False)


