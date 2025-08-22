"""工具注册表"""
from typing import Dict, List, Optional, Any, Callable
import asyncio
from .models import ToolSchema, ToolCall, ToolResult


class ToolRegistry:
    """工具注册表，管理可用工具的注册、查找和执行"""
    
    def __init__(self):
        self._tools: Dict[str, ToolSchema] = {}
        self._handlers: Dict[str, Callable] = {}
    
    def register_tool(self, schema: ToolSchema, handler: Callable):
        """注册工具
        
        Args:
            schema: 工具定义 Schema
            handler: 工具执行函数，可以是同步或异步函数
        """
        self._tools[schema.name] = schema
        self._handlers[schema.name] = handler
    
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
    
    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """执行工具调用
        
        Args:
            tool_call: 工具调用请求
            
        Returns:
            工具执行结果
        """
        print(f"[Registry] 收到工具调用请求: {tool_call.name}, 参数: {tool_call.arguments}")
        
        if not self.is_allowed(tool_call.name):
            print(f"[Registry] 工具未找到或不允许: {tool_call.name}")
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 不在允许列表中",
                success=False,
                error="Tool not allowed",
                call_id=tool_call.call_id
            )
        
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
        
        try:
            print(f"[Registry] 开始执行工具处理函数: {tool_call.name}")
            # 执行工具函数
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**tool_call.arguments)
            else:
                result = handler(**tool_call.arguments)
                
            print(f"[Registry] 工具执行成功: {tool_call.name}, 结果长度: {len(str(result)) if result else 0}")
            return ToolResult(
                name=tool_call.name,
                result=result,
                success=True,
                call_id=tool_call.call_id
            )
            
        except Exception as e:
            print(f"[Registry] 工具执行异常: {tool_call.name}, 错误: {str(e)}")
            return ToolResult(
                name=tool_call.name,
                result=f"工具执行出错：{str(e)}",
                success=False,
                error=str(e),
                call_id=tool_call.call_id
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
                }
            },
            "required": ["query"]
        }
    )
    
    tool_registry.register_tool(web_search_schema, web_search)


# 注册所有工具
def register_all_tools():
    """注册所有可用工具"""
    register_web_search_tool()


# 自动注册工具
register_all_tools()


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
