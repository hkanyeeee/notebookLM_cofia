"""Web 搜索工具 - 整合关键词生成、SearxNG 搜索、网页爬取、embedding、向量召回和 rerank"""

import asyncio
import json
import uuid
import time
import re
import hashlib
from typing import List, Dict, Any, Optional, Tuple, Set
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from difflib import SequenceMatcher
import os
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from ..config import (
    EMBEDDING_BATCH_SIZE, LLM_SERVICE_URL, SEARXNG_QUERY_URL,
    WEB_SEARCH_RESULT_COUNT, WEB_SEARCH_MAX_QUERIES, WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_CONCURRENT_REQUESTS, WEB_SEARCH_TIMEOUT,
    WEB_LOADER_ENGINE, PLAYWRIGHT_TIMEOUT,
    ENABLE_QUERY_GENERATION, QUERY_GENERATION_PROMPT_TEMPLATE,
    CHUNK_SIZE, CHUNK_OVERLAP, RAG_TOP_K, RAG_RERANK_TOP_K,
    WEB_CACHE_ENABLED, WEB_CACHE_MAX_SIZE, WEB_CACHE_TTL_SECONDS, WEB_CACHE_MAX_CONTENT_SIZE,
    WEB_SEARCH_LLM_TIMEOUT,
    # 简单查询专用配置
    SIMPLE_QUERY_MAX_QUERIES, SIMPLE_QUERY_RESULT_COUNT, SIMPLE_QUERY_MAX_RESULTS
)
from ..fetch_parse import fetch_then_extract, fetch_rendered_text
from ..chunking import chunk_text
from ..embedding_client import embed_texts, DEFAULT_EMBEDDING_MODEL
from ..vector_db_client import add_embeddings, query_hybrid
from ..rerank_client import rerank
from ..models import Chunk, Source
from ..database import AsyncSessionLocal
from ..cache import get_web_content_cache


# === 相似度计算的模块级辅助函数（可被多进程安全调用） ===
def _normalize_text_for_similarity(text: str) -> str:
    if not text:
        return ""
    # 移除多余空白和常见标点，仅保留中英文与数字下划线
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", "", normalized)
    return normalized.lower()


def _get_text_hash(text: str) -> str:
    """计算文本的MD5哈希值，用于快速去重"""
    if not text:
        return ""
    normalized = _normalize_text_for_similarity(text)
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def _get_text_shingles(text: str, k: int = 3) -> Set[str]:
    """提取文本的k-shingles（连续k个字符的子串集合）"""
    if not text or len(text) < k:
        return set()
    normalized = _normalize_text_for_similarity(text)
    return {normalized[i:i+k] for i in range(len(normalized) - k + 1)}


def _jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    """计算两个集合的Jaccard相似度"""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0


def _fast_similarity(text1: str, text2: str, max_length: int = 2000) -> float:
    """快速计算两个文本的相似度
    
    Args:
        text1, text2: 待比较的文本
        max_length: 比较的最大文本长度，超出部分将被截断
    
    Returns:
        相似度分数 (0-1)
    """
    if not text1 or not text2:
        return 0.0
    
    # 截断长文本以提高性能
    text1_truncated = text1[:max_length] if len(text1) > max_length else text1
    text2_truncated = text2[:max_length] if len(text2) > max_length else text2
    
    # 使用k-shingles计算Jaccard相似度
    shingles1 = _get_text_shingles(text1_truncated, k=3)
    shingles2 = _get_text_shingles(text2_truncated, k=3)
    
    return _jaccard_similarity(shingles1, shingles2)


