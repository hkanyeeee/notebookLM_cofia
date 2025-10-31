import os
import asyncio
import time
from typing import List, Optional, Dict
from enum import Enum
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from contextlib import asynccontextmanager


# 后端实例列表（逗号分隔）
EMBEDDING_BACKENDS: List[str] = os.getenv(
    "EMBEDDING_BACKENDS",
    "http://192.168.31.98:7998/v1,http://192.168.31.231:7998/v1,http://host.docker.internal:7988/v1",
).split(",")

PUBLIC_ENDPOINTS = ["/embeddings", "/v1/embeddings"]
FORWARD_ENDPOINT = "/embeddings"  # 后端 base 已含 /v1
TIMEOUT_S = float(os.getenv("EMBEDDING_TIMEOUT", "300"))

# 单独设置，避免与其他网关（如 rerank_gateway.py）端口冲突
HOST = os.getenv("EMBEDDING_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("EMBEDDING_GATEWAY_PORT", "7998"))

# 后端健康管理配置
ERROR_THRESHOLD = int(os.getenv("BACKEND_ERROR_THRESHOLD", "3"))  # 连续错误次数阈值
RECOVERY_TIME_S = int(os.getenv("BACKEND_RECOVERY_TIME", "30"))  # 错误后恢复时间（秒）


class BackendStatus(Enum):
    """后端状态枚举"""
    HEALTHY = "healthy"  # 健康可用
    ERROR = "error"  # 错误状态，暂不接收请求


@dataclass
class BackendState:
    """后端状态管理"""
    url: str
    semaphore: asyncio.Semaphore  # 并发控制（限制为1）
    status: BackendStatus = BackendStatus.HEALTHY
    error_count: int = 0  # 连续错误计数
    last_error_time: float = 0.0  # 最后一次错误时间
    
    def mark_success(self):
        """标记请求成功（返回200）"""
        self.status = BackendStatus.HEALTHY
        self.error_count = 0
        
    def mark_error(self):
        """标记请求失败"""
        self.error_count += 1
        self.last_error_time = time.time()
        if self.error_count >= ERROR_THRESHOLD:
            self.status = BackendStatus.ERROR
            
    def should_recover(self) -> bool:
        """检查是否应该从错误状态恢复"""
        if self.status == BackendStatus.ERROR:
            elapsed = time.time() - self.last_error_time
            return elapsed >= RECOVERY_TIME_S
        return False
    
    def try_recover(self):
        """尝试从错误状态恢复"""
        if self.should_recover():
            self.status = BackendStatus.HEALTHY
            self.error_count = 0

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化后端状态
    init_backend_states()
    print(f"Initialized {len(backend_states)} backend(s)")
    for url, state in backend_states.items():
        print(f"  - {url}: {state.status.value}")
    yield
    # 关闭时清理资源
    await client.aclose()

app = FastAPI(title="Embedding Gateway", lifespan=lifespan)

# 复用连接的 httpx 客户端
client = httpx.AsyncClient(timeout=TIMEOUT_S)

# 后端状态字典（初始化时创建）
backend_states: Dict[str, BackendState] = {}


def init_backend_states():
    """初始化后端状态"""
    global backend_states
    for url in EMBEDDING_BACKENDS:
        backend_states[url] = BackendState(
            url=url,
            semaphore=asyncio.Semaphore(1)  # 每个后端最多1个并发请求
        )


async def pick_backend() -> Optional[BackendState]:
    """
    选择一个可用的后端
    策略（最少连接数负载均衡）：
    1. 优先选择健康且空闲的后端中，等待队列最短的
    2. 尝试恢复错误状态的后端
    3. 如果所有后端都忙碌，选择等待队列最短的健康后端
    4. 如果所有后端都错误且无法恢复，返回 None
    """
    # 第一轮：尝试恢复错误后端
    for backend in backend_states.values():
        backend.try_recover()
    
    # 第二轮：找到健康且空闲的后端，选择等待队列最短的（_value 越小越好）
    idle_healthy_backends = [
        b for b in backend_states.values()
        if b.status == BackendStatus.HEALTHY and not b.semaphore.locked()
    ]
    
    if idle_healthy_backends:
        # 如果有多个空闲后端，选择 semaphore._value 最大的（说明最近使用最少）
        # 注意：_value 是内部属性，但这是获取等待队列长度的标准方式
        return min(idle_healthy_backends, key=lambda b: -b.semaphore._value)
    
    # 第三轮：所有后端都忙碌，选择等待队列最短的健康后端
    # 通过 semaphore._waiters 队列长度来判断
    healthy_backends = [
        b for b in backend_states.values() 
        if b.status == BackendStatus.HEALTHY
    ]
    
    if healthy_backends:
        # 选择等待队列最短的后端
        return min(
            healthy_backends,
            key=lambda b: len(b.semaphore._waiters) if hasattr(b.semaphore, '_waiters') else 0
        )
    
    # 第四轮：所有后端都是错误状态，强制重试第一个
    if backend_states:
        first_backend = list(backend_states.values())[0]
        first_backend.try_recover()  # 强制恢复
        first_backend.status = BackendStatus.HEALTHY  # 强制标记为健康
        return first_backend
    
    return None


def _forward_headers(src: dict) -> dict:
    # 过滤掉不该手动传的 hop-by-hop 头
    drop = {"host", "content-length", "connection"}
    out = {k: v for k, v in src.items() if k.lower() not in drop}
    # 确保 content-type 在
    out.setdefault("content-type", "application/json")
    return out


async def try_forward(body: bytes, headers: dict, backend_state: BackendState) -> Response:
    """
    转发请求到指定后端，并根据结果更新后端状态
    """
    try:
        resp = await client.post(
            backend_state.url.rstrip("/") + FORWARD_ENDPOINT,
            content=body,
            headers=_forward_headers(headers),
        )
        
        # 根据状态码更新后端状态
        if resp.status_code == 200:
            backend_state.mark_success()
        else:
            backend_state.mark_error()
        
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
            headers={k: v for k, v in resp.headers.items() if k.lower() == "x-request-id"},
        )
    except Exception as e:
        # 网络异常也标记为错误
        backend_state.mark_error()
        raise e


