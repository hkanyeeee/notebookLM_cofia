"""Harmony DSL 策略实现"""
import json
import httpx
from typing import Dict, List, Any, Optional, AsyncGenerator
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry
from ..parsers import HarmonyParser, ToolCallValidator


class HarmonyStrategy:
    """Harmony DSL 工具标记策略（仅适用于 gpt-oss 模型）"""
    
    def __init__(self, llm_service_url: str):
        self.llm_service_url = llm_service_url
    
    def build_system_prompt(self, context: ToolExecutionContext) -> str:
        """构建 Harmony DSL 系统提示"""
        base_prompt = (
            "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，"
            "根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；"
            "你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；"
            "回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、"
            "根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科。"
            "必须使用中文进行回答。\n\n"
        )
        
        # 添加工具说明
        if tool_registry.has_tools():
            tools_desc = "你可以使用以下工具来获取额外信息：\n"
            for schema in tool_registry.get_all_schemas():
                tools_desc += f"- {schema.name}: {schema.description}\n"
            
            tools_desc += "\n如需使用工具，请使用以下格式：\n"
            tools_desc += '<tool name="工具名称">{"参数名": "参数值"}</tool>\n\n'
            tools_desc += "你可以在回答中使用多个工具调用。每个工具调用完成后，"
            tools_desc += "系统会返回结果，你可以继续使用其他工具或给出最终答案。\n"
            tools_desc += "如果不需要使用工具，请直接给出答案。\n\n"
        else:
            tools_desc = "当前没有可用工具，请直接根据提供的参考资料回答问题。\n\n"
        
        return base_prompt + tools_desc
    
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建 messages"""
        system_prompt = self.build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加用户问题
        user_content = "参考资料：\n" + "\n".join(context.contexts) + f"\n\n用户问题：{context.question}"
        messages.append({"role": "user", "content": user_content})
        
        # 添加历史对话
        for step in context.steps:
            if step.step_type == StepType.REASONING:
                messages.append({"role": "assistant", "content": step.content})
            elif step.step_type == StepType.ACTION and step.tool_call:
                # 工具调用（Harmony 格式）
                tool_content = f'<tool name="{step.tool_call.name}">{json.dumps(step.tool_call.arguments, ensure_ascii=False)}</tool>'
                messages.append({"role": "assistant", "content": tool_content})
            elif step.step_type == StepType.OBSERVATION and step.tool_result:
                # 工具结果
                messages.append({"role": "user", "content": f"工具执行结果：{step.tool_result.result}"})
        
        return messages
    
    def build_payload(self, context: ToolExecutionContext) -> Dict[str, Any]:
        """构建请求 payload"""
        messages = self.build_messages(context)
        
        return {
            "model": context.run_config.model,
            "messages": messages,
        }
    
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
    
    def parse_response(self, response_text: str) -> tuple[List[ToolCall], str]:
        """解析 Harmony DSL 格式的响应
        
        Returns:
            (tool_calls, remaining_content) - 工具调用列表和剩余内容
        """
        tool_calls = HarmonyParser.parse_tool_calls(response_text)
        
        # 移除工具标签，保留其他内容
        remaining_content = response_text
        for tool_call in tool_calls:
            # 简单地移除工具标签（实际实现中可能需要更精确的处理）
            tool_pattern = f'<tool name="{tool_call.name}">[^<]*</tool>'
            import re
            remaining_content = re.sub(tool_pattern, "", remaining_content, flags=re.IGNORECASE | re.DOTALL)
        
        remaining_content = remaining_content.strip()
        
        return tool_calls, remaining_content
    
    async def execute_step(self, context: ToolExecutionContext) -> Optional[Step]:
        """执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            response_data = await self.call_llm(payload)
            
            choices = response_data.get("choices", [])
            if not choices:
                return None
            
            message = choices[0].get("message", {})
            content = message.get("reasoning_content") or message.get("content") or ""
            
            tool_calls, remaining_content = self.parse_response(content)
            
            # 如果有工具调用，先执行第一个工具
            if tool_calls:
                tool_call = tool_calls[0]  # 一次处理一个工具调用
                
                # 验证工具调用
                if not tool_registry.is_allowed(tool_call.name):
                    return Step(
                        step_type=StepType.OBSERVATION,
                        content=f"错误：工具 '{tool_call.name}' 不在允许列表中",
                        tool_result=ToolResult(
                            name=tool_call.name,
                            result=f"工具 '{tool_call.name}' 不在允许列表中",
                            success=False,
                            error="Tool not allowed"
                        )
                    )
                
                # 参数验证和清理
                tool_schema = tool_registry.get_tool_schema(tool_call.name)
                if tool_schema:
                    tool_call.arguments = ToolCallValidator.sanitize_arguments(tool_call.arguments)
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
                                error=error_msg
                            )
                        )
                
                # 执行工具
                tool_result = await tool_registry.execute_tool(tool_call)
                
                return Step(
                    step_type=StepType.OBSERVATION,
                    content=f"工具执行结果：{tool_result.result}",
                    tool_call=tool_call,
                    tool_result=tool_result
                )
            
            # 没有工具调用，返回最终内容
            elif remaining_content:
                return Step(
                    step_type=StepType.FINAL_ANSWER,
                    content=remaining_content
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
                    in_tool_block = False
                    current_tool_content = ""
                    
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
                            reasoning_content = delta.get("reasoning_content")
                            content = delta.get("content")
                            
                            delta_text = reasoning_content or content or ""
                            if not delta_text:
                                continue
                            
                            accumulated_content += delta_text
                            
                            # 检查是否在工具块中
                            if "<tool" in delta_text:
                                in_tool_block = True
                                current_tool_content += delta_text
                            elif in_tool_block:
                                current_tool_content += delta_text
                                if "</tool>" in delta_text:
                                    # 工具块结束，解析工具调用
                                    tool_calls = HarmonyParser.parse_tool_calls(current_tool_content)
                                    if tool_calls:
                                        tool_call = tool_calls[0]
                                        
                                        yield {
                                            "type": "action",
                                            "name": tool_call.name,
                                            "args": tool_call.arguments
                                        }
                                        
                                        # 执行工具
                                        if tool_registry.is_allowed(tool_call.name):
                                            tool_result = await tool_registry.execute_tool(tool_call)
                                            
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
                                                content=f"工具执行结果：{tool_result.result}",
                                                tool_result=tool_result
                                            ))
                                        else:
                                            yield {
                                                "type": "observation",
                                                "name": tool_call.name,
                                                "result": f"工具 '{tool_call.name}' 不在允许列表中"
                                            }
                                    
                                    in_tool_block = False
                                    current_tool_content = ""
                            else:
                                # 普通内容
                                if reasoning_content:
                                    yield {"type": "reasoning", "content": reasoning_content}
                                elif content:
                                    yield {"type": "content", "content": content}
                        
                        except Exception:
                            continue
        
        except Exception as e:
            yield {
                "type": "error",
                "message": f"流式执行出错: {str(e)}"
            }
