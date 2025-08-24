"""Web 搜索工具 - 整合关键词生成、SearxNG 搜索、网页爬取、embedding、向量召回和 rerank"""

import asyncio
import json
import uuid
import time
import re
from typing import List, Dict, Any, Optional, Tuple
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from difflib import SequenceMatcher

from ..config import (
    EMBEDDING_BATCH_SIZE, LLM_SERVICE_URL, SEARXNG_QUERY_URL,
    WEB_SEARCH_RESULT_COUNT, WEB_SEARCH_MAX_QUERIES, WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_CONCURRENT_REQUESTS, WEB_SEARCH_TIMEOUT,
    WEB_LOADER_ENGINE, PLAYWRIGHT_TIMEOUT,
    ENABLE_QUERY_GENERATION, QUERY_GENERATION_PROMPT_TEMPLATE,
    CHUNK_SIZE, CHUNK_OVERLAP, RAG_TOP_K, RAG_RERANK_TOP_K,
    WEB_CACHE_ENABLED, WEB_CACHE_MAX_SIZE, WEB_CACHE_TTL_SECONDS, WEB_CACHE_MAX_CONTENT_SIZE,
    LLM_DEFAULT_TEMPERATURE, WEB_SEARCH_LLM_TIMEOUT
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
from ..cache import get_web_content_cache


class WebSearchTool:
    """Web 搜索工具，整合了完整的搜索-爬取-索引-召回流程"""
    
    def __init__(self):
        self.name = "web_search"
        self.description = "搜索网络信息，爬取相关网页内容，并进行向量化索引和智能召回"
        
        # 初始化缓存（如果启用）
        if WEB_CACHE_ENABLED:
            self.cache = get_web_content_cache()
            # 更新缓存配置
            self.cache.max_cache_size = WEB_CACHE_MAX_SIZE
            self.cache.default_ttl = WEB_CACHE_TTL_SECONDS
            self.cache.max_content_size = WEB_CACHE_MAX_CONTENT_SIZE
            print(f"[WebSearch] 缓存已启用 (max_size={WEB_CACHE_MAX_SIZE}, ttl={WEB_CACHE_TTL_SECONDS}s)")
        else:
            self.cache = None
            print("[WebSearch] 缓存已禁用")
        
        # 搜索结果缓存和去重
        self.search_result_cache = {}  # 基于查询fingerprint的搜索结果缓存
        self.executed_queries = set()  # 已执行的查询fingerprint集合

    def _normalize_query(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        s = text.strip().lower()
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"[\u3000\s\t\r\n\-_,.;:!?，。；：！？""\"'`（）()\\\[\\\]{}]", "", s)
        return s

    def _generate_search_fingerprint(self, queries: List[str], language: str = "en-US", categories: str = "") -> str:
        """生成搜索查询的fingerprint，用于去重和缓存"""
        normalized_queries = sorted([self._normalize_query(q) for q in queries if q.strip()])
        params_str = f"lang:{language}|cat:{categories}"
        fingerprint = f"queries:{'|'.join(normalized_queries)}|{params_str}"
        return fingerprint
    
    def _similarity_check(self, fp1: str, fp2: str) -> float:
        """检查两个fingerprint的相似度 (0-1)"""
        # 提取查询部分
        try:
            queries1 = set(fp1.split('|')[0].replace('queries:', '').split('|'))
            queries2 = set(fp2.split('|')[0].replace('queries:', '').split('|'))
            
            if not queries1 or not queries2:
                return 0.0
            
            # 计算Jaccard相似度
            intersection = len(queries1.intersection(queries2))
            union = len(queries1.union(queries2))
            return intersection / union if union > 0 else 0.0
        except:
            return 0.0

    def _clean_and_validate_queries(self, queries: List[str], original_topic: str) -> List[str]:
        """清理和验证生成的搜索查询 - 简化版本"""
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
        
        print(f"[WebSearch] 查询清理结果: {len(queries)} -> {len(cleaned_queries)} 个查询")
        for i, q in enumerate(cleaned_queries):
            print(f"[WebSearch]   {i+1}. {q}")
        
        return cleaned_queries
    
    def _calculate_content_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本内容的相似度 (0-1)"""
        if not text1 or not text2:
            return 0.0
        
        # 标准化文本（去除空白字符和标点）
        def normalize_text(text):
            # 移除多余空白和常见标点
            normalized = re.sub(r'\s+', ' ', text.strip())
            normalized = re.sub(r'[^\w\s\u4e00-\u9fff]', '', normalized)  # 保留中英文字符
            return normalized.lower()
        
        norm_text1 = normalize_text(text1)
        norm_text2 = normalize_text(text2)
        
        # 使用SequenceMatcher计算相似度
        similarity = SequenceMatcher(None, norm_text1, norm_text2).ratio()
        return similarity
    
    def _deduplicate_documents(self, documents: List[Dict[str, str]], similarity_threshold: float = 0.8) -> List[Dict[str, str]]:
        """
        对文档进行内容去重
        
        Args:
            documents: 文档列表
            similarity_threshold: 相似度阈值，超过此值认为是重复内容
        
        Returns:
            去重后的文档列表
        """
        if not documents:
            return documents
        
        unique_documents = []
        removed_count = 0
        
        for doc in documents:
            content = doc.get("content", "")
            if not content.strip():
                continue  # 跳过空内容
            
            # 检查是否与已有文档重复
            is_duplicate = False
            for existing_doc in unique_documents:
                existing_content = existing_doc.get("content", "")
                similarity = self._calculate_content_similarity(content, existing_content)
                
                if similarity > similarity_threshold:
                    print(f"[WebSearch] 发现重复内容(相似度:{similarity:.2f})，跳过: {doc['url']}")
                    is_duplicate = True
                    removed_count += 1
                    break
            
            if not is_duplicate:
                unique_documents.append(doc)
        
        if removed_count > 0:
            print(f"[WebSearch] 内容去重完成，移除了 {removed_count} 个重复文档，保留 {len(unique_documents)} 个")
        
        return unique_documents
    
    async def generate_search_queries(self, topic: str, model: str = None) -> List[str]:
        """生成搜索关键词"""
        if not ENABLE_QUERY_GENERATION or not topic.strip():
            return [topic]
        
        # 使用传入的模型或默认模型（在函数内部导入，避免循环导入）
        if model is None:
            from ..llm_client import DEFAULT_CHAT_MODEL
            model = DEFAULT_CHAT_MODEL
        
        prompt_system = QUERY_GENERATION_PROMPT_TEMPLATE
        user_prompt = f"课题：{topic}\n请直接给出 JSON，如：{{'queries': ['...', '...', '...', '...']}}"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": LLM_DEFAULT_TEMPERATURE,
        }
        
        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH_LLM_TIMEOUT) as client:
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
                        # 清理和验证查询
                        cleaned_queries = self._clean_and_validate_queries([str(q).strip() for q in queries if str(q).strip()], topic)
                        if cleaned_queries:
                            return cleaned_queries
                except Exception:
                    pass
                
                # 兜底策略：简化的默认查询
                return [topic]
                
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
        """爬取网页内容，支持缓存和自动回退机制"""
        # 如果启用缓存，先检查缓存
        if self.cache and WEB_CACHE_ENABLED:
            cached_content = self.cache.get(url)
            if cached_content is not None:
                return cached_content
        
        # 检测特殊文件类型
        url_lower = url.lower()
        is_pdf = url_lower.endswith('.pdf') or '.pdf?' in url_lower
        is_special_file = (url_lower.endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')) or
                          any(ext in url_lower for ext in ['.pdf?', '.doc?', '.docx?', '.xls?', '.xlsx?', '.ppt?', '.pptx?']))
        
        # 缓存未命中或未启用缓存，进行实际爬取
        content = None
        
        if WEB_LOADER_ENGINE == "playwright":
            # 对于PDF等特殊文件，直接使用safe_web模式
            if is_special_file:
                print(f"[WebSearch] 检测到特殊文件类型 ({url})，直接使用 safe_web 模式...")
                try:
                    content = await fetch_then_extract(
                        url, 
                        selector="article", 
                        timeout=WEB_SEARCH_TIMEOUT
                    )
                    if content:
                        print(f"[WebSearch] safe_web 模式处理特殊文件成功: {url}")
                    else:
                        print(f"[WebSearch] safe_web 模式无法处理特殊文件: {url}")
                except Exception as e:
                    print(f"[WebSearch] safe_web 模式处理特殊文件失败 {url}: {e}")
                    content = None
            else:
                # 常规网页，首先尝试 Playwright 渲染模式
                try:
                    content = await fetch_rendered_text(
                        url, 
                        selector="article",
                        timeout=PLAYWRIGHT_TIMEOUT
                    )
                    print(f"[WebSearch] Playwright 模式成功爬取: {url}")
                except Exception as e:
                    print(f"[WebSearch] Playwright 模式失败 {url}: {e}")
                    print(f"[WebSearch] 自动回退到 safe_web 模式...")
                    
                    # 回退到 safe_web 模式
                    try:
                        content = await fetch_then_extract(
                            url, 
                            selector="article", 
                            timeout=WEB_SEARCH_TIMEOUT
                        )
                        if content:
                            print(f"[WebSearch] safe_web 模式回退成功: {url}")
                        else:
                            print(f"[WebSearch] safe_web 模式回退也未能获取内容: {url}")
                    except Exception as fallback_e:
                        print(f"[WebSearch] safe_web 模式回退也失败 {url}: {fallback_e}")
                        content = None
        else:
            # 使用安全模式（httpx + BeautifulSoup，失败后回退到 Playwright）
            try:
                content = await fetch_then_extract(
                    url, 
                    selector="article", 
                    timeout=WEB_SEARCH_TIMEOUT
                )
            except Exception as e:
                print(f"爬取网页内容失败 {url}: {e}")
                content = None
        
        # 如果成功获取内容且启用缓存，将内容存入缓存
        if content and self.cache and WEB_CACHE_ENABLED:
            self.cache.put(url, content)
        
        return content
    
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
                
                # 检查是否已存在相同URL的Source记录
                from sqlalchemy import select
                existing_source = await db.execute(
                    select(Source).where(Source.url == url)
                )
                source = existing_source.scalar_one_or_none()
                
                if source:
                    # 使用现有的Source记录
                    print(f"[WebSearch] 使用现有Source记录: {url}")
                    source_ids.append(source.id)
                else:
                    # 创建新的 Source 记录
                    source = Source(
                        session_id=session_id,
                        url=url,
                        title=title
                    )
                    db.add(source)
                    await db.commit()
                    await db.refresh(source)
                    source_ids.append(source.id)
                    print(f"[WebSearch] 创建新Source记录: {url}")
                
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
                    batch_size=EMBEDDING_BATCH_SIZE
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
        model: str = None,
        predefined_queries: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行完整的 Web 搜索流程
        
        Args:
            query: 搜索查询
            language: 语言过滤器，默认为 "en-US"
            categories: 搜索类别列表，默认为 ""
            filter_list: 域名过滤列表，用于过滤搜索结果
            model: 用于关键词生成的LLM模型名称，默认使用系统配置
            predefined_queries: 预定义的搜索关键词列表，如果提供则跳过关键词生成
            session_id: 会话ID，如果提供则使用此ID而不是生成新的
            
        Returns:
            包含搜索结果和召回内容的字典
        """
        # 使用提供的session_id或生成新的
        if not session_id:
            session_id = str(uuid.uuid4())
        
        result = {
            "session_id": session_id,
            "query": query,
            "search_results": [],
            "retrieved_content": [],
            "source_ids": [],
            "success": True,
            "message": "",
            "cached": False,
            "reused": False,
            "similar_query": None,
            "metrics": {
                "step_durations_ms": {}
            }
        }
        
        try:
            # 1. 使用预定义的搜索关键词或生成新的
            if predefined_queries and predefined_queries[0].strip():
                queries = predefined_queries
                print(f"[WebSearch] 使用预定义搜索关键词: {queries}")
                result["metrics"]["step_durations_ms"]["generate_queries"] = 0
            else:
                print(f"[WebSearch] 开始生成搜索关键词...")
                t0 = time.perf_counter()
                queries = await self.generate_search_queries(query, model)
                self_time = (time.perf_counter() - t0) * 1000.0
                result["metrics"]["step_durations_ms"]["generate_queries"] = self_time
                print(f"[WebSearch] 生成搜索关键词耗时: {self_time/1000.0:.2f}s")
                print(f"[WebSearch] 生成的搜索关键词: {queries}")
            
            # 2. 生成搜索fingerprint并检查缓存和去重
            fingerprint = self._generate_search_fingerprint(queries, language, categories)
            print(f"[WebSearch] 搜索fingerprint: {fingerprint}")
            
            # 检查完全匹配的缓存
            if fingerprint in self.search_result_cache:
                cached_result = self.search_result_cache[fingerprint]
                print("[WebSearch] 发现完全匹配的缓存结果，直接返回")
                cached_result["cached"] = True
                return cached_result
            
            # 检查相似查询（相似度>0.7认为是重复）
            similar_threshold = 0.7
            for existing_fp in self.executed_queries:
                similarity = self._similarity_check(fingerprint, existing_fp)
                if similarity > similar_threshold:
                    if existing_fp in self.search_result_cache:
                        cached_result = self.search_result_cache[existing_fp]
                        print(f"[WebSearch] 发现相似查询(相似度:{similarity:.2f})，复用结果")
                        cached_result["reused"] = True
                        cached_result["similar_query"] = existing_fp
                        return cached_result
            
            # 记录此次查询
            self.executed_queries.add(fingerprint)
            
            # 3. 并发搜索
            print(f"[WebSearch] 开始并发搜索...")
            t1 = time.perf_counter()
            search_tasks = [self.search_searxng(q, language, categories) for q in queries]
            search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
            search_time = (time.perf_counter() - t1) * 1000.0
            result["metrics"]["step_durations_ms"]["searxng_search"] = search_time
            print(f"[WebSearch] 并发搜索耗时: {search_time/1000.0:.2f}s")
            
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
                print(f"[WebSearch] 开始并发爬取网页内容...")
                t2 = time.perf_counter()
                content_tasks = []
                for item in all_results[:WEB_SEARCH_CONCURRENT_REQUESTS]:
                    content_tasks.append(self.fetch_web_content(item["url"]))
                
                # 处理剩余的 URL（分批）
                remaining_urls = all_results[WEB_SEARCH_CONCURRENT_REQUESTS:]
                contents = await asyncio.gather(*content_tasks, return_exceptions=True)
                first_batch_time = (time.perf_counter() - t2) * 1000.0
                print(f"[WebSearch] 第一批爬取耗时: {first_batch_time/1000.0:.2f}s")
                
                # 处理剩余的批次
                t2b = time.perf_counter()
                for i in range(0, len(remaining_urls), WEB_SEARCH_CONCURRENT_REQUESTS):
                    batch = remaining_urls[i:i + WEB_SEARCH_CONCURRENT_REQUESTS]
                    batch_tasks = [self.fetch_web_content(item["url"]) for item in batch]
                    batch_contents = await asyncio.gather(*batch_tasks, return_exceptions=True)
                    contents.extend(batch_contents)
                
                crawl_time = (time.perf_counter() - t2) * 1000.0
                result["metrics"]["step_durations_ms"]["crawl_contents_total"] = crawl_time
                result["metrics"]["step_durations_ms"]["crawl_first_batch"] = first_batch_time
                result["metrics"]["step_durations_ms"]["crawl_remaining_batches"] = (time.perf_counter() - t2b) * 1000.0
                # 组装文档
                raw_documents = []
                for item, content in zip(all_results, contents):
                    if isinstance(content, str) and content:
                        raw_documents.append({
                            "url": item["url"],
                            "title": item["title"],
                            "content": content,
                            "snippet": item.get("snippet", "")
                        })
                        print(f"[WebSearch] ✓ 成功爬取: {item['url']}")
                    else:
                        print(f"[WebSearch] ✗ 爬取失败: {item['url']} - {type(content).__name__}: {str(content)[:100] if content else 'None'}")
                
                print(f"成功爬取 {len(raw_documents)} 个网页")
                
                # 对文档进行内容去重
                documents = self._deduplicate_documents(raw_documents, similarity_threshold=0.8)
                result["search_results"] = documents
                
                if documents:
                    # 4. 处理文档（切分、embedding、存储）
                    print(f"[WebSearch] 开始处理文档（切分、embedding、存储）...")
                    t3 = time.perf_counter()
                    source_ids = await self.process_documents(documents, session_id)
                    result["source_ids"] = source_ids
                    proc_time = (time.perf_counter() - t3) * 1000.0
                    result["metrics"]["step_durations_ms"]["process_documents"] = proc_time
                    print(f"[WebSearch] 文档处理耗时: {proc_time/1000.0:.2f}s")
                    print(f"[WebSearch] 处理了 {len(source_ids)} 个文档源")
            
            # 5. 搜索和召回
            if result["source_ids"]:
                print(f"[WebSearch] 开始搜索和召回...")
                t4 = time.perf_counter()
                hits = await self.search_and_retrieve(
                    query, 
                    session_id, 
                    source_ids=result["source_ids"]
                )
                retrieve_time = (time.perf_counter() - t4) * 1000.0
                result["metrics"]["step_durations_ms"]["search_and_retrieve"] = retrieve_time
                print(f"[WebSearch] 搜索和召回耗时: {retrieve_time/1000.0:.2f}s")
                
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
        
        # 将成功的搜索结果存入缓存
        if result["success"] and result["retrieved_content"]:
            self.search_result_cache[fingerprint] = result.copy()
            print(f"[WebSearch] 搜索结果已存入缓存，fingerprint: {fingerprint}")
            
            # 限制缓存大小，移除最老的条目
            if len(self.search_result_cache) > 50:  # 限制最多缓存50个查询结果
                oldest_fp = next(iter(self.search_result_cache))
                del self.search_result_cache[oldest_fp]
                self.executed_queries.discard(oldest_fp)
                print("[WebSearch] 缓存已满，移除最老的条目")

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
    predefined_queries: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    **kwargs  # 接受额外的参数用于向后兼容
) -> str:
    """Web 搜索工具函数
    
    Args:
        query: 搜索查询内容
        language: 语言过滤器，默认为 "en-US"
        categories: 搜索类别列表，默认为 ""
        filter_list: 域名过滤列表，用于过滤搜索结果
        model: 用于关键词生成的LLM模型名称，默认使用系统配置
        predefined_queries: 预定义的搜索关键词列表，如果提供则跳过关键词生成
        session_id: 会话ID，如果提供则使用此ID而不是生成新的
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
    
    result = await web_search_tool.execute(query, language, categories, filter_list, model, predefined_queries, session_id)
    
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
