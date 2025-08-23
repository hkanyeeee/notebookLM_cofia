"""JSON Function Calling 策略实现"""
import json
import httpx
from typing import Dict, List, Any, Optional, AsyncGenerator
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry
from ..parsers import ToolCallValidator


class JSONFunctionCallingStrategy:
    """JSON Function Calling 策略（OpenAI 风格）"""
    
    def __init__(self, llm_service_url: str):
        self.llm_service_url = llm_service_url
    
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建 messages 用于 OpenAI 兼容接口"""
        system_prompt = (
            "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，"
            "根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；"
            "你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；"
            "回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、"
            "根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科。"
            "必须使用中文进行回答。"
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加用户问题
        user_content = "参考资料：\n" + "\n".join(context.contexts) + f"\n\n用户问题：{context.question}"
        messages.append({"role": "user", "content": user_content})
        
        # 添加历史步骤
        for step in context.steps:
            if step.step_type == StepType.ACTION and step.tool_call:
                # 助手的工具调用
                tool_call_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": step.tool_call.call_id or f"call_{len(messages)}",
                        "type": "function",
                        "function": {
                            "name": step.tool_call.name,
                            "arguments": json.dumps(step.tool_call.arguments, ensure_ascii=False)
                        }
                    }]
                }
                messages.append(tool_call_msg)
                
            elif step.step_type == StepType.OBSERVATION and step.tool_result:
                # 工具执行结果
                tool_result_msg = {
                    "role": "tool",
                    "tool_call_id": step.tool_result.call_id or f"call_{len(messages)-1}",
                    "content": str(step.tool_result.result)
                }
                messages.append(tool_result_msg)
        
        return messages
    
    def build_payload(self, context: ToolExecutionContext) -> Dict[str, Any]:
        """构建请求 payload"""
        messages = self.build_messages(context)
        
        payload = {
            "model": context.run_config.model,
            "messages": messages,
        }
        
        # 如果有可用工具，添加 tools 参数
        if tool_registry.has_tools():
            tools = []
            for schema in tool_registry.get_all_schemas():
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": schema.name,
                        "description": schema.description,
                        "parameters": schema.parameters
                    }
                }
                tools.append(tool_def)
            
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
        
        return payload
    
    async def call_llm(self, payload: Dict[str, Any], stream: bool = False) -> Any:
        """调用 LLM 服务"""
        if stream:
            payload["stream"] = True
        
        url = f"{self.llm_service_url}/chat/completions"
        
        async with httpx.AsyncClient(timeout=300 if not stream else None) as client:
            if stream:
                response = client.stream("POST", url, json=payload)
                return response
            else:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
    
    def parse_response(self, response_data: Dict[str, Any]) -> tuple[Optional[ToolCall], Optional[str]]:
        """解析 LLM 响应
        
        Returns:
            (tool_call, content) - 工具调用或最终内容
        """
        choices = response_data.get("choices", [])
        if not choices:
            return None, None
        
        message = choices[0].get("message", {})
        
        # 检查是否有工具调用
        tool_calls = message.get("tool_calls")
        if tool_calls:
            # 取第一个工具调用
            tool_call_data = tool_calls[0]
            function_data = tool_call_data.get("function", {})
            
            try:
                arguments = json.loads(function_data.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}
            
            return ToolCall(
                name=function_data.get("name", ""),
                arguments=arguments,
                call_id=tool_call_data.get("id")
            ), None
        
        # 没有工具调用，返回内容
        content = message.get("reasoning_content") or message.get("content") or ""
        return None, content
    
    async def execute_step(self, context: ToolExecutionContext) -> Optional[Step]:
        """执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            response_data = await self.call_llm(payload)
            tool_call, content = self.parse_response(response_data)
            
            if tool_call:
                # 验证工具调用
                if not tool_registry.is_allowed(tool_call.name):
                    return Step(
                        step_type=StepType.OBSERVATION,
                        content=f"错误：工具 '{tool_call.name}' 不在允许列表中",
                        tool_result=ToolResult(
                            name=tool_call.name,
                            result=f"工具 '{tool_call.name}' 不在允许列表中",
                            success=False,
                            error="Tool not allowed",
                            call_id=tool_call.call_id
                        )
                    )
                
                # 参数验证
                tool_schema = tool_registry.get_tool_schema(tool_call.name)
                if tool_schema:
                    is_valid, error_msg = ToolCallValidator.validate_json_schema(
                        tool_call.arguments, tool_schema.parameters
                    )
                    if not is_valid:
                        return Step(
                            step_type=StepType.OBSERVATION,
                            content=f"参数验证失败: {error_msg}",
                            tool_result=ToolResult(
                                name=tool_call.name,
                                result=f"参数验证失败: {error_msg}",
                                success=False,
                                error=error_msg,
                                call_id=tool_call.call_id
                            )
                        )
                
                # 执行工具
                tool_result = await tool_registry.execute_tool(tool_call, context)
                
                return Step(
                    step_type=StepType.OBSERVATION,
                    content=f"Observation: {tool_result.result}",
                    tool_call=tool_call,
                    tool_result=tool_result
                )
            
            elif content:
                # 最终答案
                return Step(
                    step_type=StepType.FINAL_ANSWER,
                    content=content
                )
            
            return None
            
        except Exception as e:
            return Step(
                step_type=StepType.OBSERVATION,
                content=f"LLM 调用出错: {str(e)}"
            )
    
    async def stream_execute_step(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            url = f"{self.llm_service_url}/chat/completions"
            
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    
                    accumulated_content = ""
                    tool_call_data = None
                    
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        
                        try:
                            obj = json.loads(data_str)
                            choices = obj.get("choices", [])
                            if not choices:
                                continue
                            
                            delta = choices[0].get("delta", {})
                            
                            # 检查工具调用
                            tool_calls = delta.get("tool_calls")
                            if tool_calls:
                                # 处理工具调用增量
                                tool_call_delta = tool_calls[0]
                                if tool_call_data is None:
                                    tool_call_data = {
                                        "id": tool_call_delta.get("id", ""),
                                        "function": {
                                            "name": "",
                                            "arguments": ""
                                        }
                                    }
                                
                                function_delta = tool_call_delta.get("function", {})
                                if "name" in function_delta:
                                    tool_call_data["function"]["name"] += function_delta["name"]
                                if "arguments" in function_delta:
                                    tool_call_data["function"]["arguments"] += function_delta["arguments"]
                            
                            # 检查常规内容
                            reasoning_content = delta.get("reasoning_content")
                            content = delta.get("content")
                            
                            if reasoning_content:
                                accumulated_content += reasoning_content
                                yield {"type": "reasoning", "content": reasoning_content}
                            
                            if content:
                                accumulated_content += content
                                yield {"type": "content", "content": content}
                        
                        except Exception:
                            continue
                    
                    # 处理完整的工具调用
                    if tool_call_data and tool_call_data["function"]["name"]:
                        try:
                            arguments = json.loads(tool_call_data["function"]["arguments"] or "{}")
                        except json.JSONDecodeError:
                            arguments = {}
                        
                        tool_call = ToolCall(
                            name=tool_call_data["function"]["name"],
                            arguments=arguments,
                            call_id=tool_call_data["id"]
                        )
                        
                        yield {
                            "type": "action",
                            "name": tool_call.name,
                            "args": tool_call.arguments
                        }
                        
                        # 执行工具
                        if tool_registry.is_allowed(tool_call.name):
                            tool_result = await tool_registry.execute_tool(tool_call, context)
                            
                            yield {
                                "type": "observation",
                                "name": tool_call.name,
                                "result": str(tool_result.result)
                            }
                            
                            # 添加步骤到上下文
                            context.add_step(Step(
                                step_type=StepType.ACTION,
                                content=f"调用工具: {tool_call.name}",
                                tool_call=tool_call
                            ))
                            
                            context.add_step(Step(
                                step_type=StepType.OBSERVATION,
                                content=f"Observation: {tool_result.result}",
                                tool_result=tool_result
                            ))
                        else:
                            yield {
                                "type": "observation", 
                                "name": tool_call.name,
                                "result": f"工具 '{tool_call.name}' 不在允许列表中"
                            }
        
        except Exception as e:
            yield {
                "type": "error",
                "message": f"流式执行出错: {str(e)}"
            }
