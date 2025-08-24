"""工具注册表"""
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING
import asyncio
import time
import random
from .models import ToolSchema, ToolCall, ToolResult, ToolMetadata
from .parsers import ToolCallValidator
# 错误处理已简化，使用标准Python异常
# 缓存功能已简化
# 可观测性功能已简化

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
        # 简化日志系统
    
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
        
        # 缓存功能已简化
    
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
        print(f"[Registry] 收到工具调用请求: {tool_call.name}, 参数: {tool_call.arguments}, call_id: {tool_call.call_id}")
        
        if not self.is_allowed(tool_call.name):
            print(f"[Registry] 工具未找到或不允许: {tool_call.name}")
            # 记录被拒绝的工具调用
            print(f"[Registry] 工具调用被拒绝: {tool_call.name}")
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 不在允许列表中",
                success=False,
                error="Tool not allowed",
                call_id=tool_call.call_id
            )
        
        # 缓存功能已简化直接执行工具
        meta = self._metadata.get(tool_call.name) or ToolMetadata()
        
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
                        # 参数验证失败是不可重试的错误，直接抛出特殊异常
                        raise ValueError(f"参数验证失败: {err}")
                except ValueError as ve:
                    # 参数验证错误不应重试
                    raise ve
                except Exception as ve:
                    # 其他验证异常也不应重试
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
                    
                    # 缓存功能已简化
                    
                    return tool_result
                except asyncio.TimeoutError as e:
                    last_error = e
                    print(f"[Registry] 工具超时: {tool_call.name} after {timeout_s}s (尝试 {attempt+1})")
                except ValueError as e:
                    # 参数验证失败等不可重试的错误，立即返回
                    if "参数验证失败" in str(e):
                        last_error = e
                        print(f"[Registry] 工具执行异常: {tool_call.name}, 错误: {str(e)} (尝试 {attempt+1})")
                        break  # 立即跳出重试循环
                    else:
                        last_error = e
                        print(f"[Registry] 工具执行异常: {tool_call.name}, 错误: {str(e)} (尝试 {attempt+1})")
                except Exception as e:
                    last_error = e
                    print(f"[Registry] 工具执行异常: {tool_call.name}, 错误: {str(e)} (尝试 {attempt+1})")
                attempt += 1
                if attempt <= max_retries and last_error and "参数验证失败" not in str(last_error):
                    # 只有非参数验证错误才进行重试等待
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
        
        # 简化错误处理
        if last_error:
            print(f"[Registry] 工具执行错误处理: {tool_call.name} - {str(last_error)}")
            error_message = str(last_error)
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
        cache_enabled=False  # 简化系统，暂时禁用缓存
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
