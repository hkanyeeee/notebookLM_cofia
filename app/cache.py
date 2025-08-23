"""网页内容缓存模块

提供基于内存的网页内容缓存，避免重复爬取相同网页，提升性能。
"""

import time
import hashlib
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """缓存条目"""
    url: str
    content: str
    cached_at: float
    size: int


class WebContentCache:
    """网页内容缓存
    
    使用内存缓存已爬取的网页内容，避免重复请求。
    - 基于URL的键值存储
    - 支持过期时间
    - 自动清理过期缓存
    """
    
    def __init__(self, 
                 max_cache_size: int = 1000,
                 default_ttl: int = 3600,
                 max_content_size: int = 1024 * 1024):  # 1MB
        """
        Args:
            max_cache_size: 最大缓存条目数
            default_ttl: 默认过期时间（秒）
            max_content_size: 单个内容最大大小（字节）
        """
        self._cache: Dict[str, CacheEntry] = {}
        self.max_cache_size = max_cache_size
        self.default_ttl = default_ttl
        self.max_content_size = max_content_size
        
        # 统计信息
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _normalize_url(self, url: str) -> str:
        """标准化URL，确保缓存键的一致性
        
        - 移除fragment（#后的部分）
        - 统一协议为小写
        - 移除默认端口
        - 对查询参数排序（如果需要的话）
        """
        try:
            parsed = urlparse(url.strip())
            
            # 统一协议为小写
            scheme = parsed.scheme.lower()
            
            # 统一域名为小写
            netloc = parsed.netloc.lower()
            
            # 移除默认端口
            if (scheme == 'http' and netloc.endswith(':80')) or \
               (scheme == 'https' and netloc.endswith(':443')):
                netloc = netloc.rsplit(':', 1)[0]
            
            # 重构URL（不包含fragment）
            normalized = urlunparse((
                scheme,
                netloc, 
                parsed.path,
                parsed.params,
                parsed.query,
                ''  # 移除fragment
            ))
            
            return normalized
            
        except Exception as e:
            print(f"[Cache] URL标准化失败 {url}: {e}")
            return url
    
    def _generate_cache_key(self, url: str) -> str:
        """生成缓存键"""
        normalized_url = self._normalize_url(url)
        # 使用URL的MD5哈希作为缓存键，避免特殊字符问题
        return hashlib.md5(normalized_url.encode('utf-8')).hexdigest()
    
    def _is_expired(self, entry: CacheEntry, ttl: Optional[int] = None) -> bool:
        """检查缓存条目是否过期"""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        return time.time() - entry.cached_at > effective_ttl
    
    def _cleanup_expired(self):
        """清理过期的缓存条目"""
        current_time = time.time()
        expired_keys = []
        
        for key, entry in self._cache.items():
            if current_time - entry.cached_at > self.default_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
            self._evictions += 1
        
        if expired_keys:
            print(f"[Cache] 清理了 {len(expired_keys)} 个过期缓存条目")
    
    def _evict_lru(self):
        """根据LRU策略驱逐缓存（简单实现：删除最旧的条目）"""
        if not self._cache:
            return
            
        # 找到最旧的条目
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].cached_at)
        del self._cache[oldest_key]
        self._evictions += 1
        print(f"[Cache] LRU驱逐缓存条目: {oldest_key}")
    
    def get(self, url: str, ttl: Optional[int] = None) -> Optional[str]:
        """获取缓存内容
        
        Args:
            url: 网页URL
            ttl: 自定义过期时间（秒），None使用默认值
            
        Returns:
            缓存的内容，如果未命中或已过期则返回None
        """
        # 定期清理过期缓存
        if len(self._cache) > 100:  # 只有在缓存较多时才清理
            self._cleanup_expired()
        
        cache_key = self._generate_cache_key(url)
        
        if cache_key not in self._cache:
            self._misses += 1
            return None
        
        entry = self._cache[cache_key]
        
        # 检查是否过期
        if self._is_expired(entry, ttl):
            del self._cache[cache_key]
            self._misses += 1
            return None
        
        self._hits += 1
        print(f"[Cache] 缓存命中: {url}")
        return entry.content
    
    def put(self, url: str, content: str) -> bool:
        """存储内容到缓存
        
        Args:
            url: 网页URL
            content: 网页内容
            
        Returns:
            是否成功存储
        """
        if not content or len(content.encode('utf-8')) > self.max_content_size:
            print(f"[Cache] 内容过大或为空，不缓存: {url}")
            return False
        
        cache_key = self._generate_cache_key(url)
        
        # 如果缓存已满，执行LRU驱逐
        while len(self._cache) >= self.max_cache_size:
            self._evict_lru()
        
        # 存储到缓存
        entry = CacheEntry(
            url=url,
            content=content,
            cached_at=time.time(),
            size=len(content.encode('utf-8'))
        )
        
        self._cache[cache_key] = entry
        print(f"[Cache] 缓存存储: {url} ({entry.size} bytes)")
        return True
    
    def clear(self):
        """清空所有缓存"""
        self._cache.clear()
        print("[Cache] 已清空所有缓存")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0
        
        total_size = sum(entry.size for entry in self._cache.values())
        
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self.max_cache_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "evictions": self._evictions,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }
    
    def print_stats(self):
        """打印缓存统计信息"""
        stats = self.get_stats()
        print(f"[Cache] 统计信息:")
        print(f"  缓存条目: {stats['cache_size']}/{stats['max_cache_size']}")
        print(f"  命中率: {stats['hit_rate']:.1f}% ({stats['hits']} hits, {stats['misses']} misses)")
        print(f"  驱逐次数: {stats['evictions']}")
        print(f"  总大小: {stats['total_size_mb']} MB")


# 全局缓存实例
web_content_cache = WebContentCache()


def get_web_content_cache() -> WebContentCache:
    """获取全局网页内容缓存实例"""
    return web_content_cache
