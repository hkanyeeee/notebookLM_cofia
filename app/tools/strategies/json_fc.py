"""JSON Function Calling 策略实现"""
import json
from typing import Dict, List, Any, Optional, AsyncGenerator
from .base import BaseStrategy
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry


class JSONFunctionCallingStrategy(BaseStrategy):
    """JSON Function Calling 策略（OpenAI 风格）"""
    
    def __init__(self, llm_service_url: str):
        super().__init__(llm_service_url)
    
    def build_messages(self, context: ToolExecutionContext) -> List[Dict[str, Any]]:
        """构建 messages 用于 OpenAI 兼容接口"""
        # 构建系统提示，包含步数限制信息
        system_prompt = self.build_base_system_prompt()
        
        # 检查是否是最后一次工具调用机会
        current_action_count = sum(1 for step in context.steps if step.step_type == StepType.ACTION)
        max_steps = context.run_config.get_max_steps()
        is_last_chance = current_action_count >= max_steps - 1
        
        if is_last_chance:
            system_prompt += f"\n\n**重要警告**：这是您最后一次函数调用机会（已使用{current_action_count}/{max_steps}步）！请谨慎选择最重要的工具，使用后必须立即基于结果给出完整的最终答案，不能再进行任何函数调用。"
        
        system_prompt += (
            "\n\n**网络搜索使用原则**：\n"
            "1. 合理终止：对于简单查询（如天气、新闻），一次搜索即可\n"
            "2. 避免重复或过度相似的搜索：仔细检查是否已搜索过相同或相似内容\n"
            "3. 基于前次结果判断：每次搜索后评估是否已获得足够信息回答问题\n"
            "4. 搜索效率：优先使用精准关键词，避免宽泛无效的查询\n"
        )
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加外部对话历史（如果存在）
        if context.conversation_history:
            messages.extend(context.conversation_history)
        
        # 添加用户问题
        messages.append({"role": "user", "content": self.build_user_content(context)})
        
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
            allowed_tools = self.get_allowed_tools(context)
            tools = []
            registry_schemas = tool_registry.get_all_schemas()
            for schema in registry_schemas:
                if schema.name in allowed_tools:
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
        content = self.extract_response_content(response_data)
        return None, content
    
    async def execute_step(self, context: ToolExecutionContext) -> Optional[Step]:
        """执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            response_data = await self.call_llm(payload)
            tool_call, content = self.parse_response(response_data)
            
            if tool_call:
                # 如果是web_search，构建搜索历史并传递
                if tool_call.name == "web_search":
                    search_history = self._build_web_search_history(context)
                    if search_history:
                        tool_call.arguments["search_history"] = search_history
                        print(f"[JSON FC Strategy] 传递搜索历史: {len(search_history)} 条记录")
                
                # 执行工具（包含所有验证）
                tool_result = await self.execute_tool_with_validation(tool_call, context)
                return self.create_observation_step(tool_call, tool_result, format_content=True)
            
            elif content:
                # 最终答案
                return Step(
                    step_type=StepType.FINAL_ANSWER,
                    content=content
                )
            
            return None
            
        except Exception as e:
            return self.create_error_step(f"LLM 调用出错: {str(e)}", error=e)
    
    async def stream_execute_step(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行单个步骤"""
        payload = self.build_payload(context)
        
        try:
            client = await self.get_http_client()
            async with await self.call_llm(payload, stream=True) as response:
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
                            reasoning_content, content = self.parse_stream_delta(delta)
                            
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

                    # 如果没有工具调用但产生了内容，视为直接最终答案
                    if not (tool_call_data and tool_call_data["function"]["name"]) and accumulated_content.strip():
                        final_text = accumulated_content.strip()
                        yield {
                            "type": "final_answer",
                            "content": final_text
                        }
                        # 记录最终答案步骤，便于 orchestrator 判断终止
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
                "model": context.run_config.model or "openai/gpt-oss-20b",
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
                "model": context.run_config.model or "openai/gpt-oss-20b",
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
        system_prompt += f"\n\n**重要提示**：您已达到最大工具调用步数限制({context.run_config.get_max_steps()}步)。请基于当前已收集的所有信息，直接提供完整的最终答案，不要再进行任何函数调用。如果信息不完整，请说明这一点，并基于现有信息给出最佳回答。"
        
        messages.append({"role": "system", "content": system_prompt})
        
        # 添加用户内容和步骤历史
        messages.extend(context.get_conversation_history())
        
        return messages