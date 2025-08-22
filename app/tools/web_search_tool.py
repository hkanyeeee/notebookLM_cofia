"""Web 搜索工具 - 整合关键词生成、SearxNG 搜索、网页爬取、embedding、向量召回和 rerank"""

import asyncio
import json
import uuid
from typing import List, Dict, Any, Optional, Tuple
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import (
    LLM_SERVICE_URL, SEARXNG_QUERY_URL,
    WEB_SEARCH_RESULT_COUNT, WEB_SEARCH_MAX_QUERIES, WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_CONCURRENT_REQUESTS, WEB_SEARCH_TIMEOUT,
    WEB_LOADER_ENGINE, PLAYWRIGHT_TIMEOUT,
    ENABLE_QUERY_GENERATION, QUERY_GENERATION_PROMPT_TEMPLATE,
    CHUNK_SIZE, CHUNK_OVERLAP, RAG_TOP_K, RAG_RERANK_TOP_K
)
# 移除模块级别的导入，避免循环导入
# from ..llm_client import DEFAULT_CHAT_MODEL
from ..fetch_parse import fetch_then_extract, fetch_rendered_text
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..vector_db_client import add_embeddings, query_hybrid
from ..rerank_client import rerank
from ..models import Chunk, Source
from ..database import AsyncSessionLocal


