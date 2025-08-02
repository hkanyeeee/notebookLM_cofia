import httpx
from bs4 import BeautifulSoup

async def fetch_html(url: str, timeout: float = 10.0) -> str:
    """使用 httpx 异步获取网页原始 HTML。"""
    async with httpx.AsyncClient(trust_env=True) as client:
        response = await client.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text


def extract_text(html: str) -> str:
    """使用 BeautifulSoup 提取主要文本内容，优先 article 标签，后备 p 标签。"""
    soup = BeautifulSoup(html, "html.parser")
    # 移除不需要的标签
    for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
        tag.decompose()
    # 尝试提取 article 标签中的内容
    article = soup.find("article")
    if article:
        return article.get_text(separator="\n", strip=True)
    # 后备：提取所有 p 标签
    paragraphs = soup.find_all("p")
    return "\n".join(p.get_text(strip=True) for p in paragraphs)