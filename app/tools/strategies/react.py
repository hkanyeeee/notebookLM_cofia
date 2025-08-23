"""ReAct 策略实现"""
import json
from typing import Dict, List, Any, Optional, AsyncGenerator
from .base import BaseStrategy
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry
from ..parsers import ReActParser


class ReActStrategy(BaseStrategy):
    """ReAct (Reason + Act) 策略实现"""
    
    def __init__(self, llm_service_url: str):
        super().__init__(llm_service_url)
    
    def build_system_prompt(self, context: ToolExecutionContext) -> str:
        """构建 ReAct 系统提示"""
        base_prompt = self.build_base_system_prompt()
        
        # 添加工具说明
        if tool_registry.has_tools():
            tools_desc = "你可以使用以下工具来获取额外信息（如需要）：\n"
            allowed_tools = self.get_allowed_tools(context)
            for schema in tool_registry.get_all_schemas():
                if schema.name in allowed_tools:
                    tools_desc += f"- {schema.name}: {schema.description}\n"
            
            tools_desc += "\n请严格按照以下格式进行推理和操作：\n"
            tools_desc += "Thought: [你的思考过程]\n"
            tools_desc += "Action: [工具名称]\n"
            tools_desc += "Action Input: {\"key\": \"value\"}\n"
            tools_desc += "Observation: [工具返回结果，由系统自动填写]\n"
            tools_desc += "\n你可以重复 Thought -> Action -> Action Input -> Observation 的循环。\n"
            tools_desc += "当你有足够信息回答问题时，请输出：\n"
            tools_desc += "Final Answer: [你的最终答案]\n\n"
        else:
            tools_desc = "当前没有可用工具，请直接根据提供的参考资料回答问题。\n\n"
        
        return base_prompt + tools_desc
    
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建 messages"""
        system_prompt = self.build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加用户问题
        messages.append({"role": "user", "content": self.build_user_content(context)})
        
        # 添加历史对话
        current_content = ""
        
        for step in context.steps:
            if step.step_type == StepType.REASONING:
                current_content += f"Thought: {step.content}\n"
            elif step.step_type == StepType.ACTION and step.tool_call:
                current_content += f"Action: {step.tool_call.name}\n"
                current_content += f"Action Input: {json.dumps(step.tool_call.arguments, ensure_ascii=False)}\n"
            elif step.step_type == StepType.OBSERVATION and step.tool_result:
                current_content += f"Observation: {step.tool_result.result}\n"
                
                # 添加完整的轮次到消息
                if current_content.strip():
                    messages.append({"role": "assistant", "content": current_content.strip()})
                    current_content = ""
        
        # 添加未完成的内容
        if current_content.strip():
            messages.append({"role": "assistant", "content": current_content.strip()})
        
        return messages
    
    def build_payload(self, context: ToolExecutionContext) -> Dict[str, Any]:
        """构建请求 payload"""
        messages = self.build_messages(context)
        
        return {
            "model": context.run_config.model,
            "messages": messages,
        }
    

    
    def parse_response(self, response_text: str) -> tuple[Optional[ToolCall], Optional[str], Optional[str]]:
        """解析 ReAct 格式的响应
        
        Returns:
            (tool_call, final_answer, thought) - 工具调用、最终答案或思考内容
        """
        # 检查是否是最终答案
        final_answer = ReActParser.extract_final_answer(response_text)
        if final_answer:
            return None, final_answer, None
        
        # 检查是否有工具调用
        tool_call = ReActParser.parse_tool_call(response_text)
        if tool_call:
            return tool_call, None, None
        
        # 提取思考内容
        thought = ReActParser.extract_thought(response_text)
        if thought:
            return None, None, thought
        
        # 如果都没有，返回原始内容作为最终答案
        return None, response_text.strip(), None
    
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
            
            tool_call, final_answer, thought = self.parse_response(content)
            
            if final_answer:
                return Step(
                    step_type=StepType.FINAL_ANSWER,
                    content=final_answer
                )
            
            elif tool_call:
                # 执行工具（包含所有验证）
                tool_result = await self.execute_tool_with_validation(tool_call, context)
                return self.create_observation_step(tool_call, tool_result, format_content=True)
            
            elif thought:
                return Step(
                    step_type=StepType.REASONING,
                    content=thought
                )
            
            return None
            
        except Exception as e:
            return self.create_error_step(f"LLM 调用出错: {str(e)}", error=e)
    
    async def stream_execute_step(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            url = f"{self.llm_service_url}/chat/completions"
            
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    
                    accumulated_content = ""
                    
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
                            
                            if reasoning_content:
                                accumulated_content += reasoning_content
                                yield {"type": "reasoning", "content": reasoning_content}
                            
                            if content:
                                accumulated_content += content
                                yield {"type": "content", "content": content}
                        
                        except Exception:
                            continue
                    
                    # 解析完整内容
                    if accumulated_content:
                        tool_call, final_answer, thought = self.parse_response(accumulated_content)
                        
                        if tool_call and tool_registry.is_allowed(tool_call.name):
                            yield {
                                "type": "action",
                                "name": tool_call.name,
                                "args": tool_call.arguments
                            }
                            
                            # 执行工具
                            tool_result = await tool_registry.execute_tool(tool_call, context)
                            
                            yield {
                                "type": "observation",
                                "name": tool_call.name,
                                "result": str(tool_result.result),
                                "success": tool_result.success,
                                "latency_ms": tool_result.latency_ms,
                                "retries": tool_result.retries,
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
        
        except Exception as e:
            yield {
                "type": "error",
                "message": f"流式执行出错: {str(e)}"
            }