class WebSearchTool:
    """Web 搜索工具，整合了完整的搜索-爬取-索引-召回流程"""
    
    def __init__(self):
        self.name = "web_search"
        self.description = "搜索网络信息，爬取相关网页内容，并进行向量化索引和智能召回"
    
    async def generate_search_queries(self, topic: str, model: str = None) -> List[str]:
        """生成搜索关键词"""
        if not ENABLE_QUERY_GENERATION or not topic.strip():
            return [topic]
        
        # 使用传入的模型或默认模型（在函数内部导入，避免循环导入）
        if model is None:
            from ..llm_client import DEFAULT_CHAT_MODEL
            model = DEFAULT_CHAT_MODEL
        
        prompt_system = QUERY_GENERATION_PROMPT_TEMPLATE
        user_prompt = f"课题：{topic}\n请直接给出 JSON，如：{{'queries': ['...', '...', '...']}}"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{LLM_SERVICE_URL}/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                
                # 尝试解析 JSON
                try:
                    import re
                    
                    # 去掉可能的代码块包裹
                    content_stripped = content.strip()
                    if content_stripped.startswith("```"):
                        content_stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content_stripped)
                    
                    # 提取 JSON 对象
                    m = re.search(r"\{[\s\S]*\}", content_stripped)
                    json_candidate = m.group(0) if m else content_stripped
                    
                    parsed = json.loads(json_candidate)
                    queries = parsed.get("queries") or parsed.get("Queries")
                    if isinstance(queries, list):
                        queries = [str(q).strip() for q in queries if str(q).strip()][:WEB_SEARCH_MAX_QUERIES]
                        if queries:
                            # 填满 3 个
                            while len(queries) < WEB_SEARCH_MAX_QUERIES:
                                queries.append(topic)
                            return queries[:WEB_SEARCH_MAX_QUERIES]
                except Exception:
                    pass
                
                # 兜底策略
                return [topic, f"{topic} 相关", f"{topic} 详细信息"][:WEB_SEARCH_MAX_QUERIES]
                
        except Exception as e:
            print(f"生成搜索关键词失败: {e}")
            return [topic]
    
    async def search_searxng(
        self, 
        query: str, 
        language: str = "en-US",
        categories: str = ""
    ) -> List[Dict[str, str]]:
        """使用 SearxNG 搜索"""
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "safesearch": "1",
            "language": language,
            "time_range": "",
            "categories": categories,
            "theme": "simple",
            "image_proxy": 0,
        }
        
        headers = {
            "User-Agent": "notebookLM_cofia RAG Bot",
            "Accept": "text/html",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(SEARXNG_QUERY_URL, params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                results = payload.get("results", [])
                
                # 按 score 降序排列并限制数量
                results_sorted = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
                items = []
                for r in results_sorted[:WEB_SEARCH_RESULT_COUNT]:
                    title = r.get("title") or r.get("name") or "Untitled"
                    url = r.get("url") or r.get("link")
                    snippet = r.get("content") or r.get("snippet") or ""
                    if url:
                        items.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet
                        })
                return items
        except Exception as e:
            print(f"SearxNG 搜索失败: {e}")
            return []
    
    async def fetch_web_content(self, url: str) -> Optional[str]:
        """爬取网页内容"""
        try:
            if WEB_LOADER_ENGINE == "playwright":
                # 使用 Playwright 渲染模式
                content = await fetch_rendered_text(
                    url, 
                    selector="article",
                    timeout=PLAYWRIGHT_TIMEOUT
                )
            else:
                # 使用安全模式（httpx + BeautifulSoup，失败后回退到 Playwright）
                content = await fetch_then_extract(
                    url, 
                    selector="article", 
                    timeout=WEB_SEARCH_TIMEOUT
                )
            
            # 限制内容长度
            # if content and len(content) > WEB_SEARCH_MAX_CONTENT_LENGTH:
            #     content = content[:WEB_SEARCH_MAX_CONTENT_LENGTH] + "..."
            
            return content
        except Exception as e:
            print(f"爬取网页内容失败 {url}: {e}")
            return None
    
    async def process_documents(
        self, 
        documents: List[Dict[str, str]], 
        session_id: str
    ) -> List[int]:
        """处理文档：切分、embedding、存储到向量数据库"""
        if not documents:
            return []
        
        # 使用数据库会话
        async with AsyncSessionLocal() as db:
            source_ids = []
            all_chunks = []
            all_embeddings_flat = []
            
            # 用于确保 chunk_id 在整个 session 中唯一的全局计数器
            global_chunk_index = 0
            
            for doc in documents:
                url = doc["url"]
                title = doc["title"]
                content = doc.get("content", "")
                
                if not content:
                    continue
                
                # 创建 Source 记录
                source = Source(
                    session_id=session_id,
                    url=url,
                    title=title
                )
                db.add(source)
                await db.commit()
                await db.refresh(source)
                source_ids.append(source.id)
                
                # 文档切分
                chunks_text = chunk_text(
                    content,
                    tokens_per_chunk=CHUNK_SIZE,
                    overlap_tokens=CHUNK_OVERLAP
                )
                
                # 创建 Chunk 记录
                chunks = []
                # 使用全局计数器确保chunk_id在整个session中唯一
                for chunk_content in chunks_text:
                    # 生成基于session_id和全局索引的唯一chunk_id
                    chunk_id = f"{session_id}_{global_chunk_index}"
                    chunk = Chunk(
                        content=chunk_content,
                        source_id=source.id,
                        session_id=session_id,
                        chunk_id=chunk_id
                    )
                    chunks.append(chunk)
                    global_chunk_index += 1
                
                db.add_all(chunks)
                await db.commit()
                
                # 刷新以获取 ID 并确保chunks在session中
                for chunk in chunks:
                    await db.refresh(chunk)
                    # 确保source关系正确加载
                    if not chunk.source:
                        chunk.source = source
                
                all_chunks.extend(chunks)
                
                # 计算 embeddings
                chunk_texts = [chunk.content for chunk in chunks]
                embeddings = await embed_texts(
                    chunk_texts,
                    model=DEFAULT_EMBEDDING_MODEL,
                    batch_size=2
                )
                all_embeddings_flat.extend(embeddings)
            
            # 批量存储到向量数据库
            if all_chunks and all_embeddings_flat:
                # 按 source 分组存储
                chunk_idx = 0
                for source_id in source_ids:
                    source_chunks = [c for c in all_chunks if c.source_id == source_id]
                    if source_chunks:
                        source_embeddings = all_embeddings_flat[chunk_idx:chunk_idx + len(source_chunks)]
                        await add_embeddings(source_id, source_chunks, source_embeddings)
                        chunk_idx += len(source_chunks)
            
            return source_ids
    
    async def search_and_retrieve(
        self, 
        query: str, 
        session_id: str,
        source_ids: Optional[List[int]] = None
    ) -> List[Tuple[Chunk, float]]:
        """搜索和召回相关内容"""
        # 计算查询的 embedding
        query_embeddings = await embed_texts([query], model=DEFAULT_EMBEDDING_MODEL)
        query_embedding = query_embeddings[0]
        
        # 使用数据库会话进行混合检索
        async with AsyncSessionLocal() as db:
            # 混合检索（向量 + BM25）
            hits = await query_hybrid(
                query_text=query,
                query_embedding=query_embedding,
                top_k=RAG_TOP_K,
                session_id=session_id,
                source_ids=source_ids,
                db=db
            )
            
            # Rerank（如果配置了）
            if hits and len(hits) > RAG_RERANK_TOP_K:
                try:
                    reranked_hits = await rerank(query, hits[:RAG_TOP_K])
                    # 取 top-k
                    hits = sorted(reranked_hits, key=lambda x: x[1], reverse=True)[:RAG_RERANK_TOP_K]
                except Exception as e:
                    print(f"Rerank 失败，使用原始结果: {e}")
                    hits = hits[:RAG_RERANK_TOP_K]
            
            return hits
    
    async def execute(
        self, 
        query: str,
        language: str = "en-US",
        categories: str = "",
        filter_list: Optional[List[str]] = None,
        model: str = None
    ) -> Dict[str, Any]:
        """执行完整的 Web 搜索流程
        
        Args:
            query: 搜索查询
            language: 语言过滤器，默认为 "en-US"
            categories: 搜索类别列表，默认为 ""
            filter_list: 域名过滤列表，用于过滤搜索结果
            model: 用于关键词生成的LLM模型名称，默认使用系统配置
            
        Returns:
            包含搜索结果和召回内容的字典
        """
        # 内部自动生成会话ID
        session_id = str(uuid.uuid4())
        
        result = {
            "session_id": session_id,
            "query": query,
            "search_results": [],
            "retrieved_content": [],
            "source_ids": [],
            "success": True,
            "message": ""
        }
        
        try:
            # 1. 生成搜索关键词
            queries = await self.generate_search_queries(query, model)
            print(f"生成的搜索关键词: {queries}")
            
            # 2. 并发搜索
            search_tasks = [self.search_searxng(q, language, categories) for q in queries]
            search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # 合并搜索结果并去重
            all_results = []
            seen_urls = set()
            for results in search_results_list:
                if isinstance(results, list):
                    for item in results:
                        url = item.get("url")
                        if url and url not in seen_urls:
                            # 应用域名过滤
                            if filter_list:
                                from urllib.parse import urlparse
                                domain = urlparse(url).netloc
                                # 如果域名在过滤列表中，则跳过
                                if any(filter_domain in domain for filter_domain in filter_list):
                                    continue
                            seen_urls.add(url)
                            all_results.append(item)
            
            # 限制结果数量
            all_results = all_results[:WEB_SEARCH_MAX_RESULTS]
            print(f"找到 {len(all_results)} 个搜索结果")
            
            if all_results:
                # 3. 并发爬取网页内容
                content_tasks = []
                for item in all_results[:WEB_SEARCH_CONCURRENT_REQUESTS]:
                    content_tasks.append(self.fetch_web_content(item["url"]))
                
                # 处理剩余的 URL（分批）
                remaining_urls = all_results[WEB_SEARCH_CONCURRENT_REQUESTS:]
                contents = await asyncio.gather(*content_tasks, return_exceptions=True)
                
                # 处理剩余的批次
                for i in range(0, len(remaining_urls), WEB_SEARCH_CONCURRENT_REQUESTS):
                    batch = remaining_urls[i:i + WEB_SEARCH_CONCURRENT_REQUESTS]
                    batch_tasks = [self.fetch_web_content(item["url"]) for item in batch]
                    batch_contents = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    contents.extend(batch_contents)
                
                # 组装文档
                documents = []
                for item, content in zip(all_results, contents):
                    if isinstance(content, str) and content:
                        documents.append({
                            "url": item["url"],
                            "title": item["title"],
                            "content": content,
                            "snippet": item.get("snippet", "")
                        })
                
                print(f"成功爬取 {len(documents)} 个网页")
                result["search_results"] = documents
                
                if documents:
                    # 4. 处理文档（切分、embedding、存储）
                    source_ids = await self.process_documents(documents, session_id)
                    result["source_ids"] = source_ids
                    print(f"处理了 {len(source_ids)} 个文档源")
            
            # 5. 搜索和召回
            if result["source_ids"]:
                hits = await self.search_and_retrieve(
                    query, 
                    session_id, 
                    source_ids=result["source_ids"]
                )
                
                # 格式化召回内容
                retrieved_content = []
                for chunk, score in hits:
                    retrieved_content.append({
                        "content": chunk.content,
                        "score": float(score),
                        "source_url": chunk.source.url if chunk.source else "",
                        "source_title": chunk.source.title if chunk.source else "",
                        "chunk_id": chunk.chunk_id
                    })
                
                result["retrieved_content"] = retrieved_content
                print(f"召回了 {len(retrieved_content)} 个相关内容片段")
                
                if retrieved_content:
                    result["message"] = f"搜索完成，找到 {len(result['search_results'])} 个网页，召回 {len(retrieved_content)} 个相关内容片段"
                else:
                    result["message"] = "搜索完成，但没有找到相关内容"
            else:
                result["message"] = "没有找到可用的搜索结果"
                
        except Exception as e:
            result["success"] = False
            result["message"] = f"Web 搜索执行失败: {str(e)}"
            print(f"Web 搜索工具执行错误: {e}")
        
        return result