def _sequence_ratio_from_normalized(args: Tuple[str, str]) -> float:
    """备用的SequenceMatcher计算方法（仅在需要高精度时使用）"""
    a, b = args
    # 限制文本长度以防止性能问题
    max_len = 1000
    a_truncated = a[:max_len] if len(a) > max_len else a
    b_truncated = b[:max_len] if len(b) > max_len else b
    return SequenceMatcher(None, a_truncated, b_truncated).ratio()


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
        
        # 单次问题的搜索历史管理（按session_id分组）
        self.session_search_history = {}  # {session_id: [{"query": "...", "result_summary": "...", "timestamp": ...}]}

    def _normalize_query(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        s = text.strip().lower()
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"[\u3000\s\t\r\n\-_,.;:!?，。；：！？\"'`（）()\\[\]{}]", "", s)
        return s

    def _generate_search_fingerprint(self, queries: List[str]) -> str:
        """生成搜索查询的fingerprint，用于去重和缓存"""
        normalized_queries = sorted([self._normalize_query(q) for q in queries if q.strip()])
        fingerprint = f"queries:{'|'.join(normalized_queries)}"
        return fingerprint
    
    def _record_session_search(self, session_id: str, original_query: str, search_queries: List[str], result_summary: str):
        """记录会话级搜索历史"""
        import time
        
        if session_id not in self.session_search_history:
            self.session_search_history[session_id] = []
        
        # 记录这次搜索
        search_record = {
            "original_query": original_query,
            "search_queries": search_queries,
            "result_summary": result_summary[:300] + "..." if len(result_summary) > 300 else result_summary,
            "timestamp": time.time()
        }
        
        self.session_search_history[session_id].append(search_record)
        
        # 限制每个会话的历史记录数量
        if len(self.session_search_history[session_id]) > 10:
            self.session_search_history[session_id].pop(0)  # 移除最旧的记录
        
        print(f"[WebSearch] 记录会话搜索历史: {session_id}, 当前历史记录数: {len(self.session_search_history[session_id])}")
    
    def _get_session_search_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取会话级搜索历史"""
        if session_id not in self.session_search_history:
            return []
        
        # 返回格式化的搜索历史，用于传递给关键词生成
        formatted_history = []
        for record in self.session_search_history[session_id]:
            formatted_history.append({
                "query": f"{record['original_query']} (搜索词: {', '.join(record['search_queries'])})",
                "result_summary": record["result_summary"]
            })
        
        return formatted_history
    
    def _similarity_check(self, fp1: str, fp2: str) -> float:
        """检查两个fingerprint的相似度 (0-1)"""
        # 提取全部查询项（不能只取首段）
        try:
            def _extract_queries(fp: str) -> Set[str]:
                s = fp or ""
                prefix = "queries:"
                if s.startswith(prefix):
                    s = s[len(prefix):]
                parts = [p for p in s.split('|') if p]
                return set(parts)

            queries1 = _extract_queries(fp1)
            queries2 = _extract_queries(fp2)

            if not queries1 or not queries2:
                return 0.0

            intersection = len(queries1.intersection(queries2))
            union = len(queries1.union(queries2))
            return intersection / union if union > 0 else 0.0
        except Exception:
            return 0.0

    def _normalize_url_for_dedup(self, url: str) -> str:
        """用于去重的URL规范化：小写scheme/netloc，去默认端口与fragment，排序查询参数，去除多余尾斜杠。"""
        try:
            parsed = urlparse(url.strip())
            scheme = (parsed.scheme or '').lower()
            netloc = (parsed.netloc or '').lower()
            if (scheme == 'http' and netloc.endswith(':80')) or (scheme == 'https' and netloc.endswith(':443')):
                netloc = netloc.rsplit(':', 1)[0]
            path = parsed.path or ''
            if path.endswith('/') and path != '/':
                path = path.rstrip('/')
            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            if query_items:
                query_items.sort(key=lambda kv: (kv[0], kv[1]))
                query = urlencode(query_items, doseq=True)
            else:
                query = ''
            normalized = urlunparse((scheme, netloc, path, parsed.params, query, ''))
            return normalized
        except Exception:
            return url

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
        
        # 使用快速相似度计算方法
        return _fast_similarity(text1, text2)
    
    
    async def generate_search_queries(self, topic: str, model: str = None, search_history: List[Dict[str, Any]] = None) -> List[str]:
        """生成搜索关键词
        
        Args:
            topic: 搜索主题
            model: 模型名称  
            search_history: 历史搜索记录列表，格式: [{"query": "关键词", "result_summary": "结果摘要"}]
        """
        if not ENABLE_QUERY_GENERATION or not topic.strip():
            return [topic]
        
        # 构建历史搜索信息
        history_context = ""
        if search_history:
            history_context = "\n\n**历史搜索记录**（避免重复搜索相似内容）：\n"
            for i, record in enumerate(search_history[-3:], 1):  # 只考虑最近3次搜索
                history_context += f"{i}. 搜索关键词：{record.get('query', '')}\n"
                if record.get('result_summary'):
                    history_context += f"   获得结果：{record['result_summary'][:200]}...\n"
            history_context += "\n请确保新生成的关键词与上述历史搜索明显不同，避免获取重复信息。"
        
        prompt_system = QUERY_GENERATION_PROMPT_TEMPLATE + history_context
        user_prompt = f"课题：{topic}\n请直接给出 JSON，如：{{'queries': ['...', '...', '...']}}"
        
        try:
            from ..llm_client import chat_complete
            content = await chat_complete(
                system_prompt=prompt_system,
                user_prompt=user_prompt,
                model=model,
                timeout=WEB_SEARCH_LLM_TIMEOUT,
            )
            
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
        count: int = WEB_SEARCH_RESULT_COUNT
    ) -> List[Dict[str, str]]:
        """使用 SearxNG 搜索"""
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "safesearch": "1",
            "time_range": "",
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
                for r in results_sorted[:count]:
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
    
    async def process_single_document(
        self, 
        doc: Dict[str, str], 
        session_id: str, 
        global_chunk_index: int,
        db: AsyncSession
    ) -> Tuple[Optional[int], List[Chunk], int]:
        """处理单个文档：切分、创建chunks、返回source_id和chunks"""
        url = doc["url"]
        title = doc["title"]
        content = doc.get("content", "")
        
        if not content:
            return None, [], global_chunk_index
        
        # 规范化 URL，避免重复的 Source
        normalized_url = self._normalize_url_for_dedup(url)
        # 检查是否已存在相同URL的Source记录（使用规范化后的URL）
        from sqlalchemy import select
        existing_source = await db.execute(
            select(Source).where(Source.url == normalized_url)
        )
        source = existing_source.scalar_one_or_none()
        
        if source:
            # 使用现有的Source记录
            print(f"[WebSearch] 使用现有Source记录: {url}")
        else:
            # 创建新的 Source 记录
            source = Source(
                session_id=session_id,
                url=normalized_url,
                title=title
            )
            db.add(source)
            await db.commit()
            await db.refresh(source)
            print(f"[WebSearch] 创建新Source记录: {url}")
        
        # 文档切分
        chunks_text = chunk_text(
            content,
            tokens_per_chunk=CHUNK_SIZE,
            overlap_tokens=CHUNK_OVERLAP
        )
        
        # 创建 Chunk 记录
        chunks = []
        import time
        timestamp_ms = int(time.time() * 1000)
        for idx, chunk_content in enumerate(chunks_text):
            # 生成更加唯一的chunk_id，包含时间戳和URL哈希
            url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
            chunk_id = f"{session_id}_{url_hash}_{global_chunk_index}_{timestamp_ms}_{idx}"
            chunk = Chunk(
                content=chunk_content,
                source_id=source.id,
                session_id=session_id,
                chunk_id=chunk_id
            )
            chunks.append(chunk)
            global_chunk_index += 1
        
        try:
            db.add_all(chunks)
            await db.commit()
            
            # 刷新以获取 ID 并确保chunks在session中
            for chunk in chunks:
                await db.refresh(chunk)
                # 确保source关系正确加载
                if not chunk.source:
                    chunk.source = source
            
            return source.id, chunks, global_chunk_index
        except Exception as e:
            await db.rollback()
            print(f"[WebSearch] 数据库操作失败，回滚事务: {e}")
            # 如果是重复键错误，尝试重新生成chunk_id
            if "UNIQUE constraint failed: chunks.id" in str(e):
                print(f"[WebSearch] 检测到ID冲突，尝试重新创建chunks...")
                # 清除之前的chunks，重新创建
                chunks.clear()
                retry_timestamp = int(time.time() * 1000000)  # 更高精度的时间戳
                for idx, chunk_content in enumerate(chunks_text):
                    # 使用更随机的chunk_id来避免冲突
                    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
                    chunk_id = f"{session_id}_{url_hash}_{global_chunk_index}_retry_{retry_timestamp}_{idx}"
                    chunk = Chunk(
                        content=chunk_content,
                        source_id=source.id,
                        session_id=session_id,
                        chunk_id=chunk_id
                    )
                    chunks.append(chunk)
                
                try:
                    db.add_all(chunks)
                    await db.commit()
                    
                    for chunk in chunks:
                        await db.refresh(chunk)
                        if not chunk.source:
                            chunk.source = source
                    
                    return source.id, chunks, global_chunk_index
                except Exception as retry_e:
                    await db.rollback()
                    print(f"[WebSearch] 重试后仍失败: {retry_e}")
                    raise retry_e
            else:
                raise e

    async def process_chunk_batch(
        self, 
        chunk_batch: List[Tuple[Chunk, int]], 
        pending_embeddings: List[str]
    ) -> List[Tuple[int, List[Chunk], List[List[float]]]]:
        """处理一批chunks：计算embedding并按source分组"""
        if not chunk_batch or not pending_embeddings:
            return []
        
        print(f"[WebSearch] 处理微批embedding: {len(pending_embeddings)} 个chunks")
        
        # 计算embeddings
        embeddings = await embed_texts(
            pending_embeddings,
            model=DEFAULT_EMBEDDING_MODEL,
            batch_size=EMBEDDING_BATCH_SIZE
        )
        
        # 按source_id分组
        source_groups = {}
        for (chunk, embed_idx), embedding in zip(chunk_batch, embeddings):
            source_id = chunk.source_id
            if source_id not in source_groups:
                source_groups[source_id] = {'chunks': [], 'embeddings': []}
            source_groups[source_id]['chunks'].append(chunk)
            source_groups[source_id]['embeddings'].append(embedding)
        
        # 转换为返回格式
        result = []
        for source_id, group in source_groups.items():
            result.append((source_id, group['chunks'], group['embeddings']))
        
        return result

    async def flush_to_vector_db(self, source_chunk_embeddings: List[Tuple[int, List[Chunk], List[List[float]]]]):
        """将chunks和embeddings写入向量数据库"""
        for source_id, chunks, embeddings in source_chunk_embeddings:
            try:
                await add_embeddings(source_id, chunks, embeddings)
                print(f"[WebSearch] 成功入库 source_id={source_id}, {len(chunks)} 个chunks")
            except Exception as e:
                print(f"[WebSearch] 入库失败 source_id={source_id}: {e}")
    
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
        filter_list: Optional[List[str]] = None,
        model: str = None,
        predefined_queries: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        perform_retrieval: bool = True,
        search_history: Optional[List[Dict[str, Any]]] = None,
        is_simple_query: bool = False,
        custom_result_count: Optional[int] = None,
        custom_max_results: Optional[int] = None
    ) -> Dict[str, Any]:
        """执行完整的 Web 搜索流程
        
        Args:
            query: 搜索查询
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
        
        # 根据查询类型确定配置参数
        if is_simple_query:
            effective_result_count = custom_result_count or SIMPLE_QUERY_RESULT_COUNT
            effective_max_results = custom_max_results or SIMPLE_QUERY_MAX_RESULTS
            print(f"[WebSearch] 简单查询模式: result_count={effective_result_count}, max_results={effective_max_results}")
        else:
            effective_result_count = custom_result_count or WEB_SEARCH_RESULT_COUNT
            effective_max_results = custom_max_results or WEB_SEARCH_MAX_RESULTS
            print(f"[WebSearch] 普通查询模式: result_count={effective_result_count}, max_results={effective_max_results}")
        
        print(f"[WebSearch] 开始执行，会话ID: {session_id}")
        print(f"[WebSearch] 过滤域名列表: {filter_list}")
        
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
                
                # 优先使用传入的搜索历史，如果没有则使用会话级历史
                history_to_use = search_history
                if not history_to_use and session_id:
                    history_to_use = self._get_session_search_history(session_id)
                
                queries = await self.generate_search_queries(query, model, history_to_use)
                self_time = (time.perf_counter() - t0) * 1000.0
                result["metrics"]["step_durations_ms"]["generate_queries"] = self_time
                print(f"[WebSearch] 生成搜索关键词耗时: {self_time/1000.0:.2f}s")
                print(f"[WebSearch] 生成的搜索关键词: {queries}")
                if history_to_use:
                    print(f"[WebSearch] 使用搜索历史: {len(history_to_use)} 条记录")
            
            # 根据查询类型对queries数量进行截断
            if is_simple_query:
                queries = queries[:SIMPLE_QUERY_MAX_QUERIES]
                print(f"[WebSearch] 简单查询模式，截断到前 {SIMPLE_QUERY_MAX_QUERIES} 个查询: {queries}")
            
            # 2. 生成搜索fingerprint并检查缓存和去重
            fingerprint = self._generate_search_fingerprint(queries)
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
            search_tasks = [self.search_searxng(q, count=effective_result_count) for q in queries]
            search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
            search_time = (time.perf_counter() - t1) * 1000.0
            result["metrics"]["step_durations_ms"]["searxng_search"] = search_time
            print(f"[WebSearch] 并发搜索耗时: {search_time/1000.0:.2f}s")
            
            # 合并搜索结果并去重（使用规范化 URL）
            all_results = []
            seen_urls = set()
            for results in search_results_list:
                if isinstance(results, list):
                    for item in results:
                        url = item.get("url")
                        norm_url = self._normalize_url_for_dedup(url) if url else None
                        if norm_url and norm_url not in seen_urls:
                            # 应用域名过滤
                            if filter_list:
                                from urllib.parse import urlparse
                                domain = urlparse(url).netloc
                                # 如果域名在过滤列表中，则跳过
                                if any(filter_domain in domain for filter_domain in filter_list):
                                    continue
                            seen_urls.add(norm_url)
                            all_results.append(item)
            
            # 限制结果数量
            all_results = all_results[:effective_max_results]
            print(f"找到 {len(all_results)} 个搜索结果")
            
            if all_results:
                # 3. 增量处理：先去重，然后并发爬取+实时处理
                print(f"[WebSearch] 开始增量处理模式...")
                t2 = time.perf_counter()
                
                # 微批配置
                FLUSH_CHUNK_COUNT = 20  # 达到20个chunk就flush
                FLUSH_TIMEOUT_MS = 500  # 或者500ms超时就flush
                
                # 使用数据库会话
                async with AsyncSessionLocal() as db:
                    source_ids = []
                    processed_documents = []
                    global_chunk_index = 0
                    
                    # 微批缓冲区
                    pending_chunks = []  # List[Tuple[Chunk, int]]  # (chunk, embedding_index)
                    pending_embeddings = []  # List[str]  # chunk contents for embedding
                    last_flush_time = time.perf_counter()
                    
                    async def flush_pending():
                        nonlocal pending_chunks, pending_embeddings, last_flush_time
                        if not pending_chunks:
                            return
                        
                        print(f"[WebSearch] 触发微批flush: {len(pending_chunks)} chunks")
                        source_chunk_embeddings = await self.process_chunk_batch(pending_chunks, pending_embeddings)
                        await self.flush_to_vector_db(source_chunk_embeddings)
                        
                        # 清空缓冲区
                        pending_chunks.clear()
                        pending_embeddings.clear()
                        last_flush_time = time.perf_counter()
                    
                    # 创建并发爬取任务
                    crawl_semaphore = asyncio.Semaphore(WEB_SEARCH_CONCURRENT_REQUESTS)
                    
                    async def crawl_and_process(item):
                        nonlocal global_chunk_index
                        async with crawl_semaphore:
                            try:
                                content = await self.fetch_web_content(item["url"])
                                if isinstance(content, str) and content:
                                    doc = {
                                        "url": item["url"],
                                        "title": item["title"],
                                        "content": content,
                                        "snippet": item.get("snippet", "")
                                    }
                                    
                                    # 立即处理单个文档
                                    source_id, chunks, new_global_index = await self.process_single_document(
                                        doc, session_id, global_chunk_index, db
                                    )
                                    global_chunk_index = new_global_index
                                    
                                    if source_id and chunks:
                                        print(f"[WebSearch] ✓ 成功处理: {item['url']} -> {len(chunks)} chunks")
                                        return source_id, doc, chunks
                                    else:
                                        print(f"[WebSearch] ✗ 处理失败: {item['url']} - 无内容")
                                        return None, None, []
                                else:
                                    print(f"[WebSearch] ✗ 爬取失败: {item['url']} - {type(content).__name__}")
                                    return None, None, []
                            except Exception as e:
                                # 如果遇到数据库错误，确保session状态正常
                                if "constraint" in str(e).lower() or "rollback" in str(e).lower():
                                    try:
                                        await db.rollback()
                                        print(f"[WebSearch] 数据库错误后执行回滚: {item['url']}")
                                    except Exception as rollback_e:
                                        print(f"[WebSearch] 回滚失败: {rollback_e}")
                                print(f"[WebSearch] ✗ 处理异常: {item['url']} - {e}")
                                return None, None, []
                    
                    # 并发处理所有URL
                    tasks = [crawl_and_process(item) for item in all_results]
                    
                    # 使用as_completed逐个处理完成的任务
                    completed_count = 0
                    for coro in asyncio.as_completed(tasks):
                        try:
                            source_id, doc, chunks = await coro
                            completed_count += 1
                            
                            if source_id and doc and chunks:
                                source_ids.append(source_id)
                                processed_documents.append(doc)
                                
                                # 添加到微批缓冲区
                                for chunk in chunks:
                                    pending_chunks.append((chunk, len(pending_embeddings)))
                                    pending_embeddings.append(chunk.content)
                                
                                # 检查是否需要flush
                                current_time = time.perf_counter()
                                should_flush = (
                                    len(pending_chunks) >= FLUSH_CHUNK_COUNT or
                                    (current_time - last_flush_time) * 1000 >= FLUSH_TIMEOUT_MS
                                )
                                
                                if should_flush:
                                    await flush_pending()
                            
                            # 每处理5个页面输出一次进度
                            if completed_count % 5 == 0:
                                print(f"[WebSearch] 进度: {completed_count}/{len(tasks)} 页面已处理")
                                
                        except Exception as e:
                            print(f"[WebSearch] 处理任务异常: {e}")
                            completed_count += 1
                    
                    # 最后flush剩余的chunks
                    if pending_chunks:
                        print("[WebSearch] 最终flush剩余chunks")
                        await flush_pending()
                    
                    result["source_ids"] = source_ids
                    result["search_results"] = processed_documents
                
                crawl_time = (time.perf_counter() - t2) * 1000.0
                result["metrics"]["step_durations_ms"]["incremental_process_total"] = crawl_time
                print(f"[WebSearch] 增量处理总耗时: {crawl_time/1000.0:.2f}s")
                print(f"[WebSearch] 成功处理 {len(processed_documents)} 个文档，入库 {len(source_ids)} 个源")
            
            # 5. 搜索和召回（可选）
            if result["source_ids"]:
                if perform_retrieval:
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
                    # 仅完成搜索、抓取、切分与入库，跳过召回
                    result["message"] = f"搜索完成，入库 {len(result['source_ids'])} 个数据源（未执行召回）"
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
            
            # 记录会话级搜索历史
            if session_id:
                self._record_session_search(session_id, query, queries, result["message"])
            
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
    filter_list: Optional[List[str]] = None,
    model: str = None,
    predefined_queries: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    perform_retrieval: bool = True,
    is_simple_query: bool = False,  # 新增：是否为简单查询模式
    **kwargs  # 接受额外的参数用于向后兼容
) -> str:
    """Web 搜索工具函数
    
    Args:
        query: 搜索查询内容
        filter_list: 域名过滤列表，用于过滤搜索结果
        model: 用于关键词生成的LLM模型名称，默认使用系统配置
        predefined_queries: 预定义的搜索关键词列表，如果提供则跳过关键词生成
        session_id: 会话ID，如果提供则使用此ID而不是生成新的
        is_simple_query: 是否为简单查询模式，影响搜索关键词数量和结果数量配置
        **kwargs: 额外参数（用于向后兼容）
    
    Returns:
        搜索和召回结果的 JSON 字符串
    """
    print(f"[WebSearch] 工具函数被调用，参数: query={query}, filter_list={filter_list}, model={model}, is_simple_query={is_simple_query}, kwargs={kwargs}")
    
    # 处理向后兼容的参数名映射 - 移除了对source/categories的处理
    if "topn" in kwargs:
        # topn参数目前没有直接映射，可以记录日志或忽略
        print(f"[WebSearch] 注意：topn参数 ({kwargs['topn']}) 当前未使用")
    
    # 检查是否通过kwargs传递了简单查询标志（向后兼容）
    if "is_simple_query" in kwargs and not is_simple_query:
        is_simple_query = kwargs["is_simple_query"]
        print(f"[WebSearch] 从kwargs中获取is_simple_query标志: {is_simple_query}")
    
    # 如果有不再支持的参数，记录但不处理
    deprecated_params = ["source", "categories", "language"]
    for param in deprecated_params:
        if param in kwargs:
            print(f"[WebSearch] 注意：{param} 参数已移除，将由外部 SearxNG 控制")
    
    result = await web_search_tool.execute(
        query=query,
        filter_list=filter_list,
        model=model,
        predefined_queries=predefined_queries,
        session_id=session_id,
        perform_retrieval=perform_retrieval,
        is_simple_query=is_simple_query
    )
    
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
