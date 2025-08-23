"""工具注册表"""
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
import asyncio
import time
import random
from .models import ToolSchema, ToolCall, ToolResult, ToolMetadata
from .parsers import ToolCallValidator
from .errors import (
    global_error_handler, ToolExecutionError, TimeoutError, 
    ValidationError, NetworkError
)
from .cache import global_tool_cache, CacheConfig
from .observability import global_observability

if TYPE_CHECKING:
    from .models import ToolExecutionContext


class ToolRegistry:
    """工具注册表，管理可用工具的注册、查找和执行"""
    
    def __init__(self):
        self._tools: Dict[str, ToolSchema] = {}
        self._handlers: Dict[str, Callable] = {}
        self._metadata: Dict[str, ToolMetadata] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        # 简单断路器：当连续失败次数超过阈值时短时间拒绝请求
        self._cb_failures: Dict[str, int] = {}
        self._cb_open_until: Dict[str, float] = {}
        self.logger = global_observability.get_logger("registry")
    
    def register_tool(self, schema: ToolSchema, handler: Callable, metadata: Optional[ToolMetadata] = None):
        """注册工具
        
        Args:
            schema: 工具定义 Schema
            handler: 工具执行函数，可以是同步或异步函数
            metadata: 工具运行元数据（超时、重试、并发等）
        """
        self._tools[schema.name] = schema
        self._handlers[schema.name] = handler
        meta = metadata or ToolMetadata()
        self._metadata[schema.name] = meta
        # 为每个工具创建并发限流器
        self._semaphores[schema.name] = asyncio.Semaphore(max(1, meta.max_concurrency))
        
        # 配置工具缓存
        if meta.cache_enabled:
            cache_config = CacheConfig(
                ttl_seconds=meta.cache_ttl or 3600.0,  # 默认1小时
                max_size=meta.cache_max_size or 1000,
                namespace=f"tool_{schema.name}"
            )
            global_tool_cache.configure_tool(schema.name, cache_config)
    
    def get_tool_schema(self, name: str) -> Optional[ToolSchema]:
        """获取工具 Schema"""
        return self._tools.get(name)
    
    def get_all_schemas(self) -> List[ToolSchema]:
        """获取所有工具 Schema"""
        return list(self._tools.values())
    
    def is_allowed(self, name: str) -> bool:
        """检查工具是否在允许列表中"""
        return name in self._tools
    
    def has_tools(self) -> bool:
        """检查是否有可用工具"""
        return len(self._tools) > 0
    
    async def execute_tool(self, tool_call: ToolCall, context: Optional['ToolExecutionContext'] = None) -> ToolResult:
        """执行工具调用
        
        Args:
            tool_call: 工具调用请求
            
        Returns:
            工具执行结果
        """
        self.logger.info("收到工具调用请求", 
                         tool_name=tool_call.name, 
                         arguments=tool_call.arguments,
                         call_id=tool_call.call_id)
        
        if not self.is_allowed(tool_call.name):
            self.logger.warning("工具未找到或不允许", tool_name=tool_call.name)
            global_observability.metrics_collector.counter('tool_requests_rejected', 1.0, {'tool': tool_call.name, 'reason': 'not_allowed'})
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 不在允许列表中",
                success=False,
                error="Tool not allowed",
                call_id=tool_call.call_id
            )
        
        # 检查缓存
        meta = self._metadata.get(tool_call.name) or ToolMetadata()
        if meta.cache_enabled:
            self.logger.debug("检查缓存", tool_name=tool_call.name)
            cached_result = await global_tool_cache.get(tool_call.name, tool_call.arguments)
            if cached_result is not None:
                self.logger.info("缓存命中", tool_name=tool_call.name)
                global_observability.performance_monitor.record_cache_hit(tool_call.name, hit=True)
                # 从缓存恢复ToolResult
                if isinstance(cached_result, dict) and 'name' in cached_result:
                    cached_tool_result = ToolResult(**cached_result)
                    cached_tool_result.call_id = tool_call.call_id  # 更新call_id
                    return cached_tool_result
                else:
                    # 兼容简单值缓存
                    return ToolResult(
                        name=tool_call.name,
                        result=cached_result,
                        success=True,
                        call_id=tool_call.call_id,
                        latency_ms=0.0,  # 缓存命中，延迟为0
                        retries=0
                    )
            else:
                global_observability.performance_monitor.record_cache_hit(tool_call.name, hit=False)
        
        handler = self._handlers.get(tool_call.name)
        if not handler:
            print(f"[Registry] 未找到工具处理函数: {tool_call.name}")
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 没有对应的执行函数",
                success=False,
                error="Handler not found",
                call_id=tool_call.call_id
            )
        meta = self._metadata.get(tool_call.name) or ToolMetadata()
        # 上下文覆盖元数据
        timeout_s = meta.timeout_s
        max_retries = meta.max_retries
        if context:
            try:
                if context.run_config.tool_timeouts and tool_call.name in context.run_config.tool_timeouts:
                    timeout_s = float(context.run_config.tool_timeouts[tool_call.name])
                if context.run_config.tool_max_retries and tool_call.name in context.run_config.tool_max_retries:
                    max_retries = int(context.run_config.tool_max_retries[tool_call.name])
            except Exception:
                pass

        semaphore = self._semaphores.get(tool_call.name) or asyncio.Semaphore(meta.max_concurrency)

        async def _invoke_once() -> Any:
            # 准备工具函数参数
            tool_args = dict(tool_call.arguments)
            # 参数清理与校验（双保险）
            schema = self.get_tool_schema(tool_call.name)
            if schema:
                try:
                    tool_args = ToolCallValidator.sanitize_arguments(tool_args)
                    ok, err = ToolCallValidator.validate_json_schema(tool_args, schema.parameters)
                    if not ok:
                        raise ValueError(f"参数验证失败: {err}")
                except Exception as ve:
                    raise ve
            # 自动注入模型参数
            if context and hasattr(handler, '__code__'):
                param_names = handler.__code__.co_varnames[:handler.__code__.co_argcount]
                if 'model' in param_names and 'model' not in tool_args:
                    if context.run_config.model:
                        tool_args['model'] = context.run_config.model
                        print(f"[Registry] 自动传递模型参数: {context.run_config.model}")
            # 执行工具函数
            if asyncio.iscoroutinefunction(handler):
                return await handler(**tool_args)
            return handler(**tool_args)

        # 重试与超时
        attempt = 0
        start = time.perf_counter()
        last_error: Optional[Exception] = None
        async with semaphore:
            # 断路器：检查是否打开
            import time as _time
            now = _time.monotonic()
            if tool_call.name in self._cb_open_until and now < self._cb_open_until[tool_call.name]:
                return ToolResult(
                    name=tool_call.name,
                    result=f"工具临时不可用（断路器打开）",
                    success=False,
                    error="circuit_open",
                    call_id=tool_call.call_id,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    retries=0,
                )
            while attempt <= max_retries:
                try:
                    print(f"[Registry] 开始执行工具处理函数: {tool_call.name}, 尝试 {attempt+1}/{max_retries+1}, 超时 {timeout_s}s")
                    if timeout_s and timeout_s > 0:
                        result = await asyncio.wait_for(_invoke_once(), timeout=timeout_s)
                    else:
                        result = await _invoke_once()
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    print(f"[Registry] 工具执行成功: {tool_call.name}, 用时 {latency_ms:.1f}ms, 结果长度: {len(str(result)) if result else 0}")
                    # 重置断路器计数
                    self._cb_failures[tool_call.name] = 0
                    
                    tool_result = ToolResult(
                        name=tool_call.name,
                        result=result,
                        success=True,
                        call_id=tool_call.call_id,
                        latency_ms=latency_ms,
                        retries=attempt,
                    )
                    
                    # 缓存成功的结果
                    if meta.cache_enabled:
                        try:
                            await global_tool_cache.put(
                                tool_call.name, 
                                tool_call.arguments,
                                tool_result.dict(),  # 缓存整个ToolResult
                                ttl=meta.cache_ttl
                            )
                            print(f"[Registry] 结果已缓存: {tool_call.name}")
                        except Exception as cache_error:
                            print(f"[Registry] 缓存保存失败: {cache_error}")
                    
                    return tool_result
                except asyncio.TimeoutError as e:
                    last_error = e
                    print(f"[Registry] 工具超时: {tool_call.name} after {timeout_s}s (尝试 {attempt+1})")
                except Exception as e:
                    last_error = e
                    print(f"[Registry] 工具执行异常: {tool_call.name}, 错误: {str(e)} (尝试 {attempt+1})")
                attempt += 1
                if attempt <= max_retries:
                    # 指数退避 + 抖动
                    backoff = min(1.5 ** attempt, 10.0) * (0.5 + random.random())
                    try:
                        await asyncio.sleep(backoff)
                    except Exception:
                        pass

        latency_ms = (time.perf_counter() - start) * 1000.0
        # 打开断路器：连续失败计数+窗口
        self._cb_failures[tool_call.name] = self._cb_failures.get(tool_call.name, 0) + 1
        if self._cb_failures[tool_call.name] >= 3:
            open_seconds = min(30.0 * self._cb_failures[tool_call.name], 300.0)
            import time as _time
            self._cb_open_until[tool_call.name] = _time.monotonic() + open_seconds
            print(f"[Registry] 断路器打开: {tool_call.name} {open_seconds:.0f}s")
        
        # 使用错误处理器处理最终错误
        if last_error:
            error_info = global_error_handler.handle_error(
                last_error, 
                context={'tool_name': tool_call.name, 'retries': max_retries}
            )
            error_message = error_info['user_message']
        else:
            error_message = '未知错误'
        
        return ToolResult(
            name=tool_call.name,
            result=f"工具执行出错：{error_message}",
            success=False,
            error=str(last_error) if last_error else 'Unknown',
            call_id=tool_call.call_id,
            latency_ms=latency_ms,
            retries=max_retries,
        )