# 工具实例
web_search_tool = WebSearchTool()


# 工具函数（供注册表使用）
async def web_search(
    query: str,
    language: str = "en-US",
    categories: str = "",
    filter_list: Optional[List[str]] = None,
    model: str = None,
    **kwargs  # 接受额外的参数用于向后兼容
) -> str:
    """Web 搜索工具函数
    
    Args:
        query: 搜索查询内容
        language: 语言过滤器，默认为 "en-US"
        categories: 搜索类别列表，默认为 ""
        filter_list: 域名过滤列表，用于过滤搜索结果
        model: 用于关键词生成的LLM模型名称，默认使用系统配置
        **kwargs: 额外参数（用于向后兼容）
    
    Returns:
        搜索和召回结果的 JSON 字符串
    """
    print(f"[WebSearch] 工具函数被调用，参数: query={query}, language={language}, categories={categories}, filter_list={filter_list}, model={model}, kwargs={kwargs}")
    
    # 处理向后兼容的参数名映射
    if "source" in kwargs and not categories:
        categories = kwargs["source"]
        print(f"[WebSearch] 映射source参数到categories: {categories}")
    
    if "topn" in kwargs:
        # topn参数目前没有直接映射，可以记录日志或忽略
        print(f"[WebSearch] 注意：topn参数 ({kwargs['topn']}) 当前未使用")
    
    result = await web_search_tool.execute(query, language, categories, filter_list, model)
    
    # 构建返回的摘要信息
    if result["success"]:
        summary = {
            "message": result["message"],
            "search_count": len(result["search_results"]),
            "retrieved_count": len(result["retrieved_content"]),
            "top_results": []
        }
        
        # 添加前几个最相关的内容片段
        for item in result["retrieved_content"][:3]:
            summary["top_results"].append({
                "content_preview": item["content"][:200] + "..." if len(item["content"]) > 200 else item["content"],
                "score": item["score"],
                "source": item["source_title"] or item["source_url"]
            })
        
        return json.dumps(summary, ensure_ascii=False, indent=2)
    else:
        return json.dumps({
            "success": False,
            "error": result["message"]
        }, ensure_ascii=False)
