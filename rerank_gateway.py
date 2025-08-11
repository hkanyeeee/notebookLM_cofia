# 文件名：rerank_gateway.py
# 作用：把 /rerank 透传到后端多实例（轮询转发，失败自动切换）
import os
import asyncio
from itertools import cycle
from typing import List
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse

# 后端实例列表（逗号分隔）
BACKENDS = os.getenv(
    "RERANK_BACKENDS",
    "http://192.168.31.98:7999,http://192.168.31.231:7999"
).split(",")

ENDPOINT = "/rerank"
TIMEOUT_S = float(os.getenv("RERANK_TIMEOUT", "300"))
HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("GATEWAY_PORT", "7999"))

app = FastAPI(title="Rerank Gateway")

# 轮询游标（并发安全：用 asyncio.Lock 保护）
_backend_cycle = cycle(BACKENDS)
_cycle_lock = asyncio.Lock()

# 单个 httpx 客户端，复用连接
client = httpx.AsyncClient(timeout=TIMEOUT_S)

async def pick_backend() -> str:
    async with _cycle_lock:
        return next(_backend_cycle)

async def try_forward(body: bytes, headers: dict, url: str) -> Response:
    # 仅透传 JSON；也可以按需带上少量请求头
    resp = await client.post(
        url + ENDPOINT,
        content=body,
        headers={"content-type": headers.get("content-type", "application/json")}
    )
    # 原样返回后端响应（状态码与 body）
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )

@app.post(ENDPOINT)
async def rerank_proxy(req: Request):
    body = await req.body()
    headers = dict(req.headers)

    # 首选：当前轮询选中的后端；失败则依次尝试其他后端
    tried: List[str] = []
    last_exc = None

    for _ in range(len(BACKENDS)):
        backend = await pick_backend()
        if backend in tried:
            continue
        tried.append(backend)
        try:
            return await try_forward(body, headers, backend)
        except Exception as e:
            last_exc = e
            # 继续尝试下一台
            continue

    # 都失败了：
    return JSONResponse(
        status_code=502,
        content={"detail": "All backends unavailable", "backends": tried, "error": str(last_exc)},
    )

@app.get("/health")
async def health():
    return {"ok": True, "backends": BACKENDS}

@app.on_event("shutdown")
async def _shutdown():
    await client.aclose()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("rerank_gateway:app", host=HOST, port=PORT, reload=False)
