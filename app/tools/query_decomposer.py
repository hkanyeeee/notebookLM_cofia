"""
问题拆解器 - 将复杂问题分解为可处理的子问题
"""
import json
from typing import List, Dict, Any, Optional
from .models import ToolExecutionContext
import httpx
from ..config import LLM_SERVICE_URL, LLM_DEFAULT_TEMPERATURE, LLM_DEFAULT_MAX_TOKENS, LLM_DEFAULT_TIMEOUT


class QueryDecomposer:
    """
    问题拆解器：将复杂问题分解为可处理的子问题
    """
    
    def __init__(self, llm_service_url: str = LLM_SERVICE_URL):
        self.llm_service_url = llm_service_url
        self.decomposition_prompt = """
你是一个专业的问题分析专家。请将用户的问题拆解为合适数量的独立子问题。

用户问题: {query}
问题复杂度: {complexity}

拆解要求:
1. 智能判断问题复杂度和子问题数量：
   - 简单事实类问题（如天气查询、价格查询、定义问答等）：保持为单个问题，无需分解
   - 中等复杂度问题（包含多个概念或需要推理）：分解为最多3个核心子问题
   - 复杂问题（涉及多个维度、需要深入分析或包含连接词如"并且"、"同时"等）：分解为最多5个核心子问题
   - 实时信息查询（涉及当前时间、天气、价格、新闻等）：优先标记为需要外部信息
2. 每个子问题应该是独立且完整的，避免重复或冗余
3. 识别问题的关键信息点和可能需要外部信息验证的部分
4. 评估每个子问题的复杂程度和重要性
5. 自动识别比较类问题并标记相应实体

请返回以下JSON格式:
{{
  "original_query": "{query}",
  "query_type": "事实性|推理性|操作性|混合型",
  "complexity_level": "{complexity}",
  "sub_queries": [
    {{
      "id": 1,
      "question": "子问题1",
      "importance": "高|中|低",
      "requires_external_info": true/false,
      "reasoning": "为什么这个子问题很重要"
    }}
  ],
  "key_entities": ["关键实体1", "关键实体2"],
  "verification_points": ["需要验证的信息点1", "需要验证的信息点2"]
}}

请确保返回的是有效的JSON格式。
"""

    async def decompose(self, query: str, context: Optional[ToolExecutionContext] = None) -> Dict[str, Any]:
        """
        将复杂问题拆解为子问题
        
        Args:
            query: 原始用户问题
            context: 执行上下文（可选）
        
        Returns:
            包含拆解结果的字典
        """
        try:
            # 先分析问题复杂度
            complexity = self.analyze_query_complexity(query)
            
            # 如果是简单问题，直接返回简化的结果，不进行分解
            if complexity == "简单":
                return {
                    "original_query": query,
                    "query_type": "事实性",
                    "complexity_level": "简单",
                    "sub_queries": [
                        {
                            "id": 1,
                            "question": query,
                            "importance": "高",
                            "requires_external_info": True,
                            "reasoning": "简单直接查询，需要获取最新信息"
                        }
                    ],
                    "key_entities": self.extract_key_entities(query),
                    "verification_points": []
                }
            
            # 构建针对复杂问题的提示
            prompt = self.decomposition_prompt.format(query=query, complexity=complexity)
            
            # 调用LLM进行问题拆解
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.llm_service_url}/chat/completions",
                    json={
                        "model": context.run_config.model if context else "qwen2.5:7b",
                        "messages": [
                            {
                                "role": "system", 
                                "content": "你是一个专业的问题分析专家，擅长将复杂问题分解为简单的子问题。请始终返回有效的JSON格式。"
                            },
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": LLM_DEFAULT_TEMPERATURE,
                        "max_tokens": LLM_DEFAULT_MAX_TOKENS
                    },
                    timeout=LLM_DEFAULT_TIMEOUT
                )
                
                if response.status_code != 200:
                    raise Exception(f"LLM请求失败: {response.status_code}")
                
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                
                # 尝试解析JSON
                try:
                    # 清理 markdown 代码块标记
                    cleaned_content = self._clean_json_content(content)
                    decomposition = json.loads(cleaned_content)
                    
                    # 验证必要字段
                    if not all(key in decomposition for key in ["sub_queries", "query_type"]):
                        raise ValueError("缺少必要字段")
                    
                    # 确保sub_queries是列表
                    if not isinstance(decomposition.get("sub_queries"), list):
                        raise ValueError("sub_queries必须是列表")
                    
                    return decomposition
                    
                except json.JSONDecodeError as e:
                    print(f"JSON解析失败: {e}, 原内容: {content}")
                    # 尝试修复截断的JSON
                    try:
                        repaired_content = self._repair_truncated_json(content)
                        if repaired_content:
                            decomposition = json.loads(repaired_content)
                            print(f"JSON修复成功")
                            return decomposition
                    except Exception as repair_e:
                        print(f"JSON修复失败: {repair_e}")
                    
                    # 返回简化的拆解结果
                    return self._create_fallback_decomposition(query)
                    
        except Exception as e:
            print(f"问题拆解失败: {e}")
            return self._create_fallback_decomposition(query)

    def _create_fallback_decomposition(self, query: str) -> Dict[str, Any]:
        """
        创建回退的拆解结果
        """
        return {
            "original_query": query,
            "query_type": "混合型",
            "complexity_level": "中等",
            "sub_queries": [
                {
                    "id": 1,
                    "question": query,
                    "importance": "高",
                    "requires_external_info": True,
                    "reasoning": "原始问题，需要外部信息支持"
                }
            ],
            "key_entities": [],
            "verification_points": ["需要验证问题的相关信息"]
        }

    def analyze_query_complexity(self, query: str) -> str:
        """
        分析问题复杂程度 - 通过 LLM 智能判断
        
        Returns:
            "简单"|"中等"|"复杂"
        """
        # 简化的启发式规则，主要基于长度和结构
        word_count = len(query.split())
        question_marks = query.count('?') + query.count('？')
        
        # 基本的复杂度评估
        if word_count <= 8 and question_marks <= 1:
            return "简单"
        elif word_count > 25 or question_marks > 1:
            return "复杂"
        else:
            return "中等"

    def should_use_fast_route(self, query: str) -> bool:
        """
        判断是否应该使用快速路由（跳过复杂分解）
        
        Args:
            query: 用户问题
            
        Returns:
            是否使用快速路由
        """
        # 使用统一的复杂度分析
        complexity = self.analyze_query_complexity(query)
        
        # 只有简单问题才使用快速路由
        return complexity == "简单"

    def extract_key_entities(self, query: str) -> List[str]:
        """
        提取问题中的关键实体（简单实现）
        """
        # 这里可以使用更复杂的NER，目前使用简单的关键词提取
        import re
        
        # 提取可能的实体词
        entities = []
        
        # 提取引号中的内容
        quoted_text = re.findall(r'"([^"]*)"', query)
        entities.extend(quoted_text)
        
        # 提取可能的专有名词（大写开头的词）
        proper_nouns = re.findall(r'\b[A-Z][a-z]+\b', query)
        entities.extend(proper_nouns)
        
        # 去重并返回
        return list(set(entities))
    
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
