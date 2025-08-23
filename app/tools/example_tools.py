"""使用装饰器的示例工具"""
from typing import List, Optional
from .decorators import tool, batch_tool, quick_metadata


# 使用简单装饰器注册工具
@tool(description="计算两个数字的和")
def add_numbers(a: float, b: float) -> float:
    """计算两个数字的和"""
    return a + b


# 使用带元数据的装饰器
@tool(
    description="生成指定长度的随机字符串", 
    metadata=quick_metadata(timeout=30.0, cache_ttl=300.0)
)
def generate_random_string(length: int = 10, charset: str = "abcdefghijklmnopqrstuvwxyz") -> str:
    """生成随机字符串"""
    import random
    return ''.join(random.choice(charset) for _ in range(length))


# 使用装饰器注册列表参数的工具
@tool(description="计算数字列表的统计信息")
def calculate_stats(numbers: List[float]) -> dict:
    """计算数字列表的统计信息"""
    if not numbers:
        return {"error": "空列表"}
    
    return {
        "count": len(numbers),
        "sum": sum(numbers),
        "average": sum(numbers) / len(numbers),
        "min": min(numbers),
        "max": max(numbers)
    }


# 使用批量装饰器注册多个工具
@batch_tool(
    ("format_text", "格式化文本", quick_metadata(timeout=10.0)),
    ("reverse_text", "反转文本", quick_metadata(timeout=5.0)),
    ("count_words", "统计单词数", quick_metadata(timeout=5.0))
)
class TextTools:
    """文本处理工具集合"""
    
    def format_text(self, text: str, format_type: str = "upper") -> str:
        """格式化文本"""
        if format_type == "upper":
            return text.upper()
        elif format_type == "lower":
            return text.lower()
        elif format_type == "title":
            return text.title()
        else:
            return text
    
    def reverse_text(self, text: str) -> str:
        """反转文本"""
        return text[::-1]
    
    def count_words(self, text: str) -> int:
        """统计单词数"""
        return len(text.split())


# 异步工具示例
@tool(
    description="异步获取URL内容",
    metadata=quick_metadata(timeout=60.0, retries=2)
)
async def fetch_url(url: str, timeout: Optional[float] = None) -> str:
    """异步获取URL内容"""
    import httpx
    
    timeout_value = timeout or 30.0
    
    async with httpx.AsyncClient(timeout=timeout_value) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text[:1000]  # 限制返回内容长度
        except Exception as e:
            return f"获取失败: {str(e)}"


# 带有复杂参数的工具
@tool(description="搜索和过滤数据")
def search_and_filter(
    query: str,
    filters: Optional[dict] = None,
    sort_by: str = "relevance",
    limit: int = 10,
    include_metadata: bool = False
) -> dict:
    """搜索和过滤数据"""
    results = {
        "query": query,
        "filters": filters or {},
        "sort_by": sort_by,
        "limit": limit,
        "results": [
            {"id": i, "title": f"结果 {i}", "relevance": 0.9 - i * 0.1}
            for i in range(min(limit, 5))
        ]
    }
    
    if include_metadata:
        results["metadata"] = {
            "total_found": 100,
            "search_time_ms": 25.5,
            "version": "1.0"
        }
    
    return results
