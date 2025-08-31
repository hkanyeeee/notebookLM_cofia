"""
输出格式化器 - 统一管理各种输出格式化功能
"""
from typing import List, Dict, Any


class OutputFormatter:
    """
    输出格式化器：统一处理各种输出的格式化
    """
    
    @staticmethod
    def format_reasoning_summary(thoughts: List[Dict[str, Any]]) -> str:
        """
        格式化思考结果摘要
        
        Args:
            thoughts: 思考结果列表
            
        Returns:
            格式化后的思考摘要
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
    
    @staticmethod
    def format_tool_results(tool_results: Dict[str, Any]) -> str:
        """
        格式化工具调用结果，避免提示性词语，优先提取原始搜索内容
        
        Args:
            tool_results: 工具调用结果字典
            
        Returns:
            格式化后的工具结果信息
        """
        if not tool_results:
            return "无工具调用结果"
        
        if not tool_results.get("success", False):
            return "工具调用失败，无可用信息"
        
        # 优先检查是否有 knowledge_gaps_search_results（统一搜索路径的召回结果）
        knowledge_gaps_search_results = tool_results.get("knowledge_gaps_search_results", {})
        tool_content = []
        
        if knowledge_gaps_search_results:
            # 从知识缺口搜索结果中提取召回内容
            for gap_id, gap_info in knowledge_gaps_search_results.items():
                recalled_content = gap_info.get("recalled_content", [])
                for item in recalled_content:
                    item_content = item.get("content", "").strip()
                    if item_content:
                        tool_content.append(item_content)
        
        # 其次从步骤中提取工具调用的原始结果（特别是搜索内容）
        steps = tool_results.get("steps", [])
        
        for step in steps:
            step_type = step.get("type", "")
            
            # 提取工具调用的观察结果（observation）
            if step_type == "observation":
                content = step.get("content", "")
                tool_result = step.get("tool_result", {})
                
                # 如果有工具结果，优先使用工具结果中的原始内容
                if tool_result and isinstance(tool_result, dict):
                    result_data = tool_result.get("result", "")
                    if isinstance(result_data, str) and len(result_data.strip()) > 20:
                        # 尝试解析JSON格式的工具结果
                        try:
                            import json
                            parsed_result = json.loads(result_data)
                            if isinstance(parsed_result, dict):
                                # 提取搜索到的内容
                                retrieved_content = parsed_result.get("retrieved_content", [])
                                if retrieved_content:
                                    for item in retrieved_content:
                                        item_content = item.get("content", "").strip()
                                        if item_content:
                                            tool_content.append(item_content)
                                
                                # 同时提取 top_results 中的 content_preview
                                top_results = parsed_result.get("top_results", [])
                                if top_results:
                                    for item in top_results:
                                        content_preview = item.get("content_preview", "").strip()
                                        if content_preview:
                                            tool_content.append(content_preview)
                        except (json.JSONDecodeError, AttributeError):
                            # 如果解析失败，直接使用原始结果
                            if result_data.strip():
                                tool_content.append(result_data.strip())
                
                # 如果没有提取到工具结果，使用步骤内容
                elif content and content.strip():
                    # 去除"工具执行结果："等前缀
                    clean_content = content.replace("工具执行结果：", "").replace("Observation: ", "").strip()
                    if clean_content:
                        tool_content.append(clean_content)
        
        # 如果从步骤中提取到了有用内容，使用这些内容
        if tool_content:
            return "获取的具体信息:\n" + "\n\n".join(tool_content)
        
        # 其次使用步骤中的其他内容信息
        content_steps = []
        for step in steps:
            step_type = step.get("type", "")
            content = step.get("content", "")
            
            # 收集包含实际信息的步骤（非工具调用和观察）
            if step_type == "content" and content and content.strip():
                content_steps.append(content)
        
        if content_steps:
            return "获取的具体信息:\n" + "\n".join(content_steps)
        
        # 备选方案：使用完整答案（但不是最优选择）
        answer = tool_results.get("answer", "")
        if answer and answer.strip():
            # 避免直接返回工具编排器的答案，而是标记为参考信息
            return f"参考信息: {answer}"
        
        # 最后尝试从所有步骤中提取信息
        if steps:
            step_summaries = []
            for step in steps:
                step_type = step.get("type", "unknown")
                content = step.get("content", "")
                if content and content.strip():
                    step_summaries.append(f"{step_type}: {content}")
            
            if step_summaries:
                return "工具执行过程:\n" + "\n".join(step_summaries)
        
        return "工具调用完成但提取不到具体信息"
    
    @staticmethod
    def format_gap_based_answer(knowledge_gaps_search_results: Dict[str, Any], selected_gaps: List[Dict[str, Any]]) -> str:
        """
        基于知识缺口搜索结果格式化答案，提供自然的表达
        
        Args:
            knowledge_gaps_search_results: 知识缺口搜索结果
            selected_gaps: 选中的知识缺口列表
        
        Returns:
            自然的答案文本，无提示性词语
        """
        if not knowledge_gaps_search_results:
            return "未能获取到相关信息来回答问题。"
        
        # 收集所有有效内容
        all_content = []
        source_info = []
        
        for gap_idx, gap in enumerate(selected_gaps):
            gap_id = f"gap_{gap_idx}"
            gap_info = knowledge_gaps_search_results.get(gap_id)
            
            if not gap_info or not gap_info.get("recalled_content"):
                continue
            
            recalled_content = gap_info["recalled_content"]
            
            # 为每个知识缺口收集内容
            for idx, content_item in enumerate(recalled_content, 1):
                content = content_item["content"]
                source_title = content_item.get("source_title", "")
                source_url = content_item.get("source_url", "")
                
                all_content.append(content)
                
                # 收集来源信息（可选显示）
                if source_title and source_url:
                    source_info.append(f"来源: {source_title}")
        
        if all_content:
            # 自然地整合内容，不使用"基于搜索结果"等词语
            final_answer = "\n\n".join(all_content)
            
            # 如果需要显示来源（可选）
            # if source_info:
            #     final_answer += "\n\n参考信息来源:\n" + "\n".join(source_info[:3])
            
            return final_answer
        else:
            return "暂未找到足够相关的信息来完整回答问题。"
    
    @staticmethod 
    def format_search_result_answer(search_result: Dict[str, Any]) -> str:
        """
        格式化搜索结果为自然的答案文本（保留原有方法以兼容）
        
        Args:
            search_result: 搜索结果字典
            
        Returns:
            自然表达的答案
        """
        if not search_result.get("success"):
            return "搜索失败，无法获取信息"
        
        retrieved_content = search_result.get("retrieved_content", [])
        if not retrieved_content:
            return "搜索完成但未找到相关信息"
        
        # 构建基于搜索结果的答案，自然表达
        content_parts = []
        
        for i, content in enumerate(retrieved_content, 1):
            content_text = content.get("content", "").strip()
            
            if content_text:
                content_parts.append(content_text)
        
        if content_parts:
            return "\n\n".join(content_parts)
        else:
            return "未找到可用的相关信息。"