import os
import asyncio
from itertools import cycle
from typing import List

import httpx
import logging
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse


# 后端实例列表（逗号分隔）
RERANK_BACKENDS: List[str] = os.getenv(
    "RERANK_BACKENDS",
    # 默认两台机器（注意：这里是示例地址，可通过环境变量覆盖）
    "http://192.168.31.98:7997,http://192.168.31.231:7995",
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

# 为后端请求设置更细粒度的超时控制
REQUEST_TIMEOUT_S = float(os.getenv("RERANK_REQUEST_TIMEOUT", "30"))

logger = logging.getLogger("rerank_gateway")


class BackendState:
    def __init__(self, base_url: str, capacity: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.semaphore = asyncio.Semaphore(capacity)
        # 添加后端健康状态跟踪
        self.is_healthy = True


# 初始化后端状态与轮询器
_backend_states: List[BackendState] = [BackendState(url, PER_BACKEND_CONCURRENCY) for url in RERANK_BACKENDS]
_backend_cycle = cycle(_backend_states)
_cycle_lock = asyncio.Lock()

# 复用连接的 httpx 客户端
client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=min(10.0, TIMEOUT_S)))


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.aclose()


app = FastAPI(title="Rerank Gateway", lifespan=lifespan)


async def pick_backend() -> BackendState:
    async with _cycle_lock:
        return next(_backend_cycle)


async def try_forward(body: bytes, headers: dict, base_url: str) -> Response:
    start_time = asyncio.get_event_loop().time()
    try:
        logger.debug(f"Attempting to forward request to {base_url}{FORWARD_ENDPOINT}")
        
        # 为单个请求设置更短的超时时间
        request_timeout = httpx.Timeout(REQUEST_TIMEOUT_S, connect=min(5.0, REQUEST_TIMEOUT_S))
        resp = await client.post(
            base_url + FORWARD_ENDPOINT,
            content=body,
            headers={"content-type": headers.get("content-type", "application/json")},
            timeout=request_timeout,
        )
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.info(f"Successfully forwarded to {base_url}{FORWARD_ENDPOINT} in {duration:.2f}s")
        
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except httpx.TimeoutException as e:
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.error(f"Timeout forwarding to {base_url}{FORWARD_ENDPOINT} after {duration:.2f}s: {e}")
        raise
    except httpx.RequestError as e:
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.error(f"Request error forwarding to {base_url}{FORWARD_ENDPOINT} after {duration:.2f}s: {e}")
        raise
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.error(f"Unexpected error forwarding to {base_url}{FORWARD_ENDPOINT} after {duration:.2f}s: {e}")
        raise


async def _try_acquire_immediately(sem: asyncio.Semaphore) -> bool:
    try:
        # 使用一个非常短的超时时间，而不是0.0
        # 这样可以避免在高并发下立即失败的问题
        await asyncio.wait_for(sem.acquire(), timeout=0.01)
        return True
    except asyncio.TimeoutError:
        # 超时说明信号量不可用，返回False
        return False
    except Exception as e:
        # 记录其他异常但仍然返回False，避免因为异常导致整个流程中断
        logger.warning(f"Error acquiring semaphore: {e}")
        return False

# 添加一个更详细的信号量状态检查函数
async def check_semaphore_status(sem: asyncio.Semaphore, backend_url: str) -> None:
    """记录信号量状态用于调试"""
    try:
        # 获取当前信号量的值
        if hasattr(sem, '_value'):
            logger.debug(f"Semaphore status for {backend_url}: value={sem._value}")
    except Exception as e:
        logger.debug(f"Could not get semaphore status for {backend_url}: {e}")


