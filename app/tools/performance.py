"""工具系统性能优化模块"""
import asyncio
import time
import weakref
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import threading
from functools import wraps

from .models import ToolCall, ToolResult, ToolExecutionContext
from .observability import global_observability


@dataclass
class PerformanceConfig:
    """性能配置"""
    # 连接池配置
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 30.0
    
    # 并发控制
    max_concurrent_tools: int = 10
    max_concurrent_requests: int = 50
    
    # 超时配置
    default_timeout: float = 300.0
    connection_timeout: float = 30.0
    
    # 线程池配置
    thread_pool_workers: int = 4
    
    # 批处理配置
    batch_size: int = 10
    batch_timeout: float = 1.0
    
    # 预热配置
    enable_warmup: bool = True
    warmup_requests: int = 3


class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self, config: Optional[PerformanceConfig] = None):
        self.config = config or PerformanceConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_tools)
        self._request_semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        
        # 线程池执行器
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.config.thread_pool_workers,
            thread_name_prefix="tool_executor"
        )
        
        # 批处理队列
        self._batch_queue: asyncio.Queue = asyncio.Queue()
        self._batch_processor_task: Optional[asyncio.Task] = None
        self._start_batch_processor()
        
        # 预热缓存
        self._warmup_cache: Dict[str, Any] = {}
        
        # 性能统计
        self._performance_stats = {
            'total_requests': 0,
            'concurrent_requests': 0,
            'avg_response_time': 0.0,
            'batch_processed': 0,
            'cache_hits': 0
        }
        self._stats_lock = threading.Lock()
    
    def _start_batch_processor(self):
        """启动批处理器"""
        if self._batch_processor_task is None:
            self._batch_processor_task = asyncio.create_task(self._process_batches())
    
    async def _process_batches(self):
        """批处理队列处理器"""
        batch = []
        last_process_time = time.time()
        
        while True:
            try:
                # 等待新项目或超时
                timeout = max(0.1, self.config.batch_timeout - (time.time() - last_process_time))
                try:
                    item = await asyncio.wait_for(self._batch_queue.get(), timeout=timeout)
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass
                
                # 检查是否应该处理批次
                should_process = (
                    len(batch) >= self.config.batch_size or
                    (batch and time.time() - last_process_time >= self.config.batch_timeout)
                )
                
                if should_process and batch:
                    await self._process_batch(batch)
                    batch.clear()
                    last_process_time = time.time()
                    
                    with self._stats_lock:
                        self._performance_stats['batch_processed'] += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                global_observability.logger.error("批处理器错误", error=str(e))
                await asyncio.sleep(1)
    
    async def _process_batch(self, batch: List[Dict[str, Any]]):
        """处理一个批次的操作"""
        if not batch:
            return
        
        global_observability.logger.debug("处理批次", batch_size=len(batch))
        
        # 根据操作类型分组
        grouped_operations = {}
        for item in batch:
            op_type = item.get('type', 'default')
            if op_type not in grouped_operations:
                grouped_operations[op_type] = []
            grouped_operations[op_type].append(item)
        
        # 并发处理不同类型的操作
        tasks = []
        for op_type, operations in grouped_operations.items():
            task = asyncio.create_task(self._process_operation_group(op_type, operations))
            tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_operation_group(self, op_type: str, operations: List[Dict[str, Any]]):
        """处理同类型操作组"""
        for operation in operations:
            try:
                callback = operation.get('callback')
                if callback and callable(callback):
                    await callback(operation)
            except Exception as e:
                global_observability.logger.error(
                    "批处理操作失败", 
                    op_type=op_type, 
                    error=str(e)
                )
    
    @asynccontextmanager
    async def concurrent_limit(self, limit_type: str = "tool"):
        """并发限制上下文管理器"""
        semaphore = self._semaphore if limit_type == "tool" else self._request_semaphore
        
        async with semaphore:
            with self._stats_lock:
                self._performance_stats['concurrent_requests'] += 1
            
            try:
                yield
            finally:
                with self._stats_lock:
                    self._performance_stats['concurrent_requests'] -= 1
    
    def performance_monitor(self, func: Callable):
        """性能监控装饰器"""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            
            async with self.concurrent_limit():
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    duration = time.perf_counter() - start_time
                    self._update_performance_stats(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            
            try:
                # 在线程池中执行同步函数
                loop = asyncio.get_event_loop()
                result = loop.run_in_executor(self._thread_pool, func, *args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start_time
                self._update_performance_stats(duration)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    def _update_performance_stats(self, duration: float):
        """更新性能统计"""
        with self._stats_lock:
            self._performance_stats['total_requests'] += 1
            total = self._performance_stats['total_requests']
            current_avg = self._performance_stats['avg_response_time']
            
            # 计算移动平均
            self._performance_stats['avg_response_time'] = (
                (current_avg * (total - 1) + duration) / total
            )
    
    async def warm_up_tool(self, tool_name: str, sample_args: Dict[str, Any]):
        """预热工具"""
        if not self.config.enable_warmup:
            return
        
        global_observability.logger.info("预热工具", tool_name=tool_name)
        
        for i in range(self.config.warmup_requests):
            try:
                # 这里应该调用实际的工具，但为了避免副作用，我们只是模拟
                start_time = time.perf_counter()
                await asyncio.sleep(0.001)  # 模拟极短的执行时间
                duration = time.perf_counter() - start_time
                
                self._warmup_cache[f"{tool_name}_{i}"] = {
                    'duration': duration,
                    'timestamp': time.time()
                }
                
            except Exception as e:
                global_observability.logger.warning(
                    "工具预热失败", 
                    tool_name=tool_name, 
                    attempt=i + 1, 
                    error=str(e)
                )
    
    async def batch_execute_tools(
        self,
        tool_calls: List[ToolCall],
        executor_func: Callable,
        context: Optional[ToolExecutionContext] = None
    ) -> List[ToolResult]:
        """批量执行工具"""
        if not tool_calls:
            return []
        
        global_observability.logger.info("批量执行工具", count=len(tool_calls))
        
        # 限制并发数量
        semaphore = asyncio.Semaphore(min(len(tool_calls), self.config.max_concurrent_tools))
        
        async def execute_with_semaphore(tool_call: ToolCall) -> ToolResult:
            async with semaphore:
                try:
                    return await executor_func(tool_call, context)
                except Exception as e:
                    global_observability.logger.error(
                        "批量工具执行失败",
                        tool_name=tool_call.name,
                        error=str(e)
                    )
                    return ToolResult(
                        name=tool_call.name,
                        result=f"执行失败: {str(e)}",
                        success=False,
                        error=str(e),
                        call_id=tool_call.call_id
                    )
        
        # 并发执行所有工具
        tasks = [execute_with_semaphore(tool_call) for tool_call in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ToolResult(
                    name=tool_calls[i].name,
                    result=f"执行异常: {str(result)}",
                    success=False,
                    error=str(result),
                    call_id=tool_calls[i].call_id
                ))
            else:
                final_results.append(result)
        
        return final_results
    
    def add_to_batch_queue(self, operation: Dict[str, Any]):
        """添加操作到批处理队列"""
        try:
            self._batch_queue.put_nowait(operation)
        except asyncio.QueueFull:
            global_observability.logger.warning("批处理队列已满，跳过操作")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        with self._stats_lock:
            return {
                **self._performance_stats.copy(),
                'warmup_cache_size': len(self._warmup_cache),
                'batch_queue_size': self._batch_queue.qsize(),
                'thread_pool_workers': self._thread_pool._threads if hasattr(self._thread_pool, '_threads') else 0
            }
    
    async def optimize_memory(self):
        """内存优化"""
        # 清理过期的预热缓存
        current_time = time.time()
        expired_keys = [
            key for key, value in self._warmup_cache.items()
            if current_time - value['timestamp'] > 3600  # 1小时过期
        ]
        
        for key in expired_keys:
            del self._warmup_cache[key]
        
        global_observability.logger.debug("内存优化完成", cleaned_warmup_items=len(expired_keys))
    
    async def close(self):
        """清理资源"""
        # 关闭批处理器
        if self._batch_processor_task:
            self._batch_processor_task.cancel()
            try:
                await self._batch_processor_task
            except asyncio.CancelledError:
                pass
        
        # 关闭线程池
        self._thread_pool.shutdown(wait=True)
        
        global_observability.logger.info("性能优化器已关闭")


class CircuitBreaker:
    """断路器模式实现"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Exception = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs):
        """通过断路器调用函数"""
        async with self._lock:
            # 检查断路器状态
            if self.state == 'OPEN':
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = 'HALF_OPEN'
                    global_observability.logger.info("断路器进入半开状态")
                else:
                    raise Exception("断路器打开，服务不可用")
            
            try:
                result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
                
                # 调用成功，重置计数器
                if self.state == 'HALF_OPEN':
                    self.state = 'CLOSED'
                    global_observability.logger.info("断路器关闭")
                self.failure_count = 0
                return result
                
            except self.expected_exception as e:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                if self.failure_count >= self.failure_threshold:
                    self.state = 'OPEN'
                    global_observability.logger.warning(
                        "断路器打开", 
                        failure_count=self.failure_count,
                        threshold=self.failure_threshold
                    )
                
                raise e


# 全局性能优化器实例
global_performance_optimizer = PerformanceOptimizer()
