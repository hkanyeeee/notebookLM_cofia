import os
import asyncio
from itertools import cycle
from typing import List

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from contextlib import asynccontextmanager


# 后端实例列表（逗号分隔）
EMBEDDING_BACKENDS: List[str] = os.getenv(
    "EMBEDDING_BACKENDS",
    "http://192.168.31.98:7998/v1,http://192.168.31.231:7998/v1",
).split(",")

PUBLIC_ENDPOINTS = ["/embeddings", "/v1/embeddings"]
FORWARD_ENDPOINT = "/embeddings"  # 后端 base 已含 /v1
TIMEOUT_S = float(os.getenv("EMBEDDING_TIMEOUT", "300"))

# 单独设置，避免与其他网关（如 rerank_gateway.py）端口冲突
HOST = os.getenv("EMBEDDING_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("EMBEDDING_GATEWAY_PORT", "7998"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.aclose()

app = FastAPI(title="Embedding Gateway", lifespan=lifespan)

# 轮询游标（并发安全：用 asyncio.Lock 保护）
_backend_cycle = cycle(EMBEDDING_BACKENDS)
_cycle_lock = asyncio.Lock()

# 复用连接的 httpx 客户端
client = httpx.AsyncClient(timeout=TIMEOUT_S)


async def pick_backend() -> str:
    async with _cycle_lock:
        return next(_backend_cycle)


async def try_forward(body: bytes, headers: dict, base_url: str) -> Response:
    # 仅透传 JSON；必要时可以附加鉴权等头
    resp = await client.post(
        base_url.rstrip("/") + FORWARD_ENDPOINT,
        content=body,
        headers={"content-type": headers.get("content-type", "application/json")},
    )
    # 原样返回后端响应
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@app.post(PUBLIC_ENDPOINTS[0])
@app.post(PUBLIC_ENDPOINTS[1])
async def embeddings_proxy(req: Request):
    body = await req.body()
    headers = dict(req.headers)

    tried: List[str] = []
    last_exc = None

    for _ in range(len(EMBEDDING_BACKENDS)):
        backend = await pick_backend()
        if backend in tried:
            continue
        tried.append(backend)
        try:
            return await try_forward(body, headers, backend)
        except Exception as e:
            last_exc = e
            # 尝试下一台后端
            continue

    return JSONResponse(
        status_code=502,
        content={
            "detail": "All embedding backends unavailable",
            "backends": tried,
            "error": str(last_exc),
        },
    )


@app.get("/health")
async def health():
    return {"ok": True, "backends": EMBEDDING_BACKENDS}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("embedding_gateway:app", host=HOST, port=PORT, reload=False)
