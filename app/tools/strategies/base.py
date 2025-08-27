"""基础策略类 - 抽取公共功能"""
import json
import httpx
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry
from ..parsers import ToolCallValidator
# 错误处理和可观测性功能已简化


class BaseStrategy(ABC):
    """工具调用策略的抽象基类"""
    
    def __init__(self, llm_service_url: str):
        self.llm_service_url = llm_service_url
        self._http_client: Optional[httpx.AsyncClient] = None
        # 简化日志系统
    
    async def get_http_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端（单例模式，复用连接）"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(1800.0, connect=30.0),  # 30分钟超时
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
            )
        return self._http_client
    
    async def close(self):
        """关闭HTTP客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
    
    def build_base_system_prompt(self) -> str:
        """构建基础系统提示"""
        return (
            "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，"
            "根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；"
            "你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；"
            "回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、"
            "根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科。"
            "\n\n**重要要求：必须完全使用中文进行回答。**\n\n"
        )
    
    def build_user_content(self, context: ToolExecutionContext) -> str:
        """构建用户内容"""
        return "参考资料：\n" + "\n".join(context.contexts) + f"\n\n用户问题：{context.question}"
    
    def get_allowed_tools(self, context: ToolExecutionContext) -> List[str]:
        """获取允许使用的工具名称列表"""
        allowed_names = None
        try:
            if context.run_config and context.run_config.tools:
                allowed_names = {t.name for t in context.run_config.tools}
        except Exception:
            allowed_names = None
        
        if allowed_names is not None:
            return [schema.name for schema in tool_registry.get_all_schemas() 
                   if schema.name in allowed_names]
        else:
            return [schema.name for schema in tool_registry.get_all_schemas()]
    
    async def call_llm(self, payload: Dict[str, Any], stream: bool = False) -> Union[Dict[str, Any], httpx.Response]:
        """调用LLM服务的通用方法"""
        if stream:
            payload["stream"] = True
        
        url = f"{self.llm_service_url}/chat/completions"
        
        print(f"[BaseStrategy] 调用LLM服务: {self.__class__.__name__} - {url}, model={payload.get('model')}, stream={stream}")
        
        try:
            # 指标收集已简化
            client = await self.get_http_client()
            
            if stream:
                return client.stream("POST", url, json=payload)
            else:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                print(f"[BaseStrategy] LLM调用成功: {self.__class__.__name__} - model={payload.get('model')}, response_size={len(str(result))}")
                return result
                
        except httpx.TimeoutException as e:
            print(f"[BaseStrategy] LLM服务调用超时: {self.__class__.__name__} - {str(e)}, url={url}")
            print(f"[BaseStrategy] LLM请求超时: {self.__class__.__name__}")
            raise TimeoutError(f"LLM服务调用超时: {str(e)}")
        except httpx.NetworkError as e:
            print(f"[BaseStrategy] LLM网络连接错误: {self.__class__.__name__} - {str(e)}, url={url}")
            print(f"[BaseStrategy] 网络错误: {self.__class__.__name__}")
            raise ConnectionError(f"网络连接错误: {str(e)}")
        except httpx.HTTPStatusError as e:
            print(f"[BaseStrategy] LLM HTTP错误: {self.__class__.__name__} - status_code={e.response.status_code}, error={str(e)}, url={url}")
            if e.response.status_code == 429:
                print(f"[BaseStrategy] 频率限制: {self.__class__.__name__}")
                raise ValueError(f"请求频率过高: {str(e)}")
            elif e.response.status_code in [401, 403]:
                print(f"[BaseStrategy] 认证错误: {self.__class__.__name__}")
                raise PermissionError(f"认证或权限错误: {str(e)}")
            else:
                print(f"[BaseStrategy] HTTP错误: {self.__class__.__name__}")
                raise ConnectionError(f"HTTP错误 {e.response.status_code}: {str(e)}")
        except Exception as e:
            print(f"[BaseStrategy] LLM调用未知错误: {self.__class__.__name__} - error={str(e)}, error_type={type(e).__name__}, url={url}")
            print(f"[BaseStrategy] 未知错误: {self.__class__.__name__}")
            raise RuntimeError(f"LLM调用出现未知错误: {str(e)}")
    
    def validate_tool_call(self, tool_call: ToolCall, context: ToolExecutionContext) -> Optional[ToolResult]:
        """验证工具调用，如果有问题返回错误结果"""
        # 检查工具是否在允许列表中
        allowed_names = set(self.get_allowed_tools(context))
        if tool_call.name not in allowed_names:
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 不在允许列表中",
                success=False,
                error="Tool not permitted by run_config",
                call_id=tool_call.call_id
            )
        
        # 检查工具是否注册
        if not tool_registry.is_allowed(tool_call.name):
            return ToolResult(
                name=tool_call.name,
                result=f"工具 '{tool_call.name}' 不在注册表中",
                success=False,
                error="Tool not registered",
                call_id=tool_call.call_id
            )
        
        # 参数验证
        tool_schema = tool_registry.get_tool_schema(tool_call.name)
        if tool_schema:
            try:
                tool_call.arguments = ToolCallValidator.sanitize_arguments(tool_call.arguments)
                is_valid, error_msg = ToolCallValidator.validate_json_schema(
                    tool_call.arguments, tool_schema.parameters
                )
                if not is_valid:
                    return ToolResult(
                        name=tool_call.name,
                        result=f"参数验证失败: {error_msg}",
                        success=False,
                        error=error_msg,
                        call_id=tool_call.call_id
                    )
            except Exception as e:
                return ToolResult(
                    name=tool_call.name,
                    result=f"参数处理异常: {str(e)}",
                    success=False,
                    error=str(e),
                    call_id=tool_call.call_id
                )
        
        return None  # 验证通过
    
    async def execute_tool_with_validation(self, tool_call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        """执行工具调用，包含完整验证"""
        # 验证工具调用
        validation_error = self.validate_tool_call(tool_call, context)
        if validation_error:
            return validation_error
        
        # 执行工具
        return await tool_registry.execute_tool(tool_call, context)
    
    def create_observation_step(self, tool_call: ToolCall, tool_result: ToolResult, format_content: bool = True) -> Step:
        """创建观察步骤"""
        if format_content:
            content = f"Observation: {tool_result.result}"
        else:
            content = f"工具执行结果：{tool_result.result}"
        
        return Step(
            step_type=StepType.OBSERVATION,
            content=content,
            tool_call=tool_call,
            tool_result=tool_result
        )
    
    def create_error_step(self, error_msg: str, error: Optional[Exception] = None) -> Step:
        """创建错误步骤"""
        if error:
            print(f"[BaseStrategy] 策略执行错误: {self.__class__.__name__} - {str(error)}")
            content = f"执行出错: {str(error)}"
        else:
            content = f"执行出错: {error_msg}"
        
        return Step(
            step_type=StepType.OBSERVATION,
            content=content
        )
    
    def extract_response_content(self, response_data: Dict[str, Any]) -> str:
        """从LLM响应中提取内容"""
        choices = response_data.get("choices", [])
        if not choices:
            return ""
        
        message = choices[0].get("message", {})
        return message.get("reasoning_content") or message.get("content") or ""
    
    def parse_stream_delta(self, delta: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """解析流式响应的delta内容"""
        reasoning_content = delta.get("reasoning_content")
        content = delta.get("content")
        return reasoning_content, content
    
    # 抽象方法，子类必须实现
    @abstractmethod
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建消息列表"""
        pass
    
    @abstractmethod
    def build_payload(self, context: ToolExecutionContext) -> Dict[str, Any]:
        """构建请求payload"""
        pass
    
    @abstractmethod
    async def execute_step(self, context: ToolExecutionContext) -> Optional[Step]:
        """执行单个步骤"""
        pass
    
    @abstractmethod
    async def stream_execute_step(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行单个步骤"""
        pass