@app.post(PUBLIC_ENDPOINTS[0])
@app.post(PUBLIC_ENDPOINTS[1])
async def rerank_proxy(req: Request):
    body = await req.body()
    headers = dict(req.headers)

    tried_hosts: List[str] = []  # 累计记录所有尝试过的后端（用于返回调试信息）
    last_exc = None
    request_start_time = asyncio.get_event_loop().time()
    
    # 记录请求的简化信息用于调试
    try:
        body_str = body.decode('utf-8')[:200] + "..." if len(body) > 200 else body.decode('utf-8')
        logger.debug(f"Incoming request with body length: {len(body)}, first 200 chars: {body_str}")
    except Exception:
        logger.debug(f"Incoming request with body length: {len(body)}")

    # 在队列等待窗口内不断尝试找到可用后端
    end_time = asyncio.get_event_loop().time() + QUEUE_WAIT_TIMEOUT_S

    while True:
        # 每一轮只尝试每个后端一次
        tried_in_round = set()
        for _ in range(len(_backend_states)):
            backend = await pick_backend()
            if backend.base_url in tried_in_round:
                continue
            tried_in_round.add(backend.base_url)
            
            # 如果后端不健康，跳过
            if not backend.is_healthy:
                logger.debug(f"Skipping unhealthy backend: {backend.base_url}")
                continue
                
            acquired = await _try_acquire_immediately(backend.semaphore)
            if not acquired:
                # 当前后端已满，跳过
                logger.debug(f"Backend {backend.base_url} is at capacity, skipping")
                # 记录信号量状态用于调试
                await check_semaphore_status(backend.semaphore, backend.base_url)
                continue
                
            # 已获得并发额度，尝试转发
            try:
                logger.info(f"Forwarding to {backend.base_url}{FORWARD_ENDPOINT}")
                resp = await try_forward(body, headers, backend.base_url)
                logger.info(f"Successfully received response from {backend.base_url}")
                return resp
            except httpx.TimeoutException:
                # 请求超时，标记后端不健康
                backend.is_healthy = False
                last_exc = "Timeout"
                if backend.base_url not in tried_hosts:
                    tried_hosts.append(backend.base_url)
                logger.warning(f"Timeout from {backend.base_url}, marking as unhealthy")
                continue
            except httpx.RequestError as e:
                # 网络请求错误，标记后端不健康
                backend.is_healthy = False
                last_exc = str(e)
                if backend.base_url not in tried_hosts:
                    tried_hosts.append(backend.base_url)
                logger.warning(f"Request error from {backend.base_url}: {e}")
                continue
            except Exception as e:
                # 其他异常
                last_exc = str(e)
                if backend.base_url not in tried_hosts:
                    tried_hosts.append(backend.base_url)
                logger.warning(f"Error from {backend.base_url}: {e}")
                continue
            finally:
                # 无论成功失败，都在完成一次转发尝试后释放并发额度
                try:
                    backend.semaphore.release()
                except Exception as e:
                    logger.error(f"Error releasing semaphore for {backend.base_url}: {e}")

        # 如果没有立即可用的后端，判断是否超时
        if asyncio.get_event_loop().time() >= end_time:
            request_duration = asyncio.get_event_loop().time() - request_start_time
            logger.warning(f"All rerank backends are busy or unhealthy after {request_duration:.2f}s")
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "All rerank backends are busy or unhealthy",
                    "backends": [b.base_url for b in _backend_states],
                    "tried": tried_hosts,
                    "error": str(last_exc) if last_exc else None,
                    "request_duration_s": request_duration,
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
        "healthy_backends": [b.base_url for b in _backend_states if b.is_healthy],
        "unhealthy_backends": [b.base_url for b in _backend_states if not b.is_healthy],
    }


if __name__ == "__main__":
    import uvicorn
    logger.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO)
    logger.info(
        f"Start gateway on {HOST}:{PORT}, backends={ [b.base_url for b in _backend_states] }, per_backend={PER_BACKEND_CONCURRENCY}, timeout={TIMEOUT_S}s"
    )
    uvicorn.run("rerank_gateway:app", host=HOST, port=PORT, reload=False)
