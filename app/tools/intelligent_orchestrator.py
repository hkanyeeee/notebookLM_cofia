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
from ..config import LLM_SERVICE_URL
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
        
        self.synthesis_prompt = """
基于以下信息，请为用户提供一个完整、准确的回答。

原始问题: {original_query}

独立思考结果:
{reasoning_summary}

工具调用结果:
{tool_results}

上下文信息:
{context}

重要指导：
1. 如果工具调用成功获取了信息，请优先使用这些最新、具体的数据来回答问题
2. 不要说"根据搜索结果"或"根据获取的信息"等提示性词语
3. 不要说"无法获取"、"无法访问"等消极表述，如果工具已获取信息
4. 直接基于获得的具体数据给出明确、肯定的答案
5. 如果工具调用失败或无结果，才说明无法获取信息

请综合所有信息，提供一个结构化的完整回答：
- 直接回答用户的问题
- 使用获取到的具体数据和信息
- 保持客观和准确
- 用自然的语言组织回答

请用自然的语言组织回答，不需要返回JSON格式。
"""

    async def process_query_intelligently(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig
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
            # 智能路由：检查是否是简单问题，可以直接调用工具
            complexity = self.decomposer.analyze_query_complexity(query)
            if complexity == "简单" and self._should_use_fast_route(query):
                print("[IntelligentOrchestrator] 检测到简单问题，使用快速路由...")
                return await self._handle_simple_query_directly(query, contexts, run_config)
            
            # 第一步：问题拆解
            print("[IntelligentOrchestrator] 开始问题拆解...")
            decomposition = await self.decomposer.decompose(query, execution_context)
            
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
                query, decomposition, thoughts, tool_results, contexts, run_config
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
        run_config: RunConfig
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
            # 智能路由：检查是否是简单问题，可以直接调用工具
            complexity = self.decomposer.analyze_query_complexity(query)
            if complexity == "简单" and self._should_use_fast_route(query):
                yield {
                    "type": "reasoning",
                    "content": "检测到简单查询，直接获取信息..."
                }
                async for event in self._handle_simple_query_directly_stream(query, contexts, run_config):
                    yield event
                return
            
            # 第一步：问题拆解
            yield {
                "type": "reasoning",
                "content": "正在分析和拆解您的问题..."
            }
            
            decomposition = await self.decomposer.decompose(query, execution_context)
            
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
                "content": "基于已有知识进行独立思考..."
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
                query, decomposition, thoughts, tool_results, contexts, run_config
            ):
                yield synthesis_event
                
        except Exception as e:
            yield {
                "type": "error",
                "message": f"智能处理失败: {str(e)}"
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
        针对知识缺口执行工具调用
        """
        if not knowledge_gaps:
            return {}
        
        # 构建搜索查询
        search_queries = []
        for gap in knowledge_gaps[:3]:  # 限制最多3个高优先级缺口
            keywords = gap.get("search_keywords", [])
            if keywords:
                search_query = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
                search_queries.append(search_query)
        
        if not search_queries:
            search_queries = [original_query]  # 回退到原始查询
        
        # 确保至少包含原始查询
        if original_query not in search_queries:
            search_queries.insert(0, original_query)
        
        # 限制搜索查询数量，避免过多搜索
        final_queries = search_queries[:3]
        
        print(f"[IntelligentOrchestrator] 直接控制搜索关键词: {final_queries}")
        
        # 创建带有预定义搜索关键词的工具执行环境
        from .models import ToolExecutionContext
        from ..tools.web_search_tool import web_search_tool
        import uuid
        
        # 生成统一的会话ID用于本次智能问答
        unified_session_id = str(uuid.uuid4())
        print(f"[IntelligentOrchestrator] 使用统一会话ID: {unified_session_id}")
        
        try:
            # 直接调用web搜索工具，传递预定义的搜索关键词
            result = await web_search_tool.execute(
                query=original_query,
                language="zh-CN",  # 默认中文搜索
                categories="",
                filter_list=None,
                model=run_config.model,
                predefined_queries=final_queries,
                session_id=unified_session_id
            )
            
            # 转换为工具编排器期望的格式
            if result.get("success"):
                return {
                    "answer": self._format_search_result_answer(result),
                    "success": True,
                    "steps": [
                        {
                            "type": "action",
                            "content": f"执行web搜索，查询: {final_queries}",
                            "tool": "web_search"
                        },
                        {
                            "type": "observation", 
                            "content": result.get("message", "搜索完成")
                        }
                    ],
                    "tool_calls": 1,
                    "session_id": unified_session_id
                }
            else:
                return {
                    "answer": "搜索失败，无法获取外部信息",
                    "success": False,
                    "steps": []
                }
                
        except Exception as e:
            print(f"[IntelligentOrchestrator] 直接搜索调用失败: {e}")
            # 回退到原有的工具编排器
            enhanced_query = f"{original_query} {' '.join(search_queries[:2])}"
            return await self.tool_orchestrator.execute_non_stream(
                enhanced_query, contexts, run_config
            )

    def _format_search_result_answer(self, search_result: Dict[str, Any]) -> str:
        """
        格式化搜索结果为答案文本
        """
        if not search_result.get("success"):
            return "搜索失败，无法获取信息"
        
        retrieved_content = search_result.get("retrieved_content", [])
        if not retrieved_content:
            return "搜索完成但未找到相关信息"
        
        # 构建基于搜索结果的答案
        answer_parts = ["基于网络搜索获取的信息：\n"]
        
        for i, content in enumerate(retrieved_content[:3], 1):  # 只取前3个最相关的结果
            content_text = content.get("content", "").strip()
            source_url = content.get("source_url", "")
            score = content.get("score", 0)
            
            if content_text:
                # 限制每个片段的长度
                if len(content_text) > 300:
                    content_text = content_text[:300] + "..."
                
                answer_parts.append(f"{i}. {content_text}")
                if source_url:
                    answer_parts.append(f"   来源: {source_url}")
                answer_parts.append("")  # 空行分隔
        
        return "\n".join(answer_parts)

    async def _execute_tools_for_gaps_stream(
        self, 
        knowledge_gaps: List[Dict[str, Any]], 
        original_query: str,
        contexts: List[str],
        run_config: RunConfig
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        针对知识缺口流式执行工具调用
        """
        if not knowledge_gaps:
            yield {"type": "final_tool_result", "result": {}}
            return
        
        # 构建搜索查询（与非流式版本相同）
        search_queries = []
        for gap in knowledge_gaps[:3]:  # 限制最多3个高优先级缺口
            keywords = gap.get("search_keywords", [])
            if keywords:
                search_query = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
                search_queries.append(search_query)
        
        if not search_queries:
            search_queries = [original_query]  # 回退到原始查询
        
        # 确保至少包含原始查询
        if original_query not in search_queries:
            search_queries.insert(0, original_query)
        
        # 限制搜索查询数量，避免过多搜索
        final_queries = search_queries[:3]
        
        print(f"[IntelligentOrchestrator] 流式直接控制搜索关键词: {final_queries}")
        
        from ..tools.web_search_tool import web_search_tool
        import uuid
        
        # 生成统一的会话ID用于本次智能问答
        unified_session_id = str(uuid.uuid4())
        
        try:
            # 发出搜索开始事件
            yield {
                "type": "tool_call",
                "name": "web_search",
                "args": {
                    "query": original_query,
                    "predefined_queries": final_queries
                }
            }
            
            # 直接调用web搜索工具（非流式，因为web搜索本身不支持流式）
            result = await web_search_tool.execute(
                query=original_query,
                language="zh-CN",  # 默认中文搜索
                categories="",
                filter_list=None,
                model=run_config.model,
                predefined_queries=final_queries,
                session_id=unified_session_id
            )
            
            # 发出搜索结果事件
            yield {
                "type": "tool_result",
                "name": "web_search",
                "result": result.get("message", "搜索完成"),
                "success": result.get("success", False)
            }
            
            # 发出最终结果
            if result.get("success"):
                final_result = {
                    "answer": self._format_search_result_answer(result),
                    "success": True,
                    "steps": [
                        {
                            "type": "action",
                            "content": f"执行web搜索，查询: {final_queries}",
                            "tool": "web_search"
                        },
                        {
                            "type": "observation",
                            "content": result.get("message", "搜索完成")
                        }
                    ],
                    "tool_calls": 1,
                    "session_id": unified_session_id
                }
            else:
                final_result = {
                    "answer": "搜索失败，无法获取外部信息",
                    "success": False,
                    "steps": []
                }
            
            yield {"type": "final_tool_result", "result": final_result}
            
        except Exception as e:
            print(f"[IntelligentOrchestrator] 流式直接搜索调用失败: {e}")
            # 回退到原有的工具编排器
            enhanced_query = f"{original_query} {' '.join(search_queries[:2])}"
            
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
        run_config: RunConfig
    ) -> str:
        """
        综合所有信息生成最终答案
        """
        try:
            # 准备综合信息
            reasoning_summary = self._format_reasoning_summary(thoughts)
            tool_summary = self._format_tool_results(tool_results)
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            prompt = self.synthesis_prompt.format(
                original_query=original_query,
                reasoning_summary=reasoning_summary,
                tool_results=tool_summary,
                context=context_str
            )
            
            # 调用LLM生成最终答案
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.llm_service_url}/chat/completions",
                    json={
                        "model": run_config.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是一个专业的问题回答专家，能够综合多种信息源提供准确、完整的答案。"
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2000
                    },
                    timeout=45.0
                )
                
                if response.status_code != 200:
                    raise Exception(f"LLM请求失败: {response.status_code}")
                
                result = response.json()
                return result["choices"][0]["message"]["content"]
                
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
        run_config: RunConfig
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式综合生成最终答案
        """
        try:
            reasoning_summary = self._format_reasoning_summary(thoughts)
            tool_summary = self._format_tool_results(tool_results)
            context_str = "\n".join(contexts) if contexts else "无特定上下文"
            
            prompt = self.synthesis_prompt.format(
                original_query=original_query,
                reasoning_summary=reasoning_summary,
                tool_results=tool_summary,
                context=context_str
            )
            
            # 流式调用LLM
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.llm_service_url}/chat/completions",
                    json={
                        "model": run_config.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是一个专业的问题回答专家，能够综合多种信息源提供准确、完整的答案。"
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                        "stream": True
                    },
                    timeout=45.0
                )
                
                if response.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"LLM请求失败: {response.status_code}"
                    }
                    return
                
                # 处理流式响应
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # 移除"data: "前缀
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield {
                                        "type": "content",
                                        "content": delta["content"]
                                    }
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            yield {
                "type": "error", 
                "message": f"流式答案生成失败: {str(e)}"
            }

    def _format_reasoning_summary(self, thoughts: List[Dict[str, Any]]) -> str:
        """
        格式化思考结果摘要
        """
        if not thoughts:
            return "无思考结果"
        
        summary_parts = []
        for i, thought in enumerate(thoughts, 1):
            question = thought.get("question", f"子问题{i}")
            process = thought.get("thought_process", "无思考过程")
            confidence = thought.get("confidence_level", "未知")
            
            summary_parts.append(f"问题{i}: {question}")
            summary_parts.append(f"思考: {process}")
            summary_parts.append(f"置信度: {confidence}")
            summary_parts.append("")  # 空行分隔
        
        return "\n".join(summary_parts)

    def _format_tool_results(self, tool_results: Dict[str, Any]) -> str:
        """
        格式化工具调用结果
        """
        if not tool_results:
            return "无工具调用结果"
        
        if not tool_results.get("success", False):
            return "工具调用失败，无可用信息"
        
        # 优先使用完整答案
        answer = tool_results.get("answer", "")
        if answer and len(answer.strip()) > 10:  # 确保答案有实际内容
            return f"获取的信息: {answer.strip()}"
        
        # 其次使用步骤中的内容信息
        steps = tool_results.get("steps", [])
        content_steps = []
        
        for step in steps:
            step_type = step.get("type", "")
            content = step.get("content", "")
            
            # 优先收集包含实际信息的步骤
            if step_type == "content" and content and len(content.strip()) > 10:
                content_steps.append(content.strip())
            elif "天气" in content or "温度" in content or "降水" in content:  # 天气相关内容
                content_steps.append(content.strip())
        
        if content_steps:
            return "获取的具体信息:\n" + "\n".join(content_steps)
        
        # 最后尝试从所有步骤中提取信息
        if steps:
            step_summaries = []
            for step in steps:
                step_type = step.get("type", "unknown")
                content = step.get("content", "")
                if content and len(content.strip()) > 5:
                    step_summaries.append(f"{step_type}: {content.strip()}")
            
            if step_summaries:
                return "工具执行过程:\n" + "\n".join(step_summaries[:3])  # 限制显示前3个
        
        return "工具调用完成但提取不到具体信息"

    def _should_use_fast_route(self, query: str) -> bool:
        """
        判断是否应该使用快速路由（跳过复杂分解）
        
        Args:
            query: 用户问题
            
        Returns:
            是否使用快速路由
        """
        import re
        
        # 明确的快速路由模式（这些问题通常只需要一次工具调用）
        fast_route_patterns = [
            r'(今天|现在|当前|目前).*(天气|气温|温度|下雨|晴天)',  # 当前天气
            r'.*(天气|气温|温度).*如何',                        # 天气询问
            r'.*(时间|几点).*现在',                            # 当前时间
            r'.*股价.*多少',                                  # 股价查询
            r'.*价格.*多少',                                  # 价格查询
            r'.*汇率.*多少',                                  # 汇率查询
            r'.*新闻.*今天',                                  # 今日新闻
        ]
        
        # 检查是否匹配快速路由模式
        return any(re.search(pattern, query) for pattern in fast_route_patterns)

    async def _handle_simple_query_directly(
        self, 
        query: str, 
        contexts: List[str], 
        run_config: RunConfig
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
                query, contexts, run_config
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
        run_config: RunConfig
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
                query, contexts, run_config
            ):
                yield event
                
        except Exception as e:
            yield {
                "type": "error",
                "message": f"快速路由流式处理失败: {str(e)}"
            }

    async def close(self):
        """清理资源"""
        if self.tool_orchestrator:
            await self.tool_orchestrator.close()
