"""
智能编排器 - 实现"问题拆解-思考-工具调用"流程
"""
import json
from typing import List, Dict, Any, Optional, AsyncGenerator
from .models import ToolExecutionContext, RunConfig, ToolMode
from .query_decomposer import QueryDecomposer
from .reasoning_engine import ReasoningEngine
from .orchestrator import ToolOrchestrator
from .selector import StrategySelector
from .search_planner import SearchPlanner
from .formatters import OutputFormatter
from ..config import LLM_SERVICE_URL
from .prompts import SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_USER_PROMPT_TEMPLATE
import httpx


class IntelligentOrchestrator:
    """
    智能编排器：实现"问题拆解-思考-工具调用"的完整流程
    """
    
    def __init__(self, llm_service_url: str = LLM_SERVICE_URL):
        self.llm_service_url = llm_service_url
        self.decomposer = QueryDecomposer(llm_service_url)
        self.reasoning_engine = ReasoningEngine(llm_service_url)
        self.tool_orchestrator = ToolOrchestrator(llm_service_url)
        self.search_planner = SearchPlanner()

    async def process_query_intelligently(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        智能处理用户查询：问题拆解-思考-工具调用 (非流式版本)
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
        
        Returns:
            处理结果
        """
        # 调用统一的核心处理方法
        result = {"answer": "", "decomposition": {}, "reasoning": [], "tool_results": {}, "used_tools": False, "success": True}
        
        async def collect_result(event_data):
            """收集非流式结果的回调函数"""
            if event_data.get("type") == "final_result":
                result.update(event_data.get("data", {}))
        
        # 使用核心处理方法，传入结果收集回调
        await self._process_query_core(query, contexts, run_config, conversation_history, collect_result)
        return result

    async def process_query_intelligently_stream(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式智能处理用户查询 (流式版本)
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
        
        Yields:
            流式处理事件
        """
        # 创建一个真正的流式回调函数，实时yield事件
        async def stream_event(event_data):
            """实时流式输出回调函数"""
            # 过滤掉final_result事件，因为流式处理不需要最终结果事件
            if event_data.get("type") != "final_result":
                yield event_data
        
        # 使用流式核心处理方法，实时yield事件
        async for event in self._process_query_core_stream(query, contexts, run_config, conversation_history):
            yield event

    async def _process_query_core(
        self,
        query: str,
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        event_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        统一的核心处理逻辑，同时支持流式和非流式调用
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
            event_callback: 事件回调函数，用于流式输出或收集结果
        
        Yields:
            处理事件（仅流式调用时）
        """
        execution_context = ToolExecutionContext(
            question=query,
            contexts=contexts,
            run_config=run_config,
            conversation_history=conversation_history
        )
        
        try:
            # 优化：如果工具已关闭，直接跳过LLM路由判断，走普通问答流程
            if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                if event_callback:
                    await event_callback({
                        "type": "reasoning",
                        "content": "工具已关闭，直接进行基于已有知识的问答..."
                    })
                # 直接进行基于上下文的问答
                result = await self._handle_context_only_query_unified(
                    query, contexts, run_config, conversation_history, event_callback
                )
                if event_callback:
                    await event_callback({"type": "final_result", "data": result})
                return result
            
            # 智能路由：检查问题的处理方式（由LLM判定）
            route_decision = await self.decomposer.should_use_fast_route_async(query, execution_context, conversation_history)
            use_fast_route = route_decision.get("use_fast_route", False)
            needs_tools = route_decision.get("needs_tools", True)
            reason = route_decision.get("reason", "")
            
            if use_fast_route:
                if needs_tools:
                    # 工具关闭：走完整分析链路，识别知识缺口并生成“不可搜索”提示下的最佳答案
                    if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                        if event_callback:
                            await event_callback({
                                "type": "reasoning",
                                "content": "工具已关闭，将进行完整分析并列出知识缺口，随后基于已有知识生成答案。"
                            })
                        # 执行完整的拆解与思考
                        decomposition = await self.decomposer.decompose(query, execution_context, conversation_history)
                        thoughts = await self.reasoning_engine.think_about_decomposition(
                            decomposition, contexts, execution_context, conversation_history
                        )
                        # 提取知识缺口
                        _, knowledge_gaps = self._should_invoke_tools(thoughts)
                        # 生成不使用搜索的最终答案（在答案中显式反映知识缺口）
                        final_answer = await self._synthesize_gap_aware_answer_without_tools(
                            query, knowledge_gaps, contexts, run_config, conversation_history
                        )
                        result = {
                            "answer": final_answer,
                            "decomposition": decomposition,
                            "reasoning": thoughts,
                            "tool_results": {},
                            "used_tools": False,
                            "success": True,
                            "knowledge_gaps": knowledge_gaps,
                            "fast_route": True
                        }
                        if event_callback:
                            await event_callback({"type": "final_result", "data": result})
                        return result
                    if event_callback:
                        await event_callback({
                            "type": "reasoning",
                            "content": f"分类为简单查询，需要外部工具，直接获取信息... ({reason})"
                        })
                    
                    result = await self._handle_simple_query_unified(query, contexts, run_config, conversation_history, event_callback)
                    
                    if event_callback:
                        await event_callback({"type": "final_result", "data": result})
                    return result
                else:
                    if event_callback:
                        await event_callback({
                            "type": "reasoning",
                            "content": f"分类为简单问题，基于已有知识回答... ({reason})"
                        })
                    
                    result = await self._handle_context_only_query_unified(query, contexts, run_config, conversation_history, event_callback)
                    
                    if event_callback:
                        await event_callback({"type": "final_result", "data": result})
                    return result
            
            # 第一步：问题拆解
            if event_callback:
                await event_callback({
                    "type": "reasoning",
                    "content": "正在分析和拆解您的问题..."
                })
            else:
                print("[IntelligentOrchestrator] 开始问题拆解...")
            
            decomposition = await self.decomposer.decompose(query, execution_context, conversation_history)
            
            # 显示子问题的具体内容（仅流式时）
            if event_callback:
                sub_queries = decomposition.get('sub_queries', [])
                sub_queries_count = len(sub_queries)
                
                await event_callback({
                    "type": "reasoning",
                    "content": f"问题拆解完成，识别到{sub_queries_count}个关键子问题。"
                })
                
                # 逐一显示每个子问题
                for i, sub_query in enumerate(sub_queries, 1):
                    if isinstance(sub_query, dict):
                        question = sub_query.get("question", "")
                        importance = sub_query.get("importance", "中")
                    else:
                        question = str(sub_query)
                        importance = "中"
                    
                    if question:
                        await event_callback({
                            "type": "reasoning",
                            "content": f"子问题{i}（{importance}重要性）：{question}"
                        })
            
            # 第二步：独立思考
            if event_callback:
                await event_callback({
                    "type": "reasoning", 
                    "content": "💡基于已有知识进行独立思考..."
                })
            else:
                print("[IntelligentOrchestrator] 开始独立思考...")
            
            thoughts = await self.reasoning_engine.think_about_decomposition(
                decomposition, contexts, execution_context, conversation_history
            )
            
            if event_callback:
                overall_confidence = self.reasoning_engine.assess_overall_confidence(thoughts)
                await event_callback({
                    "type": "reasoning",
                    "content": f"思考完成，整体置信度: {overall_confidence}。"
                })
            
            # 第三步：决定是否需要工具调用
            need_tools, knowledge_gaps = self._should_invoke_tools(thoughts)
            
            tool_results = {}
            if need_tools:
                # 工具关闭：不执行搜索，转入“知识缺口感知”的答案综合
                if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                    if event_callback:
                        await event_callback({
                            "type": "reasoning",
                            "content": "工具已关闭，无法进行搜索，将基于已有知识生成答案并列出知识缺口。"
                        })
                    final_answer = await self._synthesize_gap_aware_answer_without_tools(
                        query, knowledge_gaps, contexts, run_config, conversation_history
                    )
                    result = {
                        "answer": final_answer,
                        "decomposition": decomposition,
                        "reasoning": thoughts,
                        "tool_results": {},
                        "used_tools": False,
                        "success": True,
                        "knowledge_gaps": knowledge_gaps
                    }
                    if event_callback:
                        await event_callback({"type": "final_result", "data": result})
                    return result
                else:
                    if event_callback:
                        await event_callback({
                            "type": "reasoning",
                            "content": f"检测到{len(knowledge_gaps)}个知识缺口，开始搜索外部信息..."
                        })
                    else:
                        print("[IntelligentOrchestrator] 检测到知识缺口，开始工具调用...")
                    
                    tool_results = await self._execute_tools_for_gaps_unified(
                        knowledge_gaps, query, contexts, run_config, event_callback
                    )
            else:
                if event_callback:
                    await event_callback({
                        "type": "reasoning",
                        "content": "基于现有知识可以回答，无需外部搜索"
                    })
                else:
                    print("[IntelligentOrchestrator] 无需工具调用，基于思考结果生成答案...")
            
            # 第四步：综合所有信息生成最终答案
            if event_callback:
                await event_callback({
                    "type": "reasoning",
                    "content": "正在综合所有信息生成完整答案..."
                })
            
            final_answer = await self._synthesize_final_answer_unified(
                query, decomposition, thoughts, tool_results, contexts, run_config, conversation_history, event_callback
            )
            
            result = {
                "answer": final_answer,
                "decomposition": decomposition,
                "reasoning": thoughts,
                "tool_results": tool_results,
                "used_tools": need_tools,
                "success": True
            }
            
            if event_callback:
                await event_callback({"type": "final_result", "data": result})
            
            return result
            
        except Exception as e:
            error_msg = f"智能处理失败: {str(e)}"
            if event_callback:
                await event_callback({
                    "type": "error",
                    "message": error_msg
                })
            else:
                print(f"[IntelligentOrchestrator] {error_msg}")
            
            error_result = {
                "answer": f"处理问题时遇到错误: {str(e)}",
                "success": False
            }
            
            if event_callback:
                await event_callback({"type": "final_result", "data": error_result})
            
            return error_result

    async def _process_query_core_stream(
        self,
        query: str,
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式核心处理逻辑，实时yield事件
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
        
        Yields:
            流式处理事件
        """
        execution_context = ToolExecutionContext(
            question=query,
            contexts=contexts,
            run_config=run_config,
            conversation_history=conversation_history
        )
        
        try:
            # 优化：如果工具已关闭，直接跳过LLM路由判断，走普通问答流程
            if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                yield {
                    "type": "reasoning",
                    "content": "工具已关闭，直接进行基于已有知识的问答..."
                }
                # 直接进行基于上下文的流式问答
                context_str = "\n".join(contexts) if contexts else "无特定上下文"
                
                system_prompt = (
                    "你是一个知识渊博的助手。请仔细阅读对话历史，理解用户问题的完整语境，然后基于你的已有知识和提供的上下文来回答用户的问题。\n"
                    "重要指导原则：\n"
                    "1. 充分理解对话历史：如果用户的问题是对之前对话的延续或追问，请结合历史对话来理解当前问题的真实意图。\n"
                    "2. 不要提及需要搜索或查找外部信息，直接给出清晰、准确的答案。\n"
                    "**重要要求：必须完全使用中文进行回答。**"
                )
                
                user_prompt = (
                    f"上下文信息：\n{context_str}\n\n"
                    f"用户问题：{query}\n\n"
                    "请直接回答用户的问题。"
                )
                
                # 使用流式LLM调用
                from ..llm_client import chat_complete_stream
                async for event in chat_complete_stream(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=run_config.model,
                    conversation_history=conversation_history
                ):
                    yield event
                return
            
            # 智能路由：检查问题的处理方式（由LLM判定）
            route_decision = await self.decomposer.should_use_fast_route_async(query, execution_context, conversation_history)
            use_fast_route = route_decision.get("use_fast_route", False)
            needs_tools = route_decision.get("needs_tools", True)
            reason = route_decision.get("reason", "")
            
            if use_fast_route:
                if needs_tools:
                    # 工具关闭：走完整分析链路（流式），识别知识缺口并在答案中体现
                    if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                        yield {
                            "type": "reasoning",
                            "content": "工具已关闭，将进行完整分析并列出知识缺口，随后基于已有知识生成答案。"
                        }
                        # 流式执行拆解与思考
                        decomposition = await self.decomposer.decompose(query, execution_context, conversation_history)
                        sub_queries = decomposition.get('sub_queries', [])
                        if sub_queries:
                            yield {
                                "type": "reasoning",
                                "content": f"问题拆解完成，识别到{len(sub_queries)}个关键子问题。"
                            }
                        thoughts = await self.reasoning_engine.think_about_decomposition(
                            decomposition, contexts, execution_context, conversation_history
                        )
                        # 提取知识缺口并展示
                        _, knowledge_gaps = self._should_invoke_tools(thoughts)
                        if knowledge_gaps:
                            try:
                                gaps_brief = []
                                for i, gap in enumerate(knowledge_gaps, 1):
                                    desc = gap.get("gap_description") or gap.get("question") or str(gap)
                                    gaps_brief.append(f"{i}. {desc}")
                                yield {
                                    "type": "reasoning",
                                    "content": "已识别的知识缺口：\n" + "\n".join(gaps_brief)
                                }
                            except Exception:
                                pass
                        # 基于知识缺口进行无搜索综合（流式）
                        context_str = "\n".join(contexts) if contexts else "无特定上下文"
                        system_prompt = (
                            "你是一个知识渊博的助手。当前外部搜索工具不可用，请不要提出需要搜索的建议。\n"
                            "请充分利用已有知识和提供的上下文，尽力回答用户问题；\n"
                            "若信息不足，请明确列出待确认点与可能路径，但不要杜撰。\n"
                            "必须全程使用中文回答。"
                        )
                        gaps_text = "\n".join([
                            (gap.get("gap_description") or gap.get("question") or str(gap)) for gap in (knowledge_gaps or [])
                        ])
                        user_prompt = (
                            f"上下文：\n{context_str}\n\n"
                            f"用户问题：{query}\n\n"
                            f"已识别的知识缺口：\n{gaps_text if gaps_text else '无'}\n\n"
                            "请在不进行外部搜索的前提下给出尽力而为的答案，\n并明确指出哪些关键信息缺失、需要进一步确认。"
                        )
                        from ..llm_client import chat_complete_stream
                        async for event in chat_complete_stream(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=run_config.model,
                            conversation_history=conversation_history
                        ):
                            yield event
                        return
                    yield {
                        "type": "reasoning",
                        "content": f"分类为简单查询，需要外部工具，直接获取信息... ({reason})"
                    }
                    
                    # 使用工具编排器直接进行流式处理
                    from ..tools.orchestrator import get_orchestrator
                    orchestrator = get_orchestrator()
                    if orchestrator:
                        async for event in orchestrator.execute_stream(query, contexts, run_config, conversation_history):
                            yield event
                    else:
                        # 回退到普通流式问答
                        from ..llm_client import stream_answer
                        async for event in stream_answer(query, contexts, run_config.model, conversation_history):
                            yield event
                    return
                else:
                    yield {
                        "type": "reasoning",
                        "content": f"分类为简单问题，基于已有知识回答... ({reason})"
                    }
                    
                    # 直接进行流式基于上下文的问答
                    context_str = "\n".join(contexts) if contexts else "无特定上下文"
                    
                    system_prompt = (
                        "你是一个知识渊博的助手。请仔细阅读对话历史，理解用户问题的完整语境，然后基于你的已有知识和提供的上下文来回答用户的问题。\n"
                        "重要指导原则：\n"
                        "1. 充分理解对话历史：如果用户的问题是对之前对话的延续或追问，请结合历史对话来理解当前问题的真实意图。\n"
                        "2. 不要提及需要搜索或查找外部信息，直接给出清晰、准确的答案。\n"
                        "**重要要求：必须完全使用中文进行回答。**"
                    )
                    
                    user_prompt = (
                        f"上下文信息：\n{context_str}\n\n"
                        f"用户问题：{query}\n\n"
                        "请直接回答用户的问题。"
                    )
                    
                    # 使用流式LLM调用
                    from ..llm_client import chat_complete_stream
                    async for event in chat_complete_stream(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=run_config.model,
                        conversation_history=conversation_history
                    ):
                        yield event
                    return
            
            # 第一步：问题拆解
            yield {
                "type": "reasoning",
                "content": "正在分析和拆解您的问题..."
            }
            
            decomposition = await self.decomposer.decompose(query, execution_context, conversation_history)
            
            # 显示子问题的具体内容
            sub_queries = decomposition.get('sub_queries', [])
            sub_queries_count = len(sub_queries)
            
            yield {
                "type": "reasoning",
                "content": f"问题拆解完成，识别到{sub_queries_count}个关键子问题。"
            }
            
            # 逐一显示每个子问题
            for i, sub_query in enumerate(sub_queries, 1):
                if isinstance(sub_query, dict):
                    question = sub_query.get("question", "")
                    importance = sub_query.get("importance", "中")
                else:
                    question = str(sub_query)
                    importance = "中"
                
                if question:
                    yield {
                        "type": "reasoning",
                        "content": f"子问题{i}（{importance}重要性）：{question}"
                    }
            
            # 第二步：独立思考
            yield {
                "type": "reasoning", 
                "content": "💡基于已有知识进行独立思考..."
            }
            
            thoughts = await self.reasoning_engine.think_about_decomposition(
                decomposition, contexts, execution_context, conversation_history
            )
            
            overall_confidence = self.reasoning_engine.assess_overall_confidence(thoughts)
            yield {
                "type": "reasoning",
                "content": f"思考完成，整体置信度: {overall_confidence}。"
            }
            
            # 第三步：决定是否需要工具调用
            need_tools, knowledge_gaps = self._should_invoke_tools(thoughts)
            
            tool_results = {}
            if need_tools:
                # 工具关闭：不执行搜索，改为无搜索综合（流式）
                if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                    yield {
                        "type": "reasoning",
                        "content": "工具已关闭，无法进行搜索，将基于已有知识生成答案并列出知识缺口。"
                    }
                    # 列出知识缺口
                    if knowledge_gaps:
                        try:
                            gaps_brief = []
                            for i, gap in enumerate(knowledge_gaps, 1):
                                desc = gap.get("gap_description") or gap.get("question") or str(gap)
                                gaps_brief.append(f"{i}. {desc}")
                            yield {
                                "type": "reasoning",
                                "content": "已识别的知识缺口：\n" + "\n".join(gaps_brief)
                            }
                        except Exception:
                            pass
                    # 基于知识缺口进行无搜索综合（流式）
                    context_str = "\n".join(contexts) if contexts else "无特定上下文"
                    user_prompt = SYNTHESIS_USER_PROMPT_TEMPLATE.format(
                        original_query=query,
                        reasoning_summary=OutputFormatter.format_reasoning_summary(thoughts),
                        tool_results="未进行外部搜索。",
                        context=context_str
                    ) + "\n\n注意：外部搜索工具不可用。请：\n- 基于已有信息尽力回答\n- 明确列出关键缺失信息与建议的下一步（但不要杜撰）"
                    from ..llm_client import chat_complete_stream
                    async for event in chat_complete_stream(
                        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        model=run_config.model,
                        conversation_history=conversation_history
                    ):
                        yield event
                    return
                else:
                    yield {
                        "type": "reasoning",
                        "content": f"检测到{len(knowledge_gaps)}个知识缺口，开始搜索外部信息..."
                    }
                    
                    # 流式执行工具调用，使用统一的工具执行方法
                    tool_results = await self._execute_tools_for_gaps_unified(
                        knowledge_gaps, query, contexts, run_config, None
                    )
                    
                    # 手动发送工具调用事件（因为统一方法可能不发送流式事件）
                    if tool_results.get("success", False):
                        yield {
                            "type": "tool_result",
                            "name": "web_search_and_recall",
                            "result": "搜索和召回完成",
                            "success": True
                        }
            else:
                yield {
                    "type": "reasoning",
                    "content": "基于现有知识可以回答，无需外部搜索"
                }
            
            # 第四步：流式综合最终答案
            yield {
                "type": "reasoning",
                "content": "正在综合所有信息生成完整答案..."
            }
            
            # 直接进行流式答案综合，不使用统一方法的回调机制
            
            # 准备综合信息
            reasoning_summary = OutputFormatter.format_reasoning_summary(thoughts)
            tool_summary = OutputFormatter.format_tool_results(tool_results)
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            user_prompt = SYNTHESIS_USER_PROMPT_TEMPLATE.format(
                original_query=query,
                reasoning_summary=reasoning_summary,
                tool_results=tool_summary,
                context=context_str
            )
            
            # 直接使用流式LLM调用
            from ..llm_client import chat_complete_stream
            async for event in chat_complete_stream(
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=run_config.model,
                conversation_history=conversation_history
            ):
                yield event
                
        except Exception as e:
            yield {
                "type": "error",
                "message": f"智能处理失败: {str(e)}"
            }

    async def _run_web_search_and_recall(
        self,
        knowledge_gaps: List[Dict[str, Any]],
        original_query: str,
        run_config: RunConfig,
        is_simple_query: bool = False
    ) -> Dict[str, Any]:
        """
        统一的web搜索和召回实现（流式/非流式共用）
        
        Args:
            knowledge_gaps: 知识缺口列表
            original_query: 原始查询
            run_config: 运行配置
            is_simple_query: 是否为简单查询模式，用于应用不同的搜索配置
            
        Returns:
            包含knowledge_gaps_search_results和统计信息的结果字典
        """
        # 不再在此处短路；由上层决定是否调用该方法
        
        if not knowledge_gaps:
            return {"knowledge_gaps_search_results": {}, "success": False, "message": "没有知识缺口需要搜索"}
        
        try:
            # 1. 使用搜索规划器生成统一的查询列表，根据查询类型使用不同配置
            final_queries = self.search_planner.plan_search_queries(
                original_query, knowledge_gaps, is_simple_query=is_simple_query
            )
            
            from ..config import GAP_RECALL_TOP_K
            from ..tools.web_search_tool import web_search_tool
            import uuid
            
            # 生成统一的会话ID
            unified_session_id = str(uuid.uuid4())
            print(f"[IntelligentOrchestrator] 使用统一会话ID: {unified_session_id}")
            
            # 2. 一次性执行web搜索（避免重复抓取）
            print(f"[IntelligentOrchestrator] 开始一次性web搜索，查询: {final_queries}")
            search_result = await web_search_tool.execute(
                query=original_query,
                filter_list=None,
                model=run_config.model,
                predefined_queries=final_queries,
                session_id=unified_session_id,
                perform_retrieval=False,
                is_simple_query=is_simple_query
            )
            
            if not search_result.get("success") or not search_result.get("source_ids"):
                return {
                    "knowledge_gaps_search_results": {},
                    "success": False,
                    "message": "搜索失败或没有找到有效数据源",
                    "search_result": search_result
                }
            
            source_ids = search_result.get("source_ids", [])
            print(f"[IntelligentOrchestrator] 搜索完成，获得{len(source_ids)}个数据源")
            
            # 3. 为每个知识缺口进行独立召回
            selected_gaps = knowledge_gaps
            knowledge_gaps_search_results = {}
            
            import asyncio
            recall_tasks = []
            
            for gap_idx, gap in enumerate(selected_gaps):
                gap_id = f"gap_{gap_idx}"
                gap_description = gap.get("gap_description", f"知识缺口{gap_idx + 1}")
                
                # 使用知识缺口描述进行召回
                recall_task = self._recall_for_knowledge_gap(
                    gap_description, source_ids, unified_session_id, GAP_RECALL_TOP_K
                )
                recall_tasks.append((gap_id, gap, recall_task))
            
            # 并发执行所有召回任务
            for gap_id, gap, task in recall_tasks:
                try:
                    recalled_content = await task
                    knowledge_gaps_search_results[gap_id] = {
                        "gap": gap,
                        "recalled_content": recalled_content
                    }
                    print(f"[IntelligentOrchestrator] 知识缺口'{gap_id}'召回完成，获得{len(recalled_content)}个内容片段")
                except Exception as e:
                    print(f"[IntelligentOrchestrator] 知识缺口'{gap_id}'召回失败: {e}")
                    knowledge_gaps_search_results[gap_id] = {
                        "gap": gap,
                        "recalled_content": []
                    }
            
            # 4. 统计信息
            total_recalled = sum(len(result["recalled_content"]) for result in knowledge_gaps_search_results.values())
            
            return {
                "knowledge_gaps_search_results": knowledge_gaps_search_results,
                "success": True,
                "message": f"搜索和召回完成：处理了{len(final_queries)}个查询，为{len(selected_gaps)}个知识缺口召回了{total_recalled}个内容片段",
                "session_id": unified_session_id,
                "search_queries": final_queries,
                "source_ids": source_ids,
                "selected_gaps": selected_gaps,
                "statistics": {
                    "query_count": len(final_queries),
                    "gap_count": len(selected_gaps),
                    "source_count": len(source_ids),
                    "total_recalled": total_recalled
                }
            }
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 统一搜索和召回失败: {e}")
            return {
                "knowledge_gaps_search_results": {},
                "success": False,
                "message": f"搜索和召回过程中发生错误: {str(e)}",
                "error": str(e)
            }

    def _should_invoke_tools(self, thoughts: List[Dict[str, Any]]) -> tuple[bool, List[Dict[str, Any]]]:
        """
        基于思考结果决定是否需要调用工具
        
        Args:
            thoughts: 思考结果列表
        
        Returns:
            (是否需要工具调用, 知识缺口列表)
        """
        all_gaps = self.reasoning_engine.extract_all_knowledge_gaps(thoughts)
        
        # 如果有高重要性的知识缺口，或者整体置信度低，则需要工具调用
        high_importance_gaps = [gap for gap in all_gaps if gap.get("importance") == "高"]
        overall_confidence = self.reasoning_engine.assess_overall_confidence(thoughts)
        
        # 决策逻辑
        need_tools = (
            len(high_importance_gaps) > 0 or  # 有高重要性缺口
            overall_confidence == "低" or     # 整体置信度低
            any(thought.get("needs_verification", False) for thought in thoughts)  # 需要验证
        )
        
        return need_tools, all_gaps

    async def _execute_tools_for_gaps_unified(
        self, 
        knowledge_gaps: List[Dict[str, Any]], 
        original_query: str,
        contexts: List[str],
        run_config: RunConfig,
        event_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        统一的工具执行方法，同时支持流式和非流式调用
        
        Args:
            knowledge_gaps: 知识缺口列表
            original_query: 原始查询
            contexts: 上下文列表
            run_config: 运行配置
            event_callback: 事件回调函数，用于流式输出
        
        Returns:
            工具执行结果
        """
        if not knowledge_gaps:
            empty_result = {}
            if event_callback:
                await event_callback({"type": "final_tool_result", "result": empty_result})
            return empty_result
        
        try:
            # 发出搜索开始事件（仅流式时）
            if event_callback:
                await event_callback({
                    "type": "tool_call",
                    "name": "web_search_and_recall",
                    "args": {
                        "query": original_query,
                        "gap_count": len(knowledge_gaps)
                    }
                })
            
            # 使用统一的搜索和召回实现
            result = await self._run_web_search_and_recall(knowledge_gaps, original_query, run_config)
            
            # 发出搜索结果事件（仅流式时）
            if event_callback:
                await event_callback({
                    "type": "tool_result",
                    "name": "web_search_and_recall", 
                    "result": result.get("message", "搜索和召回完成"),
                    "success": result.get("success", False)
                })
            
            if not result.get("success"):
                error_result = {
                    "answer": result.get("message", "搜索和召回失败"),
                    "success": False,
                    "steps": [],
                    "error": result.get("error")
                }
                
                if event_callback:
                    await event_callback({"type": "final_tool_result", "result": error_result})
                
                return error_result
            
            # 格式化为最终答案
            knowledge_gaps_search_results = result.get("knowledge_gaps_search_results", {})
            selected_gaps = result.get("selected_gaps", [])
            statistics = result.get("statistics", {})
            
            final_result = {
                "answer": OutputFormatter.format_gap_based_answer(knowledge_gaps_search_results, selected_gaps),
                "success": True,
                "steps": [
                    {
                        "type": "action",
                        "content": f"统一执行{statistics.get('query_count', 0)}个搜索查询",
                        "tool": "web_search_unified"
                    },
                    {
                        "type": "observation", 
                        "content": result.get("message", "搜索和召回完成")
                    }
                ],
                "tool_calls": statistics.get("query_count", 0) + statistics.get("gap_count", 0),
                "session_id": result.get("session_id"),
                "knowledge_gaps_search_results": knowledge_gaps_search_results,
                "search_queries": result.get("search_queries", [])
            }
            
            if event_callback:
                await event_callback({"type": "final_tool_result", "result": final_result})
            
            return final_result
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 统一工具执行失败: {e}")
            # 回退到原有的工具编排器
            if event_callback:
                # 从 run_config 中获取 is_simple_query 信息
                is_simple_query = getattr(run_config, 'is_simple_query', False)
                final_queries = self.search_planner.plan_search_queries(original_query, knowledge_gaps, is_simple_query=is_simple_query)
                enhanced_query = f"{original_query} {' '.join(final_queries[:2])}"
                
                async for event in self.tool_orchestrator.execute_stream(
                    enhanced_query, contexts, run_config
                ):
                    await event_callback(event)
            
            error_result = {
                "answer": f"工具执行失败: {str(e)}",
                "success": False,
                "error": str(e)
            }
            return error_result

    async def _recall_for_knowledge_gap(
        self, 
        gap_description: str, 
        source_ids: List[int], 
        session_id: str, 
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        为特定知识缺口召回相关内容
        
        Args:
            gap_description: 知识缺口描述
            source_ids: 可用的数据源ID列表
            session_id: 会话ID
            top_k: 召回的内容数量
        
        Returns:
            召回的内容列表
        """
        try:
            from ..tools.web_search_tool import web_search_tool
            
            # 使用web_search_tool的search_and_retrieve方法
            hits = await web_search_tool.search_and_retrieve(
                query=gap_description,
                session_id=session_id,
                source_ids=source_ids
            )
            
            # 限制返回结果数量并格式化
            limited_hits = hits[:top_k]
            recalled_content = []
            
            for chunk, score in limited_hits:
                recalled_content.append({
                    "content": chunk.content,
                    "score": float(score),
                    "source_url": chunk.source.url if chunk.source else "",
                    "source_title": chunk.source.title if chunk.source else "",
                    "chunk_id": chunk.chunk_id
                })
            
            return recalled_content
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 知识缺口召回失败: {e}")
            return []

    async def _synthesize_final_answer_unified(
        self, 
        original_query: str,
        decomposition: Dict[str, Any],
        thoughts: List[Dict[str, Any]],
        tool_results: Dict[str, Any],
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        event_callback: Optional[callable] = None
    ) -> str:
        """
        统一的答案综合方法，同时支持流式和非流式调用
        
        Args:
            original_query: 原始查询
            decomposition: 问题拆解结果
            thoughts: 思考结果
            tool_results: 工具调用结果
            contexts: 上下文列表
            run_config: 运行配置
            conversation_history: 对话历史
            event_callback: 事件回调函数，用于流式输出
            
        Returns:
            最终答案字符串
        """
        try:
            # 准备综合信息
            reasoning_summary = OutputFormatter.format_reasoning_summary(thoughts)
            tool_summary = OutputFormatter.format_tool_results(tool_results)
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            user_prompt = SYNTHESIS_USER_PROMPT_TEMPLATE.format(
                original_query=original_query,
                reasoning_summary=reasoning_summary,
                tool_results=tool_summary,
                context=context_str
            )
            
            # 根据是否有回调来决定使用流式还是非流式调用
            if event_callback:
                # 流式调用
                from ..llm_client import chat_complete_stream
                full_answer = ""
                async for event in chat_complete_stream(
                    system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    model=run_config.model,
                    conversation_history=conversation_history
                ):
                    await event_callback(event)
                    # 收集完整答案用于返回
                    if event.get("type") == "content":
                        full_answer += event.get("content", "")
                return full_answer
            else:
                # 非流式调用
                from ..llm_client import chat_complete
                return await chat_complete(
                    system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    model=run_config.model,
                    conversation_history=conversation_history
                )
                
        except Exception as e:
            error_msg = f"答案综合失败: {str(e)}"
            fallback_answer = self.reasoning_engine.generate_preliminary_answer(thoughts)
            
            if event_callback:
                await event_callback({
                    "type": "error", 
                    "message": error_msg
                })
                # 尝试流式输出回退答案
                await event_callback({
                    "type": "content",
                    "content": fallback_answer
                })
            else:
                print(error_msg)
            
            return fallback_answer

    async def _synthesize_gap_aware_answer_without_tools(
        self,
        original_query: str,
        knowledge_gaps: List[Dict[str, Any]],
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        在工具关闭时使用：基于已有知识和上下文，显式呈现知识缺口并给出尽力而为的答案。
        """
        try:
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            gaps_text = "\n".join([
                (gap.get("gap_description") or gap.get("question") or str(gap)) for gap in (knowledge_gaps or [])
            ])
            system_prompt = (
                "你是一个严谨的助手。当前外部搜索工具不可用，请不要提出需要搜索的建议。\n"
                "请充分利用已有知识和提供的上下文，尽力回答用户问题；\n"
                "若信息不足，请明确列出待确认点与可能路径，但不要杜撰。\n"
                "必须全程使用中文回答。"
            )
            user_prompt = (
                f"上下文：\n{context_str}\n\n"
                f"用户问题：{original_query}\n\n"
                f"已识别的知识缺口：\n{gaps_text if gaps_text else '无'}\n\n"
                "请在不进行外部搜索的前提下给出尽力而为的答案，并\n"
                "- 明确指出哪些关键信息缺失、需要进一步确认；\n"
                "- 给出可行的下一步建议（例如需要哪些信息或数据）"
            )
            from ..llm_client import chat_complete
            return await chat_complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=run_config.model,
                conversation_history=conversation_history
            )
        except Exception as e:
            return f"外部搜索不可用。基于现有信息，我的回答可能不完整。原因：{str(e)}"

    async def _handle_simple_query_unified(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        event_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        统一的简单问题处理方法，同时支持流式和非流式调用
        
        Args:
            query: 简单问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
            event_callback: 事件回调函数，用于流式输出
            
        Returns:
            处理结果
        """
        try:
            # 保护：若工具关闭或不应使用工具，则直接走基于上下文回答
            if run_config.tool_mode == ToolMode.OFF or not StrategySelector.should_use_tools(run_config, run_config.model):
                if event_callback:
                    await event_callback({
                        "type": "reasoning",
                        "content": "工具已关闭，直接基于已有知识回答。"
                    })
                return await self._handle_context_only_query_unified(
                    query, contexts, run_config, conversation_history, event_callback
                )
            if event_callback:
                # 流式处理
                events_queue = []
                
                async def collect_tool_events(event_data):
                    """收集工具事件"""
                    events_queue.append(event_data)
                    await event_callback(event_data)
                
                # 使用工具编排器流式处理
                result = {}
                async for event in self.tool_orchestrator.execute_stream(
                    query, contexts, run_config, conversation_history
                ):
                    await collect_tool_events(event)
                    # 收集最终结果
                    if event.get("type") == "final_result":
                        result = event.get("data", {})
                        

                
                return {
                    "answer": result.get("answer", "无法获取信息"),
                    "decomposition": {
                        "original_query": query,
                        "complexity_level": "简单",
                        "sub_queries": [{"question": query}]
                    },
                    "reasoning": [{"question": query, "confidence_level": "高"}],
                    "tool_results": result,
                    "used_tools": True,
                    "success": result.get("success", False),
                    "fast_route": True  # 标记使用了快速路由
                }
            else:
                # 非流式处理
                result = await self.tool_orchestrator.execute_non_stream(
                    query, contexts, run_config, conversation_history
                )
                

                
                return {
                    "answer": result.get("answer", "无法获取信息"),
                    "decomposition": {
                        "original_query": query,
                        "complexity_level": "简单",
                        "sub_queries": [{"question": query}]
                    },
                    "reasoning": [{"question": query, "confidence_level": "高"}],
                    "tool_results": result,
                    "used_tools": True,
                    "success": result.get("success", False),
                    "fast_route": True  # 标记使用了快速路由
                }
            
        except Exception as e:
            error_msg = f"快速路由处理失败: {str(e)}"
            error_result = {
                "answer": f"处理简单问题时遇到错误: {str(e)}",
                "success": False,
                "fast_route": True
            }
            
            if event_callback:
                await event_callback({
                    "type": "error",
                    "message": error_msg
                })
            else:
                print(error_msg)
                
            return error_result

    async def _handle_context_only_query_unified(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        event_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        统一的上下文查询处理方法，同时支持流式和非流式调用
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            conversation_history: 对话历史
            event_callback: 事件回调函数，用于流式输出
            
        Returns:
            处理结果
        """
        try:
            # 准备基于上下文的提示
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            system_prompt = (
                "你是一个知识渊博的助手。请仔细阅读对话历史，理解用户问题的完整语境，然后基于你的已有知识和提供的上下文来回答用户的问题。\n"
                "重要指导原则：\n"
                "1. 充分理解对话历史：如果用户的问题是对之前对话的延续或追问，请结合历史对话来理解当前问题的真实意图。\n"
                "2. 不要提及需要搜索或查找外部信息，直接给出清晰、准确的答案。\n"
                "**重要要求：必须完全使用中文进行回答。**"
            )
            
            user_prompt = (
                f"上下文信息：\n{context_str}\n\n"
                f"用户问题：{query}\n\n"
                "请直接回答用户的问题。"
            )
            
            # 根据是否有回调来决定使用流式还是非流式调用
            if event_callback:
                # 流式调用
                from ..llm_client import chat_complete_stream
                full_answer = ""
                async for event in chat_complete_stream(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=run_config.model,
                    conversation_history=conversation_history
                ):
                    await event_callback(event)
                    # 收集完整答案用于返回
                    if event.get("type") == "content":
                        full_answer += event.get("content", "")
                        
                answer = full_answer
            else:
                # 非流式调用
                from ..llm_client import chat_complete
                answer = await chat_complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=run_config.model,
                    conversation_history=conversation_history
                )
            
            return {
                "answer": answer,
                "decomposition": {
                    "original_query": query,
                    "complexity_level": "简单",
                    "sub_queries": [{"question": query}]
                },
                "reasoning": [{"question": query, "confidence_level": "高", "needs_tools": False}],
                "tool_results": {},
                "used_tools": False,
                "success": True,
                "context_only": True  # 标记基于上下文回答
            }
            
        except Exception as e:
            error_msg = f"基于上下文的问题处理失败: {str(e)}"
            error_result = {
                "answer": f"处理问题时遇到错误: {str(e)}",
                "success": False,
                "context_only": True
            }
            
            if event_callback:
                await event_callback({
                    "type": "error", 
                    "message": error_msg
                })
            else:
                print(error_msg)
                
            return error_result

    async def close(self):
        """清理资源"""
        if self.tool_orchestrator:
            await self.tool_orchestrator.close()