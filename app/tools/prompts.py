"""
提示模板常量 - 统一管理各种LLM提示模板
"""

# 智能编排器 - 综合答案生成提示模板
SYNTHESIS_SYSTEM_PROMPT = """你是一个专业的问题回答专家，能够综合多种信息源提供准确、完整的答案。"""

SYNTHESIS_USER_PROMPT_TEMPLATE = """基于以下信息，请为用户提供一个完整、准确的回答。

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

请用自然的语言组织回答，不需要返回JSON格式。"""

# 思考引擎 - 独立思考提示模板
REASONING_SYSTEM_PROMPT = """你是一个专业的问题分析专家，擅长深入思考问题并识别知识缺口。请始终返回有效的JSON格式。"""

REASONING_USER_PROMPT_TEMPLATE = """你是一个专业的问题分析专家。请基于你的已有知识独立思考以下问题，并理性评估是否需要外部信息。

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
- 每个知识缺口的搜索关键词最多2个，请大模型自行判断实际需要的数量

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

请确保返回有效的JSON格式。"""

# LLM服务配置 - 默认参数
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_TOKENS = 2000
DEFAULT_LLM_TIMEOUT = 45.0

# 思考引擎配置 - 默认参数
REASONING_TEMPERATURE = 0.2
REASONING_MAX_TOKENS = 2000
REASONING_TIMEOUT = 30.0
