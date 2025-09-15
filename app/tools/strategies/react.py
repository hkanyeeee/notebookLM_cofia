"""ReAct 策略实现"""
import json
import httpx
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
        
        # 检查是否是最后一次工具调用机会
        current_action_count = sum(1 for step in context.steps if step.step_type == StepType.ACTION)
        max_steps = context.run_config.get_max_steps()
        is_last_chance = current_action_count >= max_steps - 1
        
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
            
            if is_last_chance:
                tools_desc += f"\n**重要警告**：这是您最后一次工具调用机会（已使用{current_action_count}/{max_steps}步）！请谨慎选择最重要的工具，使用后必须立即使用'Final Answer:'给出完整的最终答案，不能再进行任何工具调用。\n"
            tools_desc += "\n**网络搜索使用原则**：\n"
            tools_desc += "1. 避免重复或过度相似的搜索：在Thought中仔细检查是否已搜索过相同或相似内容\n"
            tools_desc += "2. 基于前次结果判断：每次Observation后评估是否已获得足够信息回答问题\n"
            tools_desc += "3. 渐进式搜索：如需多次搜索，确保每次都有明确的新信息获取目标\n"
            tools_desc += "4. 合理终止：合理终止：对于简单查询（如天气、新闻），一次搜索即可，当获得足够信息时及时使用'Final Answer:'给出答案\n"
            tools_desc += "5. 搜索效率：优先使用精准关键词，避免宽泛无效的查询\n"
            tools_desc += "当你有足够信息回答问题时，请输出：\n"
            tools_desc += "Final Answer: [你的最终答案]\n\n"
        else:
            tools_desc = "当前没有可用工具，请直接根据提供的参考资料回答问题。\n\n"
        
        return base_prompt + tools_desc
    
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建 messages"""
        system_prompt = self.build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加外部对话历史（如果存在）
        if context.conversation_history:
            messages.extend(context.conversation_history)
        
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
    
    def _build_web_search_history(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """从上下文中构建 web_search 的历史记录，用于策略层面的历史传递"""
        search_history = []
        
        # 使用基类的方法获取 web_search 工具的历史
        web_search_history = self._get_tool_call_history(context, "web_search")
        
        for record in web_search_history:
            if record["success"]:
                query = record["arguments"].get("query", "")
                if query:
                    search_history.append({
                        "query": query,
                        "result_summary": record["result"][:300] + "..." if len(record["result"]) > 300 else record["result"]
                    })
        
        return search_history
    
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
                # 如果是web_search，构建搜索历史并传递
                if tool_call.name == "web_search":
                    search_history = self._build_web_search_history(context)
                    if search_history:
                        tool_call.arguments["search_history"] = search_history
                        print(f"[ReAct Strategy] 传递搜索历史: {len(search_history)} 条记录")
                
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
                        elif final_answer:
                            # 无工具调用但模型直接给出最终答案
                            final_text = final_answer.strip()
                            if final_text:
                                yield {
                                    "type": "final_answer",
                                    "content": final_text
                                }
                                context.add_step(Step(
                                    step_type=StepType.FINAL_ANSWER,
                                    content=final_text
                                ))
        
        except Exception as e:
            yield {
                "type": "error",
                "message": f"流式执行出错: {str(e)}"
            }
    
    async def force_final_answer(self, context: ToolExecutionContext) -> Step:
        """当达到工具调用步数限制时，强制生成最终答案"""
        try:
            # 构建强制最终答案的消息
            messages = self.build_messages_for_final_answer(context)
            payload = {
                "model": context.run_config.model or "gpt-oss-20b",
                "messages": messages,
                "stream": False,
                "temperature": 0.1,
            }
            
            response = await self.call_llm(payload, stream=False)
            if isinstance(response, dict):
                content = self.extract_response_content(response).strip()
                if content:
                    return Step(
                        step_type=StepType.FINAL_ANSWER,
                        content=content
                    )
            
            # 兜底答案
            return Step(
                step_type=StepType.FINAL_ANSWER,
                content="根据已收集的信息，我无法提供更详细的答案。请重新表述您的问题或提供更多背景信息。"
            )
            
        except Exception as e:
            return Step(
                step_type=StepType.FINAL_ANSWER,
                content=f"在生成最终答案时遇到错误：{str(e)}。请重新尝试您的查询。"
            )
    
    async def stream_force_final_answer(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式强制生成最终答案"""
        try:
            # 构建强制最终答案的消息
            messages = self.build_messages_for_final_answer(context)
            payload = {
                "model": context.run_config.model or "gpt-oss-20b",
                "messages": messages,
                "stream": True,
                "temperature": 0.1,
            }
            
            ctx = await self.call_llm(payload, stream=True)
            async with ctx as response:
                response.raise_for_status()
                accumulated_content = ""
                
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        if accumulated_content.strip():
                            yield {
                                "type": "final_answer",
                                "content": accumulated_content.strip(),
                                "message": "已达到最大工具调用步数限制，基于当前信息生成最终答案"
                            }
                            context.add_step(Step(
                                step_type=StepType.FINAL_ANSWER,
                                content=accumulated_content.strip()
                            ))
                        continue
                    
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            reasoning_content, content = self.parse_stream_delta(delta)
                            
                            if reasoning_content:
                                yield {"type": "reasoning", "content": reasoning_content}
                            
                            if content:
                                accumulated_content += content
                                yield {"type": "content", "content": content}
                                
                    except (json.JSONDecodeError, KeyError) as e:
                        continue
        
        except Exception as e:
            yield {
                "type": "error",
                "message": f"强制生成最终答案时出错: {str(e)}"
            }
    
    def build_messages_for_final_answer(self, context: ToolExecutionContext) -> List[Dict[str, str]]:
        """构建用于强制生成最终答案的消息"""
        messages = []
        
        # 添加系统提示
        system_prompt = self.build_system_prompt(context)
        system_prompt += f"\n\n**重要提示**：您已达到最大工具调用步数限制({context.run_config.get_max_steps()}步)。请基于当前已收集的所有信息，直接使用'Final Answer: '格式提供完整的最终答案，不要再使用任何工具。如果信息不完整，请说明这一点，并基于现有信息给出最佳回答。"
        
        messages.append({"role": "system", "content": system_prompt})
        
        # 添加用户内容和步骤历史
        messages.extend(context.get_conversation_history())
        
        return messages