import os
import asyncio
import time
import json
from typing import List, Dict, Optional
from collections import defaultdict
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from contextlib import asynccontextmanager


def normalize_backend_url(url: str) -> str:
    return url.rstrip("/")


def _split_backends(raw: str) -> List[str]:
    return [normalize_backend_url(item.strip()) for item in raw.split(",") if item.strip()]


def _get_env_float(name: str, default: float, *, min_value: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= min_value else default


def _get_env_int(name: str, default: int, *, min_value: int = 0, max_value: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if value < min_value:
        value = default
    if max_value is not None and value > max_value:
        value = default
    return value


def _is_success_status(status_code: int) -> bool:
    return 200 <= status_code < 300


def _is_client_error(status_code: int) -> bool:
    return 400 <= status_code < 500


DEFAULT_LLM_BACKENDS = "http://192.168.31.231:1234/v1,http://192.168.31.98:1234/v1,http://192.168.31.60:1234/v1"

# 后端实例列表（逗号分隔），均为 OpenAI 风格基址（通常以 /v1 结尾）
LLM_BACKENDS: List[str] = _split_backends(
    os.getenv("LLM_BACKENDS", DEFAULT_LLM_BACKENDS)
)

# 允许针对某个后端的模型名进行映射（直接在脚本里配置）：
# 例如：{"http://192.168.31.231:1234/v1": {"alias-model": "real-model"}}
MODEL_NAME_MAP: Dict[str, Dict[str, str]] = {
    # "http://192.168.31.231:1234/v1": {"alias-model": "real-model"},
    # "*": {"alias-model": "real-model"},  # 全局默认映射
    "http://192.168.31.231:1234/v1": {
        "qwen/qwen3-vl-30b": "qwen3-vl-30b-a3b-instruct",
    },
    "http://192.168.31.98:1234/v1": {
        "qwen/qwen3-vl-30b": "unsloth/qwen3-vl-30b-a3b-instruct",
        "qwen3-30b-a3b-thinking-2507-mlx": "qwen3-30b-a3b-thinking-2507",
        "qwen/qwen3-coder-30b": "unsloth/qwen3-coder-30b-a3b-instruct",
        "qwen/qwen3-30b-a3b-2507": "unsloth/qwen3-30b-a3b-instruct-2507"
    },
    "http://192.168.31.60:1234/v1": {
        "qwen/qwen3-vl-30b": "qwen/qwen3-vl-8b",
    },
    "http://192.168.31.174:1234/v1": {
        "qwen/qwen3-vl-30b": "qwen/qwen3-vl-8b",
    },
}

# 可配置的后端权重（按算力/优先级）
_RAW_BACKEND_WEIGHTS = {
    "http://192.168.31.231:1234/v1": 26.0,
    "http://192.168.31.98:1234/v1": 13.0,
    "http://192.168.31.60:1234/v1": 10.0,
    # "http://192.168.31.174:1234/v1": 1.0,
}
BACKEND_WEIGHTS = {normalize_backend_url(k): float(v) for k, v in _RAW_BACKEND_WEIGHTS.items()}

# 公共前缀：保持 OpenAI 风格 /v1/*
PUBLIC_PREFIX = "/v1"

# 网关监听地址
HOST = os.getenv("LLM_GATEWAY_HOST", "0.0.0.0")
PORT = _get_env_int("LLM_GATEWAY_PORT", 7995, min_value=1, max_value=65535)

# 超时
TIMEOUT_S = _get_env_float("LLM_TIMEOUT", 600.0, min_value=1.0)

ERROR_THRESHOLD = _get_env_int("BACKEND_ERROR_THRESHOLD", 3, min_value=1)
RECOVERY_TIME_S = _get_env_int("BACKEND_RECOVERY_TIME", 30, min_value=1)
MAX_STATS_WINDOW = _get_env_int("BACKEND_STATS_WINDOW", 10000, min_value=0)
HTTPX_MAX_CONNECTIONS = _get_env_int("HTTPX_MAX_CONNECTIONS", 200, min_value=1)
HTTPX_MAX_KEEPALIVE = _get_env_int("HTTPX_MAX_KEEPALIVE_CONNECTIONS", 40, min_value=0)


def validate_config():
    if not LLM_BACKENDS:
        raise ValueError("LLM_BACKENDS must include at least one backend URL.")
    invalid = [url for url in LLM_BACKENDS if not url.startswith("http")]
    if invalid:
        raise ValueError(f"Invalid LLM backend URLs: {invalid}")
    non_positive_weights = [
        url for url in LLM_BACKENDS if BACKEND_WEIGHTS.get(url, 1.0) <= 0
    ]
    if non_positive_weights:
        raise ValueError(f"LLM backend weights must be positive: {non_positive_weights}")
    if not (1 <= PORT <= 65535):
        raise ValueError(f"LLM_GATEWAY_PORT out of range: {PORT}")
    if TIMEOUT_S <= 0:
        raise ValueError("LLM_TIMEOUT must be positive.")


validate_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化后端状态
    init_backend_states()
    print(f"Initialized {len(backend_states)} LLM backend(s)")
    for url, state in backend_states.items():
        print(f"  - {url}: {state.status} (weight={state.weight})")
    yield
    await client.aclose()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)

# 最少连接数负载均衡：跟踪每个后端的活跃连接数
_backend_connections: Dict[str, int] = defaultdict(int)
_connections_lock = asyncio.Lock()

# 后端状态管理（错误计数 / 自动恢复 / 响应统计）
class BackendStatus:
    HEALTHY = "healthy"
    ERROR = "error"

@dataclass
class BackendState:
    url: str
    weight: float = 1.0
    status: str = BackendStatus.HEALTHY
    error_count: int = 0
    last_error_time: float = 0.0
    total_requests: int = 0
    success_requests: int = 0
    total_response_time: float = 0.0
    last_used_time: float = field(default_factory=lambda: time.time())
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def mark_success(self, response_time: float = 0.0, completed_at: Optional[float] = None):
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
        timestamp = error_at or time.time()
        async with self._lock:
            self.error_count += 1
            self.total_requests += 1
            self.last_error_time = timestamp
            if self.error_count >= ERROR_THRESHOLD:
                self.status = BackendStatus.ERROR
            self._apply_stats_window()
    
    async def mark_client_error(self, error_at: Optional[float] = None):
        timestamp = error_at or time.time()
        async with self._lock:
            self.total_requests += 1
            self.last_used_time = timestamp
            self._apply_stats_window()

    def should_recover(self) -> bool:
        if self.status != BackendStatus.ERROR:
            return False
        return (time.time() - self.last_error_time) >= RECOVERY_TIME_S

    async def try_recover(self):
        async with self._lock:
            if self.should_recover():
                self.status = BackendStatus.HEALTHY
                self.error_count = 0

    def avg_response_time(self) -> float:
        if self.success_requests == 0:
            return 0.0
        return self.total_response_time / self.success_requests

    async def record_use(self, used_at: Optional[float] = None):
        timestamp = used_at or time.time()
        async with self._lock:
            self.last_used_time = timestamp

    def _apply_stats_window(self):
        if MAX_STATS_WINDOW <= 0:
            return
        if self.total_requests > MAX_STATS_WINDOW:
            self.total_requests = max(self.total_requests // 2, 1)
            self.success_requests = max(self.success_requests // 2, 0)
            self.total_response_time *= 0.5

# 全局后端状态字典，键为规范化后的 base
backend_states: Dict[str, BackendState] = {}

def init_backend_states():
    global backend_states
    backend_states = {}
    for backend in LLM_BACKENDS:
        weight = BACKEND_WEIGHTS.get(backend, 1.0)
        backend_states[backend] = BackendState(url=backend, weight=float(weight))

# 复用 httpx 客户端
client = httpx.AsyncClient(
    timeout=httpx.Timeout(TIMEOUT_S, connect=min(10.0, TIMEOUT_S)),
    limits=httpx.Limits(
        max_connections=HTTPX_MAX_CONNECTIONS,
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
    ),
)


async def pick_backend() -> str:
    """选择当前活跃连接数最少且考虑权重与健康状态的后端"""
    async with _connections_lock:
        # 尝试恢复处于 ERROR 状态的后端（如果达到恢复时间）
        for state in backend_states.values():
            await state.try_recover()

        backends = LLM_BACKENDS

        # 优先使用 HEALTHY 后端，如果没有健康后端则退化为所有后端
        def is_healthy(backend_url: str) -> bool:
            state = backend_states.get(backend_url)
            return state.status == BackendStatus.HEALTHY if state else True

        healthy = [b for b in backends if is_healthy(b)]
        candidate_pool = healthy if healthy else backends

        def effective_load(backend_url: str) -> float:
            state = backend_states.get(backend_url)
            weight = state.weight if state else BACKEND_WEIGHTS.get(backend_url, 1.0)
            w = weight if weight > 0 else 1.0
            return _backend_connections[backend_url] / w

        selected = min(
            candidate_pool,
            key=lambda b: (
                effective_load(b),
                backend_states.get(b).avg_response_time() if backend_states.get(b) else 0.0,
            ),
        )
        # 增加连接计数并更新使用时间
        _backend_connections[selected] += 1
        state = backend_states.get(selected)
        if state:
            await state.record_use()
        return selected


async def release_backend(backend: str):
    """释放后端连接计数"""
    async with _connections_lock:
        _backend_connections[backend] = max(0, _backend_connections[backend] - 1)


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


def _resolve_model_alias(backend_base: str, model: str) -> Optional[str]:
    backend_map = MODEL_NAME_MAP.get(backend_base)
    if backend_map and model in backend_map:
        return backend_map[model]
    default_map = MODEL_NAME_MAP.get("*") or MODEL_NAME_MAP.get("default")
    if default_map and model in default_map:
        return default_map[model]
    return None


def _maybe_map_model(backend_base: str, body: bytes, headers: dict) -> bytes:
    if not MODEL_NAME_MAP or not body:
        return body
    content_type = headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return body
    try:
        payload = json.loads(body)
    except Exception:
        return body
    if not isinstance(payload, dict):
        return body
    model = payload.get("model")
    if not model:
        return body
    mapped_model = _resolve_model_alias(backend_base, str(model))
    if not mapped_model or mapped_model == model:
        return body
    payload["model"] = mapped_model
    return json.dumps(payload).encode("utf-8")


async def _record_backend_result(
    status_code: int,
    backend_state: Optional[BackendState],
    response_time: float,
    completed_at: Optional[float] = None,
):
    if backend_state is None:
        return
    try:
        if _is_success_status(status_code):
            await backend_state.mark_success(response_time, completed_at)
        elif _is_client_error(status_code):
            await backend_state.mark_client_error(completed_at)
        else:
            await backend_state.mark_error(completed_at)
    except Exception:
        # 统计逻辑不影响主流程
        pass


async def _stream_forward_with_release(
    resp: httpx.Response,
    backend: str,
    backend_state: Optional[BackendState],
    start_time: float,
):
    """流式转发，完成后释放后端连接并更新统计"""
    try:
        async for chunk in resp.aiter_raw():
            if chunk:
                yield chunk
        completed_at = time.time()
        await _record_backend_result(
            resp.status_code,
            backend_state,
            completed_at - start_time,
            completed_at,
        )
    except Exception:
        if backend_state:
            await backend_state.mark_error()
        raise
    finally:
        await release_backend(backend)
        await resp.aclose()


async def _forward(req: Request, backend_base: str) -> Response:
    method = req.method
    raw_path = req.url.path
    raw_query = req.url.query
    body = await req.body()
    headers = _filter_request_headers(dict(req.headers))
    body = _maybe_map_model(backend_base, body, headers)

    upstream_url = _build_upstream_url(backend_base, raw_path, raw_query)
    backend_state = backend_states.get(backend_base)

    # 使用流式响应以支持 SSE/分块，并记录响应时间与成功/失败
    start_time = time.time()
    try:
        upstream_resp = await client.request(method, upstream_url, content=body, headers=headers)
    except Exception:
        if backend_state:
            await backend_state.mark_error()
        await release_backend(backend_base)
        raise

    media_type = upstream_resp.headers.get("content-type", "application/json")
    response_headers = _filter_response_headers(upstream_resp.headers)

    # 判断是否为流式（SSE 或 chunked），通过 content-type 或 transfer-encoding
    is_stream = (
        (media_type and media_type.startswith("text/event-stream"))
        or upstream_resp.headers.get("transfer-encoding", "").lower() == "chunked"
    )

    if is_stream:
        # 流式响应：在流完成后释放连接并在生成器内标记状态
        return StreamingResponse(
            _stream_forward_with_release(upstream_resp, backend_base, backend_state, start_time),
            media_type=media_type,
            headers=response_headers,
            status_code=upstream_resp.status_code
        )
    else:
        # 非流式响应：立即释放连接
        try:
            completed_at = time.time()
            await _record_backend_result(
                upstream_resp.status_code,
                backend_state,
                completed_at - start_time,
                completed_at,
            )
            return Response(
                content=upstream_resp.content,
                media_type=media_type,
                headers=response_headers,
                status_code=upstream_resp.status_code
            )
        finally:
            await release_backend(backend_base)
            await upstream_resp.aclose()


async def _try_all_backends(req: Request) -> Response:
    tried: List[str] = []
    last_err = None
    for _ in range(len(LLM_BACKENDS)):
        backend = await pick_backend()
        if backend in tried:
            # 如果已经尝试过这个后端，释放连接计数
            await release_backend(backend)
            continue
        tried.append(backend)
        try:
            return await _forward(req, backend)
        except Exception as e:
            # 请求失败，释放连接计数
            await release_backend(backend)
            # 标记后端错误
            try:
                state = backend_states.get(backend)
                if state:
                    await state.mark_error()
            except Exception:
                pass
            last_err = e
            continue
    return JSONResponse(status_code=502, content={"detail": "All LLM backends unavailable", "backends": tried, "error": str(last_err)})


# 捕获所有 /v1/* 路由并转发（POST/GET/DELETE/PATCH/PUT 等都支持）
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_all(req: Request, path: str):
    return await _try_all_backends(req)


@app.get("/health")
async def health():
    async with _connections_lock:
        backend_status = []
        for backend in LLM_BACKENDS:
            state = backend_states.get(backend)
            info = {
                "url": backend,
                "active_connections": _backend_connections[backend],
                "weight": BACKEND_WEIGHTS.get(backend, 1.0)
            }
            if state:
                info.update({
                    "status": state.status,
                    "error_count": state.error_count,
                    "total_requests": state.total_requests,
                    "success_requests": state.success_requests,
                    "avg_response_time": round(state.avg_response_time(), 3),
                    "last_used_time": state.last_used_time if state.last_used_time > 0 else None,
                    "last_error_time": state.last_error_time if state.last_error_time > 0 else None
                })
            backend_status.append(info)
    return {
        "ok": True,
        "strategy": "weighted_least_connections",
        "backends": backend_status
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("llm_gateway:app", host=HOST, port=PORT, reload=False)