@app.post(PUBLIC_ENDPOINTS[0])
@app.post(PUBLIC_ENDPOINTS[1])
async def embeddings_proxy(req: Request):
    """
    代理 embedding 请求到后端
    使用基于回调的任务分配：
    - 每个后端同时只能处理1个请求
    - 只有返回200的后端才继续可用
    - 非200或异常的后端会被标记为错误状态
    """
    body = await req.body()
    headers = dict(req.headers)

    tried: List[str] = []
    last_exc = None
    max_attempts = len(EMBEDDING_BACKENDS) * 2  # 允许重试

    for attempt in range(max_attempts):
        backend_state = await pick_backend()
        
        if backend_state is None:
            break
            
        if backend_state.url in tried:
            # 已经尝试过，等待一小段时间后重试其他后端
            await asyncio.sleep(0.1)
            continue
        
        # 获取后端的并发锁（确保同时只有一个请求）
        async with backend_state.semaphore:
            tried.append(backend_state.url)
            try:
                # 转发请求并根据结果更新状态
                response = await try_forward(body, headers, backend_state)
                # 成功返回响应
                return response
            except Exception as e:
                last_exc = e
                # 后端错误，try_forward 已经标记了错误状态
                # 继续尝试下一个后端
                continue

    # 所有后端都不可用
    backend_status_info = {
        url: {
            "status": state.status.value,
            "error_count": state.error_count,
            "locked": state.semaphore.locked()
        }
        for url, state in backend_states.items()
    }
    
    return JSONResponse(
        status_code=502,
        content={
            "detail": "All embedding backends unavailable",
            "tried": tried,
            "backends_status": backend_status_info,
            "error": str(last_exc) if last_exc else "No backends available",
        },
    )


@app.get("/health")
async def health():
    """健康检查端点，显示所有后端状态"""
    backends_info = {
        url: {
            "status": state.status.value,
            "error_count": state.error_count,
            "is_busy": state.semaphore.locked(),
            "waiting_queue_length": len(state.semaphore._waiters) if hasattr(state.semaphore, '_waiters') else 0,
            "last_error_time": state.last_error_time if state.last_error_time > 0 else None
        }
        for url, state in backend_states.items()
    }
    
    all_healthy = all(
        state.status == BackendStatus.HEALTHY 
        for state in backend_states.values()
    )
    
    return {
        "ok": all_healthy,
        "strategy": "least_connections_with_semaphore",
        "backends": backends_info,
        "config": {
            "error_threshold": ERROR_THRESHOLD,
            "recovery_time_s": RECOVERY_TIME_S,
            "max_concurrent_per_backend": 1
        }
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("embedding_gateway:app", host=HOST, port=PORT, reload=False)
