"""
思考引擎 - 基于已有知识独立思考问题
"""
import json
from typing import List, Dict, Any, Optional
from .models import ToolExecutionContext
import httpx
from ..config import LLM_SERVICE_URL


class ReasoningEngine:
    """
    思考引擎：基于已有知识独立思考每个子问题
    """
    
    def __init__(self, llm_service_url: str = LLM_SERVICE_URL):
        self.llm_service_url = llm_service_url
        self.reasoning_prompt = """
你是一个专业的问题分析专家。请基于你的已有知识独立思考以下问题，并理性评估是否需要外部信息。

问题: {question}
上下文信息: {context}

思考指导：
- 对于简单的事实查询（如天气、时间、价格等），通常需要最新的外部信息
- 对于复杂的分析、推理问题，可能需要多方面的知识支撑
- 只有在确实需要实时、准确、具体数据时才标记为高重要性知识缺口
- 避免为了信息完整性而过度标记知识缺口

搜索关键词生成指导：
- 使用简单直接的词语，避免过于技术化的术语
- 保持原语言（中文问题用中文关键词），便于本地化搜索
- 关键词应该是普通用户会搜索的自然语言
- 避免生成过长或过于复杂的搜索词组
- 每个关键词应该是完整且有意义的搜索查询

请进行深入思考并返回以下JSON格式:
{{
  "question": "{question}",
  "thought_process": "你的详细思考过程，包括你知道的相关信息",
  "preliminary_answer": "基于现有知识的初步回答",
  "confidence_level": "高|中|低",
  "knowledge_gaps": [
    {{
      "gap_description": "具体的知识缺口描述",
      "importance": "高|中|低",
      "search_keywords": ["简单直接的搜索关键词，使用自然语言，便于普通用户理解和搜索"]
    }}
  ],
  "reasoning_steps": [
    "思考步骤1",
    "思考步骤2"
  ],
  "assumptions": ["假设1", "假设2"],
  "needs_verification": true/false
}}

请确保返回有效的JSON格式。
"""

    async def think_independently(
        self, 
        question: str, 
        context: List[str] = None,
        execution_context: Optional[ToolExecutionContext] = None
    ) -> Dict[str, Any]:
        """
        对单个问题进行独立思考
        
        Args:
            question: 要思考的问题
            context: 相关上下文信息
            execution_context: 执行上下文
        
        Returns:
            思考结果字典
        """
        try:
            # 准备上下文信息
            context_str = "\n".join(context) if context else "无特定上下文"
            
            # 构建提示
            prompt = self.reasoning_prompt.format(
                question=question,
                context=context_str
            )
            
            # 调用LLM进行思考
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.llm_service_url}/chat/completions",
                    json={
                        "model": execution_context.run_config.model if execution_context else "qwen2.5:7b",
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是一个专业的问题分析专家，擅长深入思考问题并识别知识缺口。请始终返回有效的JSON格式。"
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 2000
                    },
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    raise Exception(f"LLM请求失败: {response.status_code}")
                
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                # 尝试解析JSON
                try:
                    # 清理 markdown 代码块标记
                    cleaned_content = self._clean_json_content(content)
                    thinking_result = json.loads(cleaned_content)
                    
                    # 验证必要字段
                    required_fields = ["thought_process", "confidence_level", "knowledge_gaps"]
                    if not all(key in thinking_result for key in required_fields):
                        raise ValueError("缺少必要字段")
                    
                    return thinking_result
                    
                except json.JSONDecodeError as e:
                    print(f"JSON解析失败: {e}, 原内容: {content}")
                    # 尝试修复截断的JSON
                    try:
                        repaired_content = self._repair_truncated_json(content)
                        if repaired_content:
                            thinking_result = json.loads(repaired_content)
                            print(f"JSON修复成功")
                            return thinking_result
                    except Exception as repair_e:
                        print(f"JSON修复失败: {repair_e}")
                    
                    return self._create_fallback_thinking(question, context_str)
                    
        except Exception as e:
            print(f"独立思考失败: {e}")
            return self._create_fallback_thinking(question, context or [])

    async def think_about_decomposition(
        self, 
        decomposition: Dict[str, Any], 
        context: List[str] = None,
        execution_context: Optional[ToolExecutionContext] = None
    ) -> List[Dict[str, Any]]:
        """
        对拆解后的多个子问题进行思考
        
        Args:
            decomposition: 问题拆解结果
            context: 相关上下文
            execution_context: 执行上下文
        
        Returns:
            每个子问题的思考结果列表
        """
        thoughts = []
        
        sub_queries = decomposition.get("sub_queries", [])
        for sub_query in sub_queries:
            if isinstance(sub_query, dict):
                question = sub_query.get("question", "")
            else:
                question = str(sub_query)
            
            if question:
                thought = await self.think_independently(
                    question, 
                    context, 
                    execution_context
                )
                thought["sub_query_id"] = sub_query.get("id") if isinstance(sub_query, dict) else None
                thoughts.append(thought)
        
        return thoughts

    def _create_fallback_thinking(self, question: str, context: Any) -> Dict[str, Any]:
        """
        创建回退的思考结果
        """
        # 分析问题类型，决定知识缺口重要性
        import re
        
        # 简单的实时查询模式
        realtime_patterns = [
            r'(今天|现在|当前|目前).*(天气|气温|温度)',
            r'.*天气.*如何',
            r'.*价格.*多少',
            r'.*股价|股票.*价格',
            r'.*(时间|几点).*什么时候'
        ]
        
        is_realtime_query = any(re.search(pattern, question) for pattern in realtime_patterns)
        
        # 根据问题类型设置不同的知识缺口重要性
        gap_importance = "高" if is_realtime_query else "中"
        
        # 智能生成搜索关键词
        search_keywords = self._generate_practical_keywords(question)
        
        return {
            "question": question,
            "thought_process": f"对于问题'{question}'，需要获取最新信息来提供准确答案。" if is_realtime_query else f"对于问题'{question}'，可能需要一些额外信息来完善回答。",
            "preliminary_answer": "需要获取最新信息才能回答" if is_realtime_query else "基于现有知识可以部分回答，但需要验证具体细节",
            "confidence_level": "低" if is_realtime_query else "中",
            "knowledge_gaps": [
                {
                    "gap_description": f"关于'{question}'的最新具体信息" if is_realtime_query else f"关于'{question}'的详细信息",
                    "importance": gap_importance,
                    "search_keywords": search_keywords
                }
            ],
            "reasoning_steps": [
                "分析问题类型",
                "评估信息需求", 
                "确定所需外部信息的重要性"
            ],
            "assumptions": [],
            "needs_verification": is_realtime_query
        }

    def assess_overall_confidence(self, thoughts: List[Dict[str, Any]]) -> str:
        """
        评估整体置信度
        
        Args:
            thoughts: 所有子问题的思考结果
        
        Returns:
            整体置信度 "高"|"中"|"低"
        """
        if not thoughts:
            return "低"
        
        confidence_levels = [thought.get("confidence_level", "低") for thought in thoughts]
        
        # 统计置信度分布
        high_count = confidence_levels.count("高")
        medium_count = confidence_levels.count("中")
        low_count = confidence_levels.count("低")
        
        total = len(confidence_levels)
        
        # 基于分布决定整体置信度
        if high_count / total >= 0.7:
            return "高"
        elif (high_count + medium_count) / total >= 0.6:
            return "中"
        else:
            return "低"

    def extract_all_knowledge_gaps(self, thoughts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        提取所有思考结果中的知识缺口
        
        Args:
            thoughts: 所有子问题的思考结果
        
        Returns:
            合并和去重后的知识缺口列表
        """
        all_gaps = []
        seen_descriptions = set()
        
        for thought in thoughts:
            gaps = thought.get("knowledge_gaps", [])
            for gap in gaps:
                gap_desc = gap.get("gap_description", "")
                if gap_desc and gap_desc not in seen_descriptions:
                    seen_descriptions.add(gap_desc)
                    all_gaps.append(gap)
        
        # 按重要性排序
        importance_order = {"高": 3, "中": 2, "低": 1}
        all_gaps.sort(
            key=lambda x: importance_order.get(x.get("importance", "低"), 1),
            reverse=True
        )
        
        return all_gaps

    def generate_preliminary_answer(self, thoughts: List[Dict[str, Any]]) -> str:
        """
        基于所有思考结果生成初步答案
        
        Args:
            thoughts: 所有子问题的思考结果
        
        Returns:
            合并的初步答案
        """
        if not thoughts:
            return "无法基于当前信息提供答案。"
        
        answers = []
        for i, thought in enumerate(thoughts, 1):
            preliminary = thought.get("preliminary_answer", "")
            if preliminary and preliminary != "需要更多信息才能回答":
                answers.append(f"{i}. {preliminary}")
        
        if not answers:
            return "需要更多外部信息才能提供完整答案。"
        
        return "\n".join(answers)

    def _clean_json_content(self, content: str) -> str:
        """
        清理 LLM 返回内容中的 markdown 代码块标记
        
        Args:
            content: 原始内容
        
        Returns:
            清理后的 JSON 字符串
        """
        # 去除开头和结尾的空白字符
        content = content.strip()
        
        # 移除 markdown 代码块标记
        if content.startswith("```json"):
            content = content[7:]  # 移除 "```json"
        elif content.startswith("```"):
            content = content[3:]   # 移除 "```"
        
        if content.endswith("```"):
            content = content[:-3]  # 移除结尾的 "```"
        
        # 再次去除空白字符
        return content.strip()
    
    def _repair_truncated_json(self, content: str) -> str:
        """
        尝试修复被截断的JSON内容
        
        Args:
            content: 原始内容
        
        Returns:
            修复后的JSON字符串，如果无法修复则返回None
        """
        try:
            # 清理内容
            cleaned_content = self._clean_json_content(content)
            
            # 检查是否是未完成的JSON
            if not cleaned_content.strip().endswith('}'):
                # 尝试找到最后一个完整的字段
                lines = cleaned_content.split('\n')
                valid_lines = []
                open_braces = 0
                open_quotes = False
                
                for line in lines:
                    # 简单的状态跟踪
                    for char in line:
                        if char == '"' and (not valid_lines or valid_lines[-1][-1] != '\\'):
                            open_quotes = not open_quotes
                        elif not open_quotes:
                            if char == '{':
                                open_braces += 1
                            elif char == '}':
                                open_braces -= 1
                    
                    # 如果这一行结束时处于安全状态，则保留
                    if not open_quotes and (line.strip().endswith(',') or line.strip().endswith('}') or line.strip().endswith('{')):
                        valid_lines.append(line)
                    elif not open_quotes and not line.strip():
                        valid_lines.append(line)  # 保留空行
                    elif open_quotes:
                        # 如果在引号内被截断，尝试补完
                        if line.strip().endswith('",'):
                            valid_lines.append(line)
                        else:
                            # 尝试补完这个字段
                            fixed_line = line.strip()
                            if not fixed_line.endswith('"'):
                                fixed_line += '"'
                            if not fixed_line.endswith(','):
                                fixed_line += ','
                            valid_lines.append('  ' + fixed_line)
                            break
                    else:
                        valid_lines.append(line)
                
                # 确保JSON结构完整
                reconstructed = '\n'.join(valid_lines)
                
                # 补完缺失的结构
                while open_braces > 0:
                    reconstructed += '\n}'
                    open_braces -= 1
                
                return reconstructed
            
            return cleaned_content
            
        except Exception as e:
            print(f"修复JSON时出错: {e}")
            return None

    def _generate_practical_keywords(self, question: str) -> List[str]:
        """
        智能生成更实用的搜索关键词
        
        Args:
            question: 原始问题
            
        Returns:
            优化后的搜索关键词列表
        """
        import re
        
        # 移除问号和语气词
        cleaned_question = re.sub(r'[？?吗呢啊]', '', question)
        
        # 常见的比较词汇和连接词，需要保留
        comparison_words = ['对比', '比较', '和', '与', 'vs', '哪个', '更']
        performance_words = ['性能', '快', '慢', '强', '弱', '好', '差', '优', '劣']
        
        keywords = []
        
        # 如果是比较类问题，生成针对性的关键词
        if any(word in question for word in comparison_words):
            # 提取主要产品/实体
            entities = []
            # 匹配 M4 Pro, M2 Max 等产品名
            product_pattern = r'[A-Za-z0-9]+\s*[A-Za-z0-9]*(?:\s*[Pp]ro|[Mm]ax|[Aa]ir|[Mm]ini)?'
            products = re.findall(product_pattern, question)
            
            # 匹配中文产品名
            chinese_entities = re.findall(r'苹果|小米|华为|联想|戴尔|惠普|[A-Za-z]+', question)
            
            entities.extend(products)
            entities.extend(chinese_entities)
            
            # 去重并过滤
            unique_entities = []
            seen = set()
            for entity in entities:
                entity_clean = entity.strip()
                if entity_clean and entity_clean.lower() not in seen and len(entity_clean) > 1:
                    seen.add(entity_clean.lower())
                    unique_entities.append(entity_clean)
            
            # 生成具体的搜索词
            if len(unique_entities) >= 2:
                # 对比类搜索词
                keywords.append(f"{unique_entities[0]} {unique_entities[1]} 对比")
                keywords.append(f"{unique_entities[0]} vs {unique_entities[1]}")
                
                # 如果涉及性能问题，加上性能关键词
                if any(word in question for word in performance_words + ['推理', '运算', '处理']):
                    keywords.append(f"{unique_entities[0]} {unique_entities[1]} 性能测试")
                    
                    # 针对大模型推理的特殊处理
                    if '大模型' in question or '推理' in question:
                        keywords.append(f"{unique_entities[0]} {unique_entities[1]} AI性能")
            else:
                # 如果没有提取到足够的实体，使用简化的关键词
                keywords.append(cleaned_question)
        else:
            # 非比较类问题，使用原始问题的简化版本
            keywords.append(cleaned_question)
            
            # 提取核心概念
            core_concepts = []
            if '天气' in question:
                core_concepts.append('天气预报')
            if '价格' in question:
                core_concepts.append('价格查询')
            if '时间' in question:
                core_concepts.append('当前时间')
                
            keywords.extend(core_concepts)
        
        # 如果没有生成任何关键词，使用原始问题
        if not keywords:
            keywords.append(question)
        
        # 限制关键词数量，去重
        final_keywords = []
        seen = set()
        for kw in keywords[:3]:  # 最多3个关键词
            kw_clean = kw.strip()
            if kw_clean and kw_clean not in seen:
                seen.add(kw_clean)
                final_keywords.append(kw_clean)
        
        return final_keywords or [question]
