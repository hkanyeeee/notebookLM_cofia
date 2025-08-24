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
        格式化工具调用结果，避免提示性词语
        
        Args:
            tool_results: 工具调用结果字典
            
        Returns:
            格式化后的工具结果信息
        """
        if not tool_results:
            return "无工具调用结果"
        
        if not tool_results.get("success", False):
            return "工具调用失败，无可用信息"
        
        # 优先使用完整答案
        answer = tool_results.get("answer", "")
        if answer and len(answer.strip()) > 10:  # 确保答案有实际内容
            # 清理答案中的提示性词语
            return f"获取的信息: {cleaned_answer}"
        
        # 其次使用步骤中的内容信息
        steps = tool_results.get("steps", [])
        content_steps = []
        
        for step in steps:
            step_type = step.get("type", "")
            content = step.get("content", "")
            
            # 优先收集包含实际信息的步骤
            if step_type == "content" and content and len(content.strip()) > 10:
                content_steps.append(cleaned_content)
            elif "天气" in content or "温度" in content or "降水" in content:  # 天气相关内容
                content_steps.append(cleaned_content)
        
        if content_steps:
            return "获取的具体信息:\n" + "\n".join(content_steps)
        
        # 最后尝试从所有步骤中提取信息
        if steps:
            step_summaries = []
            for step in steps:
                step_type = step.get("type", "unknown")
                content = step.get("content", "")
                if content and len(content.strip()) > 5:
                    step_summaries.append(f"{step_type}: {cleaned_content}")
            
            if step_summaries:
                return "工具执行过程:\n" + "\n".join(step_summaries[:3])  # 限制显示前3个
        
        return "工具调用完成但提取不到具体信息"
    
    @staticmethod
    def format_gap_based_answer(gap_recall_results: Dict[str, Any], selected_gaps: List[Dict[str, Any]]) -> str:
        """
        基于知识缺口召回结果格式化答案，提供自然的表达
        
        Args:
            gap_recall_results: 知识缺口召回结果
            selected_gaps: 选中的知识缺口列表
        
        Returns:
            自然的答案文本，无提示性词语
        """
        if not gap_recall_results:
            return "未能获取到相关信息来回答问题。"
        
        # 收集所有有效内容
        all_content = []
        source_info = []
        
        for gap_idx, gap in enumerate(selected_gaps):
            gap_id = f"gap_{gap_idx}"
            gap_info = gap_recall_results.get(gap_id)
            
            if not gap_info or not gap_info.get("recalled_content"):
                continue
            
            recalled_content = gap_info["recalled_content"]
            
            # 为每个知识缺口收集内容
            for idx, content_item in enumerate(recalled_content[:3], 1):  # 只展示前3个最相关的
                content = content_item["content"]
                source_title = content_item.get("source_title", "")
                source_url = content_item.get("source_url", "")
                
                # 限制内容长度并清理
                if len(content) > 300:
                    content = content[:300] + "..."
                
                all_content.append(cleaned_content)
                
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
        
        for i, content in enumerate(retrieved_content[:3], 1):  # 只取前3个最相关的结果
            content_text = content.get("content", "").strip()
            
            if content_text:
                # 限制每个片段的长度
                if len(content_text) > 300:
                    content_text = content_text[:300] + "..."
                
                # 清理提示性词语
                content_parts.append(cleaned_text)
        
        if content_parts:
            return "\n\n".join(content_parts)
        else:
            return "未找到可用的相关信息。"