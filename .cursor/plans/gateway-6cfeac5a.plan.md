<!-- 6cfeac5a-8404-4fb8-a6f3-90ace8447ff9 4bc2cced-7a05-4939-9b1d-35ff220cc4ae -->
# Gateway 安全加固与优化方案

## 修复范围

修复 `llm_gateway.py` 和 `embedding_gateway.py` 中的 10 个风险点，按风险等级从高到低依次处理。

---

## 🔴 高风险问题修复

### 1. Embedding Gateway - 移除 `_waiters` 私有属性访问

**位置：** `embedding_gateway.py:130-138`

**问题：** 直接访问 `asyncio.Semaphore._waiters` 私有属性，不同 Python 版本可能为 None 或不存在，导致功能异常。

**修复方案：**

- 使用公开的 API 或自定义等待队列跟踪机制
- 方案1：维护自己的等待队列计数器（推荐）
- 方案2：通过 `semaphore.locked()` 和自定义计数器实现
```python
# 为每个 BackendState 添加 waiting_count 属性
@dataclass
class BackendState:
    # ... 现有字段 ...
    waiting_count: int = 0  # 等待队列计数

# 在 acquire/release 时更新计数
```


### 2. LLM Gateway - 修复流式响应状态标记时机

**位置：** `llm_gateway.py:215-223`

**问题：** 在流式响应开始时就 `mark_success()`，但实际流传输可能失败，导致统计不准确。

**修复方案：**

- 流式响应应在流完成后才标记成功
- 将成功标记移到 `_stream_forward_with_release()` 的 finally 块
- 非200状态码的流式响应也需要正确标记错误
```python
async def _stream_forward_with_release(resp: httpx.Response, backend: str, backend_state: BackendState, start_time: float):
    try:
        async for chunk in resp.aiter_raw():
            if chunk:
                yield chunk
        # 流成功完成，标记成功
        if resp.status_code == 200:
            backend_state.mark_success(time.time() - start_time)
    except Exception:
        backend_state.mark_error()
        raise
    finally:
        await release_backend(backend)
```


### 3. 两个 Gateway - 添加 BackendState 并发保护锁

**位置：** 两个文件的 `BackendState` 类

**问题：** 多个协程同时修改 `BackendState` 的统计字段，存在数据竞争。

**修复方案：**

- 为每个 `BackendState` 添加 `asyncio.Lock`
- 所有修改状态的方法（`mark_success`, `mark_error`, `try_recover`）使用锁保护
```python
@dataclass
class BackendState:
    # ... 现有字段 ...
    _lock: asyncio.Lock = None
    
    def __post_init__(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
    
    async def mark_success(self, response_time: float = 0.0):
        async with self._lock:
            # 原有逻辑
```


---

## 🟡 中等风险问题修复

### 4. 环境变量配置验证增强

**位置：** 两个文件的启动配置部分

**问题：** 环境变量解析失败时，程序可能使用错误的默认值或崩溃。

**修复方案：**

- 添加配置验证函数，启动时检查关键配置
- 对数值类型的环境变量添加范围检查
- 对 URL 列表进行格式验证
```python
def validate_config():
    """验证并规范化配置"""
    # 检查后端列表不为空
    # 检查端口在合法范围
    # 检查超时时间为正数
    # 检查权重值合理性
```


### 5. 扩展状态码判断逻辑

**位置：** 两个文件的响应处理逻辑

**问题：** 只判断 `status_code == 200`，2xx 范围内的其他成功状态码被误判为失败。

**修复方案：**

- 使用 `200 <= status_code < 300` 判断成功
- 对 4xx 和 5xx 分别处理（客户端错误 vs 服务端错误）

### 6. Embedding Gateway - 时间比较精度优化

**位置：** `embedding_gateway.py` 中使用时间比较的地方

**问题：** 后端初始化阶段 `last_used_time` 为 0，可能导致排序异常。

**修复方案：**

- 初始化时使用当前时间戳而非 0
- 或在比较逻辑中特殊处理 0 值（已部分处理，需检查一致性）

### 7. LLM Gateway - 统一后端状态字典键

**位置：** `llm_gateway.py` 多处使用 `rstrip("/")`

**问题：** 部分地方用原始 URL，部分地方用 `rstrip("/")`，可能导致键不匹配。

**修复方案：**

- 创建 `normalize_backend_url()` 辅助函数
- 所有访问 `backend_states` 字典时统一使用规范化的键

---

## 🟢 低风险问题优化

### 8. 统计数据增长控制

**位置：** 两个文件的 `BackendState` 统计字段

**问题：** `total_requests`, `total_response_time` 无限累积，长时间运行可能溢出。

**修复方案：**

- 添加统计数据重置机制（可选）
- 使用滑动窗口统计最近 N 次请求（推荐）
- 或添加定期重置逻辑（每天零点重置）

### 9. httpx 连接池优化

**位置：** 两个文件的 `httpx.AsyncClient` 创建

**问题：** 未配置连接池限制，极高并发时可能资源耗尽。

**修复方案：**

- 配置 `limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)`
- 根据后端数量和并发需求调整参数

### 10. 时间调用性能优化

**位置：** 频繁调用 `time.time()` 的地方

**问题：** 每次请求多次调用 `time.time()`，高并发时有轻微开销。

**修复方案：**

- 在请求开始时记录一次时间，复用该时间戳
- 合并相邻的时间记录调用

---

## 实施顺序

1. 高风险问题（1-3）：立即修复，影响系统稳定性
2. 中等风险问题（4-7）：优先修复，提升健壮性
3. 低风险问题（8-10）：渐进优化，提升性能

## 测试要点

- 并发请求测试（验证锁保护）
- 流式响应异常中断测试
- 后端故障切换测试
- 长时间运行稳定性测试
- 不同 Python 版本兼容性测试（3.9-3.12）

### To-dos

- [ ] 移除 Embedding Gateway 中的 _waiters 私有属性访问，使用自定义等待队列计数器
- [ ] 修复 LLM Gateway 流式响应状态标记时机，将成功标记移到流完成后
- [ ] 为两个 Gateway 的 BackendState 添加并发保护锁
- [ ] 添加环境变量配置验证函数，启动时检查关键配置
- [ ] 扩展状态码判断逻辑，支持 2xx 范围内的成功响应
- [ ] 优化 Embedding Gateway 时间比较精度问题
- [ ] 统一 LLM Gateway 后端状态字典键，创建规范化函数
- [ ] 添加统计数据增长控制机制
- [ ] 优化 httpx 连接池配置
- [ ] 优化时间调用性能
- [ ] 进行并发测试、流式测试和长时间运行测试