# 全局注册表实例
tool_registry = ToolRegistry()


# 注册 Web 搜索工具
def register_web_search_tool():
    """注册 Web 搜索工具"""
    from .web_search_tool import web_search
    
    web_search_schema = ToolSchema(
        name="web_search",
        description="搜索网络信息并进行智能召回。能够生成搜索关键词，从网络搜索相关内容，爬取网页，进行文档切分、向量化索引，并基于用户查询召回最相关的内容片段。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询内容，可以是问题、关键词或主题"
                },
                "language": {
                    "type": "string",
                    "description": "语言过滤器，用于指定搜索结果的语言。默认为 'en-US'",
                    "default": "en-US"
                },
                "categories": {
                    "type": "string",
                    "description": "搜索类别列表，用于限制搜索范围到特定类别。默认为空字符串（所有类别）",
                    "default": ""
                },
                "filter_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "域名过滤列表，包含需要从搜索结果中排除的域名。例如：['example.com', 'badsite.org']"
                },
                "model": {
                    "type": "string",
                    "description": "用于关键词生成的LLM模型名称，默认使用系统配置。传入此参数可覆盖系统默认模型",
                    "default": ""
                }
            },
            "required": ["query"]
        }
    )
    # 默认元数据：较长超时、适度并发、有限重试、启用缓存
    meta = ToolMetadata(
        timeout_s=600.0, 
        max_retries=1, 
        max_concurrency=4,
        cache_enabled=True,
        cache_ttl=1800.0,  # 30分钟缓存
        cache_max_size=500
    )
    tool_registry.register_tool(web_search_schema, web_search, metadata=meta)


# 注册所有工具
def register_all_tools():
    """注册所有可用工具"""
    register_web_search_tool()


# 注意：工具注册将在 orchestrator 初始化时执行，避免循环导入
# register_all_tools()  # 移除自动注册


# 示例：注册一个简单的测试工具（当前注释掉）
"""
def echo_tool(message: str) -> str:
    '''简单的回显工具，用于测试'''
    return f"Echo: {message}"

# 注册测试工具
test_schema = ToolSchema(
    name="echo",
    description="回显输入的消息",
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "要回显的消息"
            }
        },
        "required": ["message"]
    }
)

tool_registry.register_tool(test_schema, echo_tool)
"""
