import os
import asyncio
from itertools import cycle
from typing import List

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse


# 后端实例列表（逗号分隔）
RERANK_BACKENDS: List[str] = os.getenv(
    "RERANK_BACKENDS",
    # 默认两台机器（注意：这里是示例地址，可通过环境变量覆盖）
    "http://192.168.31.98:7997,http://192.168.31.231:7999",
).split(",")

PUBLIC_ENDPOINTS = ["/rerank", "/v1/rerank"]
FORWARD_ENDPOINT = "/rerank"
TIMEOUT_S = float(os.getenv("RERANK_TIMEOUT", "300"))

# 每台机器最大并发
PER_BACKEND_CONCURRENCY = int(os.getenv("RERANK_PER_BACKEND_CONCURRENCY", "2"))

# 为避免与其他网关端口冲突，单独设置
HOST = os.getenv("RERANK_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("RERANK_GATEWAY_PORT", "7996"))

# 当所有后端都繁忙时的排队等待时长（秒）；超时后返回 503
QUEUE_WAIT_TIMEOUT_S = float(os.getenv("RERANK_QUEUE_WAIT_TIMEOUT", "300"))

app = FastAPI(title="Rerank Gateway")


class BackendState:
    def __init__(self, base_url: str, capacity: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.semaphore = asyncio.Semaphore(capacity)


# 初始化后端状态与轮询器
_backend_states: List[BackendState] = [BackendState(url, PER_BACKEND_CONCURRENCY) for url in RERANK_BACKENDS]
_backend_cycle = cycle(_backend_states)
_cycle_lock = asyncio.Lock()

# 复用连接的 httpx 客户端
client = httpx.AsyncClient(timeout=TIMEOUT_S)


async def pick_backend() -> BackendState:
    async with _cycle_lock:
        return next(_backend_cycle)


async def try_forward(body: bytes, headers: dict, base_url: str) -> Response:
    resp = await client.post(
        base_url + FORWARD_ENDPOINT,
        content=body,
        headers={"content-type": headers.get("content-type", "application/json")},
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _try_acquire_immediately(sem: asyncio.Semaphore) -> bool:
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.0)
        return True
    except Exception:
        return False


@app.post(PUBLIC_ENDPOINTS[0])
@app.post(PUBLIC_ENDPOINTS[1])
async def rerank_proxy(req: Request):
    body = await req.body()
    headers = dict(req.headers)

    tried_hosts: List[str] = []
    last_exc = None

    # 在队列等待窗口内不断尝试找到可用后端
    end_time = asyncio.get_event_loop().time() + QUEUE_WAIT_TIMEOUT_S

    while True:
        # 先尝试所有后端是否立即可用
        for _ in range(len(_backend_states)):
            backend = await pick_backend()
            if backend.base_url in tried_hosts:
                # 本次循环中已经尝试过该后端
                continue
            acquired = await _try_acquire_immediately(backend.semaphore)
            if not acquired:
                continue
            # 已获得并发额度，尝试转发
            try:
                resp = await try_forward(body, headers, backend.base_url)
                return resp
            except Exception as e:
                last_exc = e
                tried_hosts.append(backend.base_url)
                continue
            finally:
                # 无论成功失败，都在完成一次转发尝试后释放并发额度
                try:
                    backend.semaphore.release()
                except Exception:
                    pass

        # 如果没有立即可用的后端，判断是否超时
        if asyncio.get_event_loop().time() >= end_time:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "All rerank backends are busy",
                    "backends": [b.base_url for b in _backend_states],
                    "tried": tried_hosts,
                    "error": str(last_exc) if last_exc else None,
                },
            )

        # 简单排队：小睡一会儿再重试，避免自旋过快
        await asyncio.sleep(0.01)


@app.get("/health")
async def health():
    # 仅返回基本信息，避免访问内部属性
    return {
        "ok": True,
        "backends": [b.base_url for b in _backend_states],
        "per_backend_concurrency": PER_BACKEND_CONCURRENCY,
        "timeout_s": TIMEOUT_S,
    }


@app.on_event("shutdown")
async def _shutdown():
    await client.aclose()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("rerank_gateway:app", host=HOST, port=PORT, reload=False)


