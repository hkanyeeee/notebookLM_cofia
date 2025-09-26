"""
搜索规划器 - 统一搜索关键词生成和优化
"""
import re
from typing import List, Dict, Any, Set, Optional
from ..config import (
    WEB_SEARCH_MAX_QUERIES, 
    MAX_KEYWORDS_PER_GAP,
    MAX_WORDS_PER_QUERY,
    # 简单查询专用配置
    SIMPLE_QUERY_MAX_QUERIES,
    SIMPLE_QUERY_MAX_WORDS_PER_QUERY
)


class SearchPlanner:
    """
    搜索规划器：统一处理搜索关键词的生成、优化、去重和上限控制
    支持不同查询类型的差异化配置
    """
    
    def __init__(self):
        self.MAX_WORDS_PER_QUERY = MAX_WORDS_PER_QUERY  # 每个查询的最大词数（默认配置）
    
    def plan_search_queries(
        self, 
        original_query: str, 
        knowledge_gaps: List[Dict[str, Any]] = None,
        max_queries: Optional[int] = None,
        max_words_per_query: Optional[int] = None,
        is_simple_query: bool = False
    ) -> List[str]:
        """
        规划搜索查询：从原始问题和知识缺口生成最终的搜索查询列表
        
        Args:
            original_query: 原始用户问题
            knowledge_gaps: 知识缺口列表
            max_queries: 最大查询数量，如果不提供则使用默认配置
            max_words_per_query: 每个查询的最大词数，如果不提供则使用默认配置
            is_simple_query: 是否为简单查询模式
        
        Returns:
            去重、优化并限制数量的最终查询列表
        """
        # 根据查询类型确定配置参数
        if is_simple_query:
            effective_max_queries = max_queries or SIMPLE_QUERY_MAX_QUERIES
            effective_max_words = max_words_per_query or SIMPLE_QUERY_MAX_WORDS_PER_QUERY
            print(f"[SearchPlanner] 使用简单查询配置: max_queries={effective_max_queries}, max_words_per_query={effective_max_words}")
        else:
            effective_max_queries = max_queries or WEB_SEARCH_MAX_QUERIES
            effective_max_words = max_words_per_query or MAX_WORDS_PER_QUERY
            print(f"[SearchPlanner] 使用普通查询配置: max_queries={effective_max_queries}, max_words_per_query={effective_max_words}")
        
        # 临时更新词数限制配置
        original_max_words = self.MAX_WORDS_PER_QUERY
        self.MAX_WORDS_PER_QUERY = effective_max_words
        all_keywords = []
        
        # 1. 从知识缺口中提取关键词
        if knowledge_gaps:
            gap_keywords = self._extract_keywords_from_gaps(knowledge_gaps)
            all_keywords.extend(gap_keywords)
        
        # 2. 从原始问题生成关键词作为补充
        original_keywords = self._generate_practical_keywords(original_query)
        all_keywords.extend(original_keywords)
        
        # 3. 优化关键词（长度控制、格式规范化）
        optimized_keywords = self._optimize_search_keywords(all_keywords, original_query)
        
        # 4. 清理和验证（去重、有效性检查）
        final_queries = self._clean_and_validate_queries(optimized_keywords, original_query)
        
        # 5. 应用配置限制
        final_queries = final_queries[:effective_max_queries]
        
        # 恢复原始配置
        self.MAX_WORDS_PER_QUERY = original_max_words
        
        print(f"[SearchPlanner] 搜索规划完成:")
        print(f"[SearchPlanner]   查询模式: {'简单查询' if is_simple_query else '普通查询'}")
        print(f"[SearchPlanner]   知识缺口: {len(knowledge_gaps) if knowledge_gaps else 0} 个")
        print(f"[SearchPlanner]   原始关键词: {len(all_keywords)} 个") 
        print(f"[SearchPlanner]   最终查询: {len(final_queries)} 个")
        for i, query in enumerate(final_queries, 1):
            print(f"[SearchPlanner]     {i}. {query}")
        
        return final_queries
    
    def _extract_keywords_from_gaps(self, knowledge_gaps: List[Dict[str, Any]]) -> List[str]:
        """
        从知识缺口中提取搜索关键词
        
        Args:
            knowledge_gaps: 知识缺口列表
        
        Returns:
            关键词列表
        """
        keywords = []
        
        # 直接遍历全部知识缺口（不再限制数量）
        for gap in knowledge_gaps:
            gap_keywords = gap.get("search_keywords", [])
            # 应用每个缺口的关键词数量限制
            limited_keywords = gap_keywords[:MAX_KEYWORDS_PER_GAP]
            keywords.extend(limited_keywords)
        
        return keywords
    
    def _generate_practical_keywords(self, question: str) -> List[str]:
        """
        从问题中生成实用的搜索关键词，使用简化逻辑
        
        Args:
            question: 原始问题
            
        Returns:
            优化后的搜索关键词列表
        """
        # 移除问号和语气词
        cleaned_question = re.sub(r'[？?吗呢啊]', '', question)
        
        # 简化的关键词生成，不使用硬编码模式
        keywords = [cleaned_question]
        
        # 如果没有生成任何关键词，使用原始问题
        if not keywords or not keywords[0].strip():
            keywords = [question]
        
        # 限制关键词数量，去重
        final_keywords = []
        seen = set()
        for kw in keywords[:MAX_WORDS_PER_QUERY]:  # 最多MAX_WORDS_PER_QUERY个关键词
            kw_clean = kw.strip()
            if kw_clean and kw_clean not in seen:
                seen.add(kw_clean)
                final_keywords.append(kw_clean)
        
        return final_keywords or [question]
    
    def _optimize_search_keywords(self, keywords: List[str], original_query: str) -> List[str]:
        """
        优化搜索关键词：长度控制、格式规范化
        来源：intelligent_orchestrator.py 中 _optimize_search_keywords 的逻辑
        
        Args:
            keywords: 原始关键词列表
            original_query: 原始查询（作为回退）
        
        Returns:
            优化后的关键词列表
        """
        optimized_queries = []
        seen_queries = set()
        
        if isinstance(keywords, str):
            keywords = [keywords]
        
        for keyword in keywords:
            if not keyword or not keyword.strip():
                continue
                
            keyword = keyword.strip()
            
            # 如果关键词就是一个完整的查询且不太长，直接使用
            word_count = len(keyword.split())
            if word_count <= self.MAX_WORDS_PER_QUERY:
                query_normalized = keyword.lower()
                if query_normalized not in seen_queries:
                    seen_queries.add(query_normalized)
                    optimized_queries.append(keyword)
                    continue
            
            # 如果太长，尝试截取或重组
            words = keyword.split()
            
            # 方案：截取前5个词
            if word_count > self.MAX_WORDS_PER_QUERY:
                truncated = " ".join(words[:self.MAX_WORDS_PER_QUERY])
                truncated_normalized = truncated.lower()
                if truncated_normalized not in seen_queries:
                    seen_queries.add(truncated_normalized)
                    optimized_queries.append(truncated)
        
        return optimized_queries
    
    def _clean_and_validate_queries(self, queries: List[str], original_topic: str) -> List[str]:
        """
        清理和验证搜索查询
        来源：WebSearchTool._clean_and_validate_queries 的逻辑
        
        Args:
            queries: 待清理的查询列表
            original_topic: 原始主题（用于回退）
        
        Returns:
            清理后的查询列表
        """
        cleaned_queries = []
        seen_queries = set()
        
        for query in queries:
            if not query or not query.strip():
                continue
                
            query = query.strip()
            
            # 简单去重
            query_normalized = query.lower()
            if query_normalized in seen_queries:
                continue
            seen_queries.add(query_normalized)
            
            cleaned_queries.append(query)
        
        # 确保至少包含原始主题
        if not cleaned_queries:
            cleaned_queries.append(original_topic)
        elif original_topic.lower() not in seen_queries:
            # 如果原始主题不在结果中，添加到开头
            cleaned_queries.insert(0, original_topic)
        
        return cleaned_queries
