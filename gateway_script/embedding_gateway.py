import os
import asyncio
import time
from typing import List, Optional, Dict
from enum import Enum
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from contextlib import asynccontextmanager


def _split_backends(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _get_env_float(name: str, default: float, *, min_value: Optional[float] = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    return value


def _get_env_int(name: str, default: int, *, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if min_value is not None and value < min_value:
        value = default
    if max_value is not None and value > max_value:
        value = default
    return value


def _is_success_status(status_code: int) -> bool:
    return 200 <= status_code < 300


def _is_client_error(status_code: int) -> bool:
    return 400 <= status_code < 500


DEFAULT_EMBEDDING_BACKENDS = "http://192.168.31.231:7998/v1,http://192.168.31.98:7998/v1,http://host.docker.internal:7988/v1"

# 后端实例列表（逗号分隔）
EMBEDDING_BACKENDS: List[str] = _split_backends(
    os.getenv("EMBEDDING_BACKENDS", DEFAULT_EMBEDDING_BACKENDS)
)

PUBLIC_ENDPOINTS = ["/embeddings", "/v1/embeddings"]
FORWARD_ENDPOINT = "/embeddings"  # 后端 base 已含 /v1
TIMEOUT_S = _get_env_float("EMBEDDING_TIMEOUT", 300.0, min_value=1.0)

# 可配置的后端权重（用于按算力/优先级调度）
# 优先按字面 URL 匹配；如果需要更灵活的匹配，可改为基于 host:port 或正则
_RAW_BACKEND_WEIGHTS = {
    "http://192.168.31.231:7998/v1": 4.064,
    "http://192.168.31.98:7998/v1": 2.547,
    "http://host.docker.internal:7988/v1": 1.0,
}
BACKEND_WEIGHTS = {k.strip(): float(v) for k, v in _RAW_BACKEND_WEIGHTS.items()}

# 单独设置，避免与其他网关（如 rerank_gateway.py）端口冲突
HOST = os.getenv("EMBEDDING_GATEWAY_HOST", "0.0.0.0")
PORT = _get_env_int("EMBEDDING_GATEWAY_PORT", 7998, min_value=1, max_value=65535)

# 后端健康管理配置
ERROR_THRESHOLD = _get_env_int("BACKEND_ERROR_THRESHOLD", 3, min_value=1)  # 连续错误次数阈值
RECOVERY_TIME_S = _get_env_int("BACKEND_RECOVERY_TIME", 30, min_value=1)  # 错误后恢复时间（秒）
MAX_STATS_WINDOW = _get_env_int("BACKEND_STATS_WINDOW", 10000, min_value=0)
HTTPX_MAX_CONNECTIONS = _get_env_int("HTTPX_MAX_CONNECTIONS", 100, min_value=1)
HTTPX_MAX_KEEPALIVE = _get_env_int("HTTPX_MAX_KEEPALIVE_CONNECTIONS", 20, min_value=0)


def validate_config():
    if not EMBEDDING_BACKENDS:
        raise ValueError("EMBEDDING_BACKENDS must contain at least one backend URL.")
    invalid = [url for url in EMBEDDING_BACKENDS if not url.startswith("http")]
    if invalid:
        raise ValueError(f"Invalid backend URLs detected: {invalid}")
    non_positive_weights = [
        url for url in EMBEDDING_BACKENDS if BACKEND_WEIGHTS.get(url, 1.0) <= 0
    ]
    if non_positive_weights:
        raise ValueError(f"Backend weights must be positive: {non_positive_weights}")
    if not (1 <= PORT <= 65535):
        raise ValueError(f"EMBEDDING_GATEWAY_PORT out of range: {PORT}")
    if TIMEOUT_S <= 0:
        raise ValueError("EMBEDDING_TIMEOUT must be positive.")
    if ERROR_THRESHOLD < 1:
        raise ValueError("BACKEND_ERROR_THRESHOLD must be >= 1.")
    if RECOVERY_TIME_S < 1:
        raise ValueError("BACKEND_RECOVERY_TIME must be >= 1 second.")


validate_config()


class BackendStatus(Enum):
    """后端状态枚举"""
    HEALTHY = "healthy"  # 健康可用
    ERROR = "error"  # 错误状态，暂不接收请求


@dataclass
class BackendState:
    """后端状态管理"""
    url: str
    semaphore: asyncio.Semaphore
    weight: float = 1.0
    max_concurrency: int = 1
    status: BackendStatus = BackendStatus.HEALTHY
    error_count: int = 0  # 连续错误计数
    last_error_time: float = 0.0  # 最后一次错误时间
    total_requests: int = 0  # 总请求数
    success_requests: int = 0  # 成功请求数
    total_response_time: float = 0.0  # 累计响应时间
    last_used_time: float = field(default_factory=lambda: time.time())  # 最后使用时间（用于轮询）
    waiting_count: int = 0  # 自定义等待队列长度
    inflight_requests: int = 0  # 当前正在处理的请求数
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    
    async def mark_success(self, response_time: float = 0.0, completed_at: Optional[float] = None):
        """标记请求成功（返回2xx）"""
        timestamp = completed_at or time.time()
        async with self._lock:
            self.status = BackendStatus.HEALTHY
            self.error_count = 0
            self.total_requests += 1
            self.success_requests += 1
            self.total_response_time += response_time
            self.last_used_time = timestamp
            self._apply_stats_window()
        
    async def mark_error(self, error_at: Optional[float] = None):
        """标记请求失败"""
        timestamp = error_at or time.time()
        async with self._lock:
            self.error_count += 1
            self.total_requests += 1
            self.last_error_time = timestamp
            if self.error_count >= ERROR_THRESHOLD:
                self.status = BackendStatus.ERROR
            self._apply_stats_window()
    
    async def mark_client_error(self, error_at: Optional[float] = None):
        """标记客户端错误（如 4xx），不影响后端健康状态"""
        timestamp = error_at or time.time()
        async with self._lock:
            self.total_requests += 1
            self.last_used_time = timestamp
            self._apply_stats_window()
            
    def should_recover(self, now: Optional[float] = None) -> bool:
        """检查是否应该从错误状态恢复"""
        if self.status != BackendStatus.ERROR:
            return False
        now = now or time.time()
        elapsed = now - self.last_error_time
        return elapsed >= RECOVERY_TIME_S
    
    async def try_recover(self):
        """尝试从错误状态恢复"""
        async with self._lock:
            if self.should_recover():
                self.status = BackendStatus.HEALTHY
                self.error_count = 0
            
    def avg_response_time(self) -> float:
        """平均响应时间（秒）"""
        if self.success_requests == 0:
            return 0.0
        return self.total_response_time / self.success_requests
    
    def _apply_stats_window(self):
        """控制统计数据增长，避免无限累积"""
        if MAX_STATS_WINDOW <= 0:
            return
        if self.total_requests > MAX_STATS_WINDOW:
            self.total_requests = max(self.total_requests // 2, 1)
            self.success_requests = max(self.success_requests // 2, 0)
            self.total_response_time *= 0.5

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化后端状态
    init_backend_states()
    print(f"Initialized {len(backend_states)} backend(s)")
    for url, state in backend_states.items():
        print(
            f"  - {url}: {state.status.value} "
            f"(weight={state.weight}, max_concurrency={state.max_concurrency})"
        )
    yield
    # 关闭时清理资源
    await client.aclose()

app = FastAPI(title="Embedding Gateway", lifespan=lifespan)

# 复用连接的 httpx 客户端
client = httpx.AsyncClient(
    timeout=httpx.Timeout(TIMEOUT_S, connect=min(10.0, TIMEOUT_S)),
    limits=httpx.Limits(
        max_connections=HTTPX_MAX_CONNECTIONS,
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
    ),
)

# 后端状态字典（初始化时创建）
backend_states: Dict[str, BackendState] = {}


def init_backend_states():
    """初始化后端状态"""
    global backend_states
    backend_states = {}
    now = time.time()
    for idx, url in enumerate(EMBEDDING_BACKENDS):
        # 从 BACKEND_WEIGHTS 中读取权重（默认为 1.0）
        weight = BACKEND_WEIGHTS.get(url, 1.0)
        max_concurrency = max(1, int(weight + 0.5))
        backend_states[url] = BackendState(
            url=url,
            semaphore=asyncio.Semaphore(max_concurrency),
            weight=float(weight),
            max_concurrency=int(max_concurrency),
            last_used_time=now + idx * 0.001,
        )


@asynccontextmanager
async def _acquire_backend_slot(state: BackendState):
    """自定义上下文管理器，跟踪 semaphore 等待/执行状态"""
    waiting_tracked = False
    acquired = False
    try:
        if state.semaphore.locked():
            waiting_tracked = True
            async with state._lock:
                state.waiting_count += 1
        try:
            await state.semaphore.acquire()
            acquired = True
            async with state._lock:
                state.inflight_requests += 1
        finally:
            if waiting_tracked:
                async with state._lock:
                    state.waiting_count = max(0, state.waiting_count - 1)
        yield
    finally:
        if acquired:
            state.semaphore.release()
            async with state._lock:
                state.inflight_requests = max(0, state.inflight_requests - 1)


def _semaphore_waiting_queue_length(state: BackendState) -> int:
    """使用自维护计数获取等待队列长度"""
    return max(0, state.waiting_count)


def _backend_available_capacity(state: BackendState) -> int:
    """根据最大并发与当前执行数计算剩余容量"""
    return max(0, state.max_concurrency - state.inflight_requests)


def _backend_capacity_ratio(state: BackendState) -> float:
    """剩余容量占最大并发的比例"""
    max_concurrency = state.max_concurrency if state.max_concurrency > 0 else 1
    return _backend_available_capacity(state) / max_concurrency


def _backend_relative_capacity_score(state: BackendState) -> float:
    """结合权重与容量比例的优先级得分"""
    weight = state.weight if state.weight > 0 else 1.0
    return _backend_capacity_ratio(state) * weight


async def pick_backend() -> Optional[BackendState]:
    """
    选择一个可用的后端
    智能负载均衡策略：
    1. 尝试恢复错误状态的后端
    2. 优先选择容量得分最高的健康后端（容量比例×权重）
    3. 如果所有后端都忙碌，选择等待队列权重代价最低的健康后端
    4. 如果所有后端都错误，返回 None
    """
    # 第一步：尝试恢复错误后端
    for backend in backend_states.values():
        await backend.try_recover()
    
    # 第二步：找到健康且空闲的后端
    idle_healthy_backends = [
        b for b in backend_states.values()
        if b.status == BackendStatus.HEALTHY and _backend_available_capacity(b) > 0
    ]
    
    if idle_healthy_backends:
        # 结合剩余容量比例与权重进行选择：容量越充裕且权重越高，得分越高
        return max(
            idle_healthy_backends,
            key=lambda b: (
                _backend_relative_capacity_score(b),
                b.weight if b.weight > 0 else 0.0,
                -(b.last_used_time if b.last_used_time > 0 else 0.0),
                -b.avg_response_time(),
            ),
        )
    
    # 第三步：所有后端都忙碌，选择等待队列最短的健康后端
    healthy_backends = [
        b for b in backend_states.values() 
        if b.status == BackendStatus.HEALTHY
    ]
    
    if healthy_backends:
        # 考虑权重：用等待队列长度 / weight 作为代价指标，weight 更大意味着更能承担更多等待
        return min(
            healthy_backends,
            key=lambda b: (
                _semaphore_waiting_queue_length(b) / (b.weight if b.weight > 0 else 1.0),
                b.avg_response_time()
            )
        )
    
    # 第四步：所有后端都是错误状态，返回 None
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
    start_time = time.time()
    try:
        resp = await client.post(
            backend_state.url.rstrip("/") + FORWARD_ENDPOINT,
            content=body,
            headers=_forward_headers(headers),
        )
        completed_at = time.time()
        response_time = completed_at - start_time
        
        # 根据状态码更新后端状态
        if _is_success_status(resp.status_code):
            await backend_state.mark_success(response_time, completed_at)
        elif _is_client_error(resp.status_code):
            await backend_state.mark_client_error(completed_at)
        else:
            await backend_state.mark_error(completed_at)
        
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
            headers={k: v for k, v in resp.headers.items() if k.lower() == "x-request-id"},
        )
    except Exception as e:
        # 网络异常也标记为错误
        await backend_state.mark_error()
        raise e


@app.post(PUBLIC_ENDPOINTS[0])
@app.post(PUBLIC_ENDPOINTS[1])
async def embeddings_proxy(req: Request):
    """
    代理 embedding 请求到后端
    使用智能负载均衡的任务分配：
    - 每个后端按权重配置不同的并发数（5/3/1并发）
    - 2xx状态码：后端保持健康状态
    - 4xx状态码：不影响后端健康状态
    - 5xx状态码或异常：后端标记为错误状态
    - 所有后端都不可用时返回502错误
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
        
        # 获取后端的并发槽位（确保不超过该后端的最大并发数）
        async with _acquire_backend_slot(backend_state):
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
            "locked": state.semaphore.locked(),
            "waiting_queue_length": _semaphore_waiting_queue_length(state)
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
            "available_capacity": _backend_available_capacity(state),
            "waiting_queue_length": _semaphore_waiting_queue_length(state),
            "weight": state.weight,
            "max_concurrency": state.max_concurrency,
            "total_requests": state.total_requests,
            "success_requests": state.success_requests,
            "success_rate": round(state.success_requests / state.total_requests * 100, 2) if state.total_requests > 0 else 0,
            "avg_response_time": round(state.avg_response_time(), 3),
            "last_used_time": state.last_used_time if state.last_used_time > 0 else None,
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
        "strategy": "capacity_score_based_load_balancing",
        "backends": backends_info,
        "config": {
            "error_threshold": ERROR_THRESHOLD,
            "recovery_time_s": RECOVERY_TIME_S,
            "concurrency_strategy": "round(weight)",
            "total_configured_concurrency": sum(state.max_concurrency for state in backend_states.values())
        }
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("embedding_gateway:app", host=HOST, port=PORT, reload=False)
