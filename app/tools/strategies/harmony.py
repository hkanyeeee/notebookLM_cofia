"""Harmony DSL 策略实现"""
import json
import re
from typing import Dict, List, Any, Optional, AsyncGenerator
from .base import BaseStrategy
from ..models import ToolCall, ToolResult, Step, StepType, ToolExecutionContext
from ..registry import tool_registry
from ..parsers import HarmonyParser


class HarmonyStrategy(BaseStrategy):
    """Harmony DSL 工具标记策略"""
    
    def __init__(self, llm_service_url: str):
        super().__init__(llm_service_url)
    
    def build_system_prompt(self, context: ToolExecutionContext) -> str:
        """构建 Harmony DSL 系统提示"""
        base_prompt = (
            "你是一位高效智能的助手。请仔细分析用户问题，合理判断是否需要使用工具获取信息。"
            "优先使用你已有的知识回答问题，只有在确实需要最新信息或特定数据时才使用工具。"
            "使用工具时要精准高效：一次工具调用通常就足够了，不要进行重复或冗余的搜索。"
            "重要：工具执行完成后，请立即基于工具返回的结果给出完整的最终答案，不要再次调用相同或类似的工具。"
            "回答要简洁准确，不要使用'可能'、'大概'、'也许'等不确定词汇，"
            "也不要说'根据搜索结果'或'根据获取的信息'等提示性词语。"
            "\n\n**重要要求：必须完全使用中文进行回答。**\n\n"
        )
        
        # 检查是否是最后一次工具调用机会
        current_action_count = sum(1 for step in context.steps if step.step_type == StepType.ACTION)
        max_steps = context.run_config.get_max_steps()
        is_last_chance = current_action_count >= max_steps - 1
        
        if is_last_chance:
            base_prompt += f"\n\n**重要警告**：这是您最后一次工具调用机会（已使用{current_action_count}/{max_steps}步）！请谨慎选择最重要的工具，使用后必须立即基于结果给出完整的最终答案，不能再进行任何工具调用。\n\n"
        
        # 添加工具说明
        if tool_registry.has_tools():
            tools_desc = "可用工具：\n"
            allowed_tools = self.get_allowed_tools(context)
            for schema in tool_registry.get_all_schemas():
                if schema.name in allowed_tools:
                    tools_desc += f"- {schema.name}: {schema.description}\n"
            
            tools_desc += "\n工具使用原则：\n"
            tools_desc += "1. 只有在确实需要实时信息时才使用工具\n"
            tools_desc += "2. 一次精准的工具调用通常就足够了\n"
            tools_desc += "3. 工具调用后立即基于结果回答，不要再次搜索相同或相似信息\n"
            tools_desc += "4. 对于简单查询（如天气、新闻），一次搜索即可\n"
            tools_desc += "5. 禁止连续调用多个工具，执行一个工具后必须立即给出最终答案\n\n"
            tools_desc += "工具调用格式：\n"
            tools_desc += '<tool name="工具名称">{"参数名": "参数值"}</tool>\n\n'
            tools_desc += "重要注意事项：\n"
            tools_desc += "- 每个工具调用必须包含所有必需参数\n"
            tools_desc += "- web_search 工具必须包含 'query' 参数\n"
            tools_desc += "- 不要生成无效的参数如 'id', 'cursor' 等\n"
            tools_desc += "- 工具执行完成后，基于结果直接给出最终答案，不要再次调用工具\n\n"
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

    def _normalize_query(self, text: str) -> str:
        """对查询文本做基本归一化，避免无意义重复调用"""
        if not isinstance(text, str):
            return ""
        s = text.strip().lower()
        # 基本的空白和标点处理，不使用硬编码的同义词替换
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"[\u3000\s\t\r\n\-_,.;:!?，。；：！？""\"'`（）()\\\[\]{}]", "", s)
        return s

    def _fingerprint_web_search(self, arguments: Dict[str, Any]) -> str:
        """根据 web_search 的入参生成指纹。仅当参数本质相同才认为重复。
        参与指纹的字段：query、filter_list、model
        其中 query 做温和归一化；filter_list 排序并归一化大小写。
        """
        query = self._normalize_query(str(arguments.get("query", "")))
        model = str(arguments.get("model", "")).strip()
        filters = arguments.get("filter_list") or []
        if isinstance(filters, list):
            filters_norm = ",".join(sorted([str(x).strip().lower() for x in filters]))
        else:
            filters_norm = str(filters).strip().lower()
        return f"web_search|q={query}|filters={filters_norm}|model={model}"
    
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
            
            # 调试日志：解析结果
            print(f"[Harmony Strategy] 解析结果: 发现 {len(tool_calls)} 个工具调用")
            for i, tc in enumerate(tool_calls):
                print(f"[Harmony Strategy] 工具调用 {i+1}: {tc.name}, 参数: {tc.arguments}")
            
            # 如果有工具调用，先执行第一个工具
            if tool_calls:
                tool_call = tool_calls[0]  # 一次处理一个工具调用
                print(f"[Harmony Strategy] 准备执行工具: {tool_call.name}")
                
                # 对 web_search 做跨步骤去重：若上下文中已有等价调用且有结果，则复用
                if tool_call.name == "web_search":
                    new_fp = self._fingerprint_web_search(tool_call.arguments)
                    reused_result: Optional[ToolResult] = None
                    # 从后往前查找最近一次相同指纹的调用结果
                    for prev in reversed(context.steps):
                        if prev.tool_call and prev.tool_call.name == "web_search" and prev.tool_result:
                            try:
                                prev_fp = self._fingerprint_web_search(prev.tool_call.arguments or {})
                            except Exception:
                                continue
                            if prev_fp == new_fp:
                                reused_result = prev.tool_result
                                break
                    if reused_result is not None:
                        print("[Harmony Strategy] 去重：复用前次相同 web_search 结果")
                        return Step(
                            step_type=StepType.OBSERVATION,
                            content=f"工具执行结果：{reused_result.result}",
                            tool_call=tool_call,
                            tool_result=reused_result
                        )
                
                # 执行工具（包含所有验证）
                print(f"[Harmony Strategy] 开始执行工具: {tool_call.name}")
                
                # 如果是web_search，构建搜索历史并传递
                if tool_call.name == "web_search":
                    search_history = self._build_web_search_history(context)
                    if search_history:
                        tool_call.arguments["search_history"] = search_history
                        print(f"[Harmony Strategy] 传递搜索历史: {len(search_history)} 条记录")
                
                tool_result = await self.execute_tool_with_validation(tool_call, context)
                print(f"[Harmony Strategy] 工具执行完成: 成功={tool_result.success}")
                if not tool_result.success:
                    print(f"[Harmony Strategy] 工具执行错误: {tool_result.error}")
                
                return self.create_observation_step(tool_call, tool_result, format_content=False)
            
            # 没有工具调用，返回最终内容
            elif remaining_content:
                return Step(
                    step_type=StepType.FINAL_ANSWER,
                    content=remaining_content
                )
            
            return None
            
        except Exception as e:
            return self.create_error_step(f"LLM 调用出错: {str(e)}", error=e)
    
    async def stream_execute_step(self, context: ToolExecutionContext) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行单个步骤"""
        payload = self.build_payload(context)
        # 重要：开启流式返回，确保 LLM 以 SSE 形式输出增量结果
        # 否则将不会产生以 "data:" 开头的行，导免前端一直停留在"信息加载中"。
        payload["stream"] = True
        
        try:
            url = f"{self.llm_service_url}/chat/completions"
            
            async with await self.call_llm(payload, stream=True) as response:
                    response.raise_for_status()
                    
                    accumulated_content = ""
                    in_tool_block = False
                    in_channel_block = False
                    current_tool_content = ""
                    current_channel_content = ""
                    # 本轮流式内的去重缓存
                    executed_fingerprints = set()
                    fingerprint_to_result: Dict[str, ToolResult] = {}
                    # 标记是否已经有实质内容输出（非工具调用）
                    has_content_output = False
                    # 标记是否已经执行了工具
                    has_executed_tool = False
                    
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            # 检查是否应该发送最终答案
                            if has_content_output and accumulated_content.strip():
                                # 检查当前上下文中是否已有工具执行记录
                                context_has_tool_result = any(step.step_type == StepType.OBSERVATION and step.tool_result 
                                                            for step in context.steps)
                                
                                if context_has_tool_result and not has_executed_tool:
                                    # 这是基于已有工具结果的回答，是最终答案
                                    print("[Harmony Stream] 检测到基于工具结果的回答，这是最终答案")
                                    yield {
                                        "type": "final_answer",
                                        "content": accumulated_content.strip(),
                                        "message": "基于工具结果的最终回答"
                                    }
                                elif not context_has_tool_result and not has_executed_tool:
                                    # 未使用工具的直接回答
                                    print("[Harmony Stream] 流式结束，未使用工具，标记为最终答案")
                                    yield {
                                        "type": "final_answer", 
                                        "content": accumulated_content.strip(),
                                        "message": "未使用工具的直接回答"
                                    }
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
                            
                            # 检查是否在 Channel Commentary 块中（GPT OSS 格式）
                            if "<|channel|>" in delta_text and not in_channel_block:
                                in_channel_block = True
                                current_channel_content = delta_text
                                print(f"[Harmony Stream] 检测到 Channel Commentary 开始: {delta_text[:50]}...")
                            elif in_channel_block:
                                current_channel_content += delta_text
                                # 检查是否有完整的工具调用信息（包含 JSON 部分）
                                if "}" in current_channel_content:
                                    print(f"[Harmony Stream] Channel Commentary 内容: {current_channel_content}")
                                    # 尝试解析完整的工具调用
                                    tool_calls = HarmonyParser.parse_tool_calls(current_channel_content)
                                    if tool_calls:
                                        tool_call = tool_calls[0]
                                        print(f"[Harmony Stream] 解析出工具调用: {tool_call.name}, 参数: {tool_call.arguments}")
                                        
                                        yield {
                                            "type": "tool_call",
                                            "name": tool_call.name,
                                            "tool_name": tool_call.name,
                                            "args": tool_call.arguments
                                        }
                                        
                                        # 执行工具
                                        if tool_registry.is_allowed(tool_call.name):
                                            # 对 web_search 做单轮去重复用
                                            if tool_call.name == "web_search":
                                                fp = self._fingerprint_web_search(tool_call.arguments)
                                                if fp in executed_fingerprints:
                                                    print("[Harmony Stream] 去重：跳过重复 web_search，复用前次结果")
                                                    reused = fingerprint_to_result.get(fp)
                                                    if reused is not None:
                                                        yield {
                                                            "type": "tool_result",
                                                            "name": tool_call.name,
                                                            "tool_name": tool_call.name,
                                                            "result": str(reused.result),
                                                            "success": reused.success,
                                                            "latency_ms": reused.latency_ms,
                                                            "retries": reused.retries,
                                                        }
                                                        context.add_step(Step(
                                                            step_type=StepType.OBSERVATION,
                                                            content=f"工具执行结果：{reused.result}",
                                                            tool_result=reused
                                                        ))
                                                        in_channel_block = False
                                                        current_channel_content = ""
                                                        continue
                                            print(f"[Harmony Stream] 开始执行工具: {tool_call.name}")
                                            tool_result = await tool_registry.execute_tool(tool_call, context)
                                            print(f"[Harmony Stream] 工具执行完成: 成功={tool_result.success}")
                                            
                                            yield {
                                                "type": "tool_result",
                                                "name": tool_call.name,
                                                "tool_name": tool_call.name,
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
                                                content=f"工具执行结果：{tool_result.result}",
                                                tool_result=tool_result
                                            ))
                                            # 记录指纹结果，便于后续复用
                                            if tool_call.name == "web_search":
                                                fp = self._fingerprint_web_search(tool_call.arguments)
                                                executed_fingerprints.add(fp)
                                                fingerprint_to_result[fp] = tool_result
                                            
                                            # 标记已执行工具
                                            has_executed_tool = True
                                        else:
                                            yield {
                                                "type": "tool_result",
                                                "name": tool_call.name,
                                                "tool_name": tool_call.name,
                                                "result": f"工具 '{tool_call.name}' 不在允许列表中",
                                                "success": False
                                            }
                                    
                                    in_channel_block = False
                                    current_channel_content = ""
                            # 检查是否在标准工具块中
                            elif "<tool" in delta_text and not in_tool_block:
                                in_tool_block = True
                                current_tool_content = delta_text
                            elif in_tool_block:
                                current_tool_content += delta_text
                                if "</tool>" in delta_text:
                                    # 工具块结束，解析工具调用
                                    tool_calls = HarmonyParser.parse_tool_calls(current_tool_content)
                                    if tool_calls:
                                        tool_call = tool_calls[0]
                                        
                                        yield {
                                            "type": "tool_call",
                                            "name": tool_call.name,
                                            "tool_name": tool_call.name,
                                            "args": tool_call.arguments
                                        }
                                        
                                        # 执行工具
                                        if tool_registry.is_allowed(tool_call.name):
                                            # 对 web_search 做单轮去重复用
                                            if tool_call.name == "web_search":
                                                fp = self._fingerprint_web_search(tool_call.arguments)
                                                if fp in executed_fingerprints:
                                                    print("[Harmony Stream] 去重：跳过重复 web_search，复用前次结果")
                                                    reused = fingerprint_to_result.get(fp)
                                                    if reused is not None:
                                                        yield {
                                                            "type": "tool_result",
                                                            "name": tool_call.name,
                                                            "tool_name": tool_call.name,
                                                            "result": str(reused.result),
                                                            "success": reused.success,
                                                            "latency_ms": reused.latency_ms,
                                                            "retries": reused.retries,
                                                        }
                                                        context.add_step(Step(
                                                            step_type=StepType.OBSERVATION,
                                                            content=f"工具执行结果：{reused.result}",
                                                            tool_result=reused
                                                        ))
                                                        in_tool_block = False
                                                        current_tool_content = ""
                                                        continue
                                            tool_result = await tool_registry.execute_tool(tool_call, context)
                                            
                                            yield {
                                                "type": "tool_result",
                                                "name": tool_call.name,
                                                "tool_name": tool_call.name,
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
                                                content=f"工具执行结果：{tool_result.result}",
                                                tool_result=tool_result
                                            ))
                                            # 记录指纹结果，便于后续复用
                                            if tool_call.name == "web_search":
                                                fp = self._fingerprint_web_search(tool_call.arguments)
                                                executed_fingerprints.add(fp)
                                                fingerprint_to_result[fp] = tool_result
                                            
                                            # 标记已执行工具
                                            has_executed_tool = True
                                        else:
                                            yield {
                                                "type": "tool_result",
                                                "name": tool_call.name,
                                                "tool_name": tool_call.name,
                                                "result": f"工具 '{tool_call.name}' 不在允许列表中",
                                                "success": False
                                            }
                                    
                                    in_tool_block = False
                                    current_tool_content = ""
                            else:
                                # 普通内容（不在任何工具块中）
                                if not in_tool_block and not in_channel_block:
                                    if reasoning_content:
                                        yield {"type": "reasoning", "content": reasoning_content}
                                    elif content:
                                        # 标记已有内容输出
                                        has_content_output = True
                                        yield {"type": "content", "content": content}
                                        
                                        # 不在工具执行的同一轮中立即结束，让模型完成输出
                        
                        except Exception as e:
                            print(f"[Harmony Stream] 解析流式数据时出错: {e}")
                            continue
        
                    # 流式处理完成，根据情况决定后续处理
                    if has_executed_tool:
                        print("[Harmony Stream] 本轮工具执行完成，让 orchestrator 继续下一轮")
                        # 工具执行完成，添加步骤到上下文，让orchestrator继续
                    elif has_content_output and accumulated_content.strip():
                        # 未使用工具且有内容输出，这是直接回答
                        print("[Harmony Stream] 未使用工具，有内容输出，这是直接的最终答案")
                        yield {
                            "type": "final_answer",
                            "content": accumulated_content.strip(),
                            "message": "未使用工具的直接回答"
                        }
                    else:
                        print("[Harmony Stream] 本轮结束，无特殊处理")
        
        except Exception as e:
            print(f"[Harmony Stream] 流式执行出错: {e}")
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
        system_prompt += f"\n\n**重要提示**：您已达到最大工具调用步数限制({context.run_config.get_max_steps()}步)。请基于当前已收集的所有信息，直接提供完整的最终答案，不要再使用任何工具。如果信息不完整，请说明这一点，并基于现有信息给出最佳回答。"
        
        messages.append({"role": "system", "content": system_prompt})
        
        # 添加用户内容和步骤历史
        messages.extend(context.get_conversation_history())
        
        return messages