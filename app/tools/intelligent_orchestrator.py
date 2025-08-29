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
        智能处理用户查询：问题拆解-思考-工具调用
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
        
        Returns:
            处理结果
        """
        execution_context = ToolExecutionContext(
            question=query,
            contexts=contexts,
            run_config=run_config
        )
        
        try:
            # 智能路由：检查问题的处理方式（由LLM判定）
            route_decision = await self.decomposer.should_use_fast_route_async(query, execution_context, conversation_history)
            use_fast_route = route_decision.get("use_fast_route", False)
            needs_tools = route_decision.get("needs_tools", True)
            reason = route_decision.get("reason", "")
            
            if use_fast_route:
                if needs_tools:
                    print(f"[IntelligentOrchestrator] 检测到简单问题，需要工具调用，使用快速路由: {reason}")
                    return await self._handle_simple_query_directly(query, contexts, run_config, conversation_history)
                else:
                    print(f"[IntelligentOrchestrator] 检测到简单问题，无需工具，直接基于知识回答: {reason}")
                    return await self._handle_context_only_query(query, contexts, run_config, conversation_history)
            
            # 第一步：问题拆解
            print("[IntelligentOrchestrator] 开始问题拆解...")
            decomposition = await self.decomposer.decompose(query, execution_context, conversation_history)
            
            # 第二步：独立思考
            print("[IntelligentOrchestrator] 开始独立思考...")
            thoughts = await self.reasoning_engine.think_about_decomposition(
                decomposition, contexts, execution_context
            )
            
            # 第三步：决定是否需要工具调用
            need_tools, knowledge_gaps = self._should_invoke_tools(thoughts)
            
            tool_results = {}
            if need_tools:
                print("[IntelligentOrchestrator] 检测到知识缺口，开始工具调用...")
                tool_results = await self._execute_tools_for_gaps(
                    knowledge_gaps, query, contexts, run_config
                )
            else:
                print("[IntelligentOrchestrator] 无需工具调用，基于思考结果生成答案...")
            
            # 第四步：综合所有信息生成最终答案
            final_answer = await self._synthesize_final_answer(
                query, decomposition, thoughts, tool_results, contexts, run_config, conversation_history
            )
            
            return {
                "answer": final_answer,
                "decomposition": decomposition,
                "reasoning": thoughts,
                "tool_results": tool_results,
                "used_tools": need_tools,
                "success": True
            }
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 智能处理失败: {e}")
            return {
                "answer": f"处理问题时遇到错误: {str(e)}",
                "success": False
            }

    async def process_query_intelligently_stream(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式智能处理用户查询
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
        
        Yields:
            流式处理事件
        """
        execution_context = ToolExecutionContext(
            question=query,
            contexts=contexts,
            run_config=run_config
        )
        
        try:
            # 智能路由：检查问题的处理方式（由LLM判定）
            route_decision = await self.decomposer.should_use_fast_route_async(query, execution_context, conversation_history)
            use_fast_route = route_decision.get("use_fast_route", False)
            needs_tools = route_decision.get("needs_tools", True)
            reason = route_decision.get("reason", "")
            
            if use_fast_route:
                if needs_tools:
                    yield {
                        "type": "reasoning",
                        "content": f"分类为简单查询，需要外部工具，直接获取信息... ({reason})"
                    }
                    async for event in self._handle_simple_query_directly_stream(query, contexts, run_config, conversation_history):
                        yield event
                    return
                else:
                    yield {
                        "type": "reasoning",
                        "content": f"分类为简单问题，基于已有知识回答... ({reason})"
                    }
                    async for event in self._handle_context_only_query_stream(query, contexts, run_config, conversation_history):
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
                decomposition, contexts, execution_context
            )
            
            overall_confidence = self.reasoning_engine.assess_overall_confidence(thoughts)
            
            yield {
                "type": "reasoning",
                "content": f"思考完成，整体置信度: {overall_confidence}。"
            }
            
            # 第三步：决定是否需要工具调用
            need_tools, knowledge_gaps = self._should_invoke_tools(thoughts)
            
            if need_tools:
                yield {
                    "type": "reasoning",
                    "content": f"检测到{len(knowledge_gaps)}个知识缺口，开始搜索外部信息..."
                }
                
                # 流式执行工具调用
                tool_results = {}
                async for tool_event in self._execute_tools_for_gaps_stream(
                    knowledge_gaps, query, contexts, run_config
                ):
                    # 转发工具调用事件
                    yield tool_event
                    
                    # 收集工具结果
                    if tool_event.get("type") == "final_tool_result":
                        tool_results = tool_event.get("result", {})
                
            else:
                yield {
                    "type": "reasoning",
                    "content": "基于现有知识可以回答，无需外部搜索"
                }
                tool_results = {}
            
            # 第四步：流式生成最终答案
            yield {
                "type": "reasoning",
                "content": "正在综合所有信息生成完整答案..."
            }
            
            async for synthesis_event in self._synthesize_final_answer_stream(
                query, decomposition, thoughts, tool_results, contexts, run_config, conversation_history
            ):
                yield synthesis_event
                
        except Exception as e:
            yield {
                "type": "error",
                "message": f"智能处理失败: {str(e)}"
            }

    async def _run_web_search_and_recall(
        self,
        knowledge_gaps: List[Dict[str, Any]],
        original_query: str,
        run_config: RunConfig
    ) -> Dict[str, Any]:
        """
        统一的web搜索和召回实现（流式/非流式共用）
        
        Args:
            knowledge_gaps: 知识缺口列表
            original_query: 原始查询
            run_config: 运行配置
            
        Returns:
            包含knowledge_gaps_search_results和统计信息的结果字典
        """
        if not knowledge_gaps:
            return {"knowledge_gaps_search_results": {}, "success": False, "message": "没有知识缺口需要搜索"}
        
        try:
            # 1. 使用搜索规划器生成统一的查询列表
            final_queries = self.search_planner.plan_search_queries(original_query, knowledge_gaps)
            
            from ..config import MAX_KNOWLEDGE_GAPS, GAP_RECALL_TOP_K
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
                session_id=unified_session_id
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
            selected_gaps = knowledge_gaps[:MAX_KNOWLEDGE_GAPS]
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

    async def _execute_tools_for_gaps(
        self, 
        knowledge_gaps: List[Dict[str, Any]], 
        original_query: str,
        contexts: List[str],
        run_config: RunConfig
    ) -> Dict[str, Any]:
        """
        针对知识缺口执行工具调用（非流式版本）
        """
        if not knowledge_gaps:
            return {}
        
        # 使用统一的搜索和召回实现
        result = await self._run_web_search_and_recall(knowledge_gaps, original_query, run_config)
        
        if not result.get("success"):
            return {
                "answer": result.get("message", "搜索和召回失败"),
                "success": False,
                "steps": [],
                "error": result.get("error")
            }
        
        # 格式化为最终答案
        knowledge_gaps_search_results = result.get("knowledge_gaps_search_results", {})
        selected_gaps = result.get("selected_gaps", [])
        statistics = result.get("statistics", {})
        
        return {
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
    


    async def _execute_tools_for_gaps_stream(
        self, 
        knowledge_gaps: List[Dict[str, Any]], 
        original_query: str,
        contexts: List[str],
        run_config: RunConfig
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        针对知识缺口流式执行工具调用（流式版本）
        """
        if not knowledge_gaps:
            yield {"type": "final_tool_result", "result": {}}
            return
        
        try:
            # 发出搜索开始事件
            yield {
                "type": "tool_call",
                "name": "web_search_and_recall",
                "args": {
                    "query": original_query,
                    "gap_count": len(knowledge_gaps)
                }
            }
            
            # 使用统一的搜索和召回实现（与非流式版本完全相同的数据路径）
            result = await self._run_web_search_and_recall(knowledge_gaps, original_query, run_config)
            
            # 发出搜索结果事件
            yield {
                "type": "tool_result",
                "name": "web_search_and_recall", 
                "result": result.get("message", "搜索和召回完成"),
                "success": result.get("success", False)
            }
            
            # 发出最终结果
            if result.get("success"):
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
            else:
                final_result = {
                    "answer": result.get("message", "搜索和召回失败"),
                    "success": False,
                    "steps": [],
                    "error": result.get("error")
                }
            
            yield {"type": "final_tool_result", "result": final_result}
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 流式统一搜索和召回失败: {e}")
            # 回退到原有的工具编排器
            final_queries = self.search_planner.plan_search_queries(original_query, knowledge_gaps)
            enhanced_query = f"{original_query} {' '.join(final_queries[:2])}"
            
            async for event in self.tool_orchestrator.execute_stream(
                enhanced_query, contexts, run_config
            ):
                yield event

    async def _synthesize_final_answer(
        self, 
        original_query: str,
        decomposition: Dict[str, Any],
        thoughts: List[Dict[str, Any]],
        tool_results: Dict[str, Any],
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        综合所有信息生成最终答案
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
            
            # 使用通用LLM客户端生成最终答案（延迟导入避免循环导入）
            from ..llm_client import chat_complete
            return await chat_complete(
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=run_config.model,
                conversation_history=conversation_history
            )
                
        except Exception as e:
            print(f"答案综合失败: {e}")
            # 返回基于思考结果的简单答案
            return self.reasoning_engine.generate_preliminary_answer(thoughts)

    async def _synthesize_final_answer_stream(
        self,
        original_query: str,
        decomposition: Dict[str, Any], 
        thoughts: List[Dict[str, Any]],
        tool_results: Dict[str, Any],
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式综合生成最终答案
        """
        try:
            reasoning_summary = OutputFormatter.format_reasoning_summary(thoughts)
            tool_summary = OutputFormatter.format_tool_results(tool_results)
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            user_prompt = SYNTHESIS_USER_PROMPT_TEMPLATE.format(
                original_query=original_query,
                reasoning_summary=reasoning_summary,
                tool_results=tool_summary,
                context=context_str
            )
            
            # 使用通用LLM客户端进行流式调用（延迟导入避免循环导入）
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
                "message": f"流式答案生成失败: {str(e)}"
            }





    async def _handle_simple_query_directly(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        直接处理简单问题，跳过复杂的分解和推理流程
        
        Args:
            query: 简单问题
            contexts: 相关上下文
            run_config: 运行配置
            
        Returns:
            处理结果
        """
        try:
            # 直接使用工具编排器处理
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
            print(f"快速路由处理失败: {e}")
            return {
                "answer": f"处理简单问题时遇到错误: {str(e)}",
                "success": False,
                "fast_route": True
            }

    async def _handle_simple_query_directly_stream(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理简单问题，跳过复杂的分解和推理流程
        
        Args:
            query: 简单问题
            contexts: 相关上下文
            run_config: 运行配置
            
        Yields:
            流式处理事件
        """
        try:
            # 直接使用工具编排器流式处理
            async for event in self.tool_orchestrator.execute_stream(
                query, contexts, run_config, conversation_history
            ):
                yield event
                
        except Exception as e:
            yield {
                "type": "error",
                "message": f"快速路由流式处理失败: {str(e)}"
            }

    async def _handle_context_only_query(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        处理完全不需要外部工具的简单问题，直接基于提供的上下文生成答案
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            
        Returns:
            处理结果
        """
        try:
            # 准备基于上下文的提示
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            system_prompt = (
                "你是一个知识渊博的助手。请仅基于你的已有知识和提供的上下文来回答用户的问题。\n"
                "不要提及需要搜索或查找外部信息，直接给出清晰、准确的答案。\n"
                "如果上下文中有相关信息，请优先使用；如果没有，则基于你的常识知识回答。\n"
                "**重要要求：必须完全使用中文进行回答。**"
            )
            
            user_prompt = (
                f"上下文信息：\n{context_str}\n\n"
                f"用户问题：{query}\n\n"
                "请直接回答用户的问题。"
            )
            
            # 使用通用LLM客户端生成答案（延迟导入避免循环导入）
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
                "context_only": True  # 标记仅基于上下文回答
            }
            
        except Exception as e:
            print(f"基于上下文的问题处理失败: {e}")
            return {
                "answer": f"处理问题时遇到错误: {str(e)}",
                "success": False,
                "context_only": True
            }

    async def _handle_context_only_query_stream(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理完全不需要外部工具的简单问题，直接基于提供的上下文生成答案
        
        Args:
            query: 用户问题
            contexts: 相关上下文
            run_config: 运行配置
            
        Yields:
            流式处理事件
        """
        try:
            # 准备基于上下文的提示
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            system_prompt = (
                "你是一个知识渊博的助手。请仅基于你的已有知识和提供的上下文来回答用户的问题。\n"
                "不要提及需要搜索或查找外部信息，直接给出清晰、准确的答案。\n"
                "如果上下文中有相关信息，请优先使用；如果没有，则基于你的常识知识回答。\n"
                "**重要要求：必须完全使用中文进行回答。**"
            )
            
            user_prompt = (
                f"上下文信息：\n{context_str}\n\n"
                f"用户问题：{query}\n\n"
                "请直接回答用户的问题。"
            )
            
            # 使用通用LLM客户端进行流式调用（延迟导入避免循环导入）
            from ..llm_client import chat_complete_stream
            async for event in chat_complete_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=run_config.model,
                conversation_history=conversation_history
            ):
                yield event
                            
        except Exception as e:
            yield {
                "type": "error", 
                "message": f"基于上下文的流式问题处理失败: {str(e)}"
            }

    async def close(self):
        """清理资源"""
        if self.tool_orchestrator:
            await self.tool_orchestrator.close()
