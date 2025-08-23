"""统一的缓存系统"""
import time
import hashlib
import json
import asyncio
from typing import Any, Optional, Dict, List, Union, Callable, Protocol, runtime_checkable
from abc import ABC, abstractmethod
from enum import Enum
import weakref
from dataclasses import dataclass


class CacheBackend(str, Enum):
    """缓存后端类型"""
    MEMORY = "memory"
    REDIS = "redis"
    DISK = "disk"


@dataclass
class CacheConfig:
    """缓存配置"""
    ttl_seconds: float = 3600.0        # 默认1小时过期
    max_size: int = 1000               # 最大缓存项数
    backend: CacheBackend = CacheBackend.MEMORY
    namespace: str = "default"         # 缓存命名空间
    serialize: bool = True             # 是否序列化键值
    compression: bool = False          # 是否压缩存储
    
    # 高级配置
    enable_stats: bool = True          # 启用统计
    auto_refresh: bool = False         # 自动刷新即将过期的缓存
    refresh_threshold: float = 0.8     # 刷新阈值（剩余TTL比例）


@dataclass
class CacheStats:
    """缓存统计信息"""
    hits: int = 0
    misses: int = 0
    puts: int = 0
    evictions: int = 0
    expired: int = 0
    total_requests: int = 0
    
    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests


@runtime_checkable
class CacheItem(Protocol):
    """缓存项协议"""
    value: Any
    created_at: float
    expires_at: Optional[float]
    access_count: int
    last_accessed: float


class MemoryCacheItem:
    """内存缓存项"""
    def __init__(self, value: Any, ttl: Optional[float] = None):
        self.value = value
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl if ttl else None
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def access(self) -> Any:
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value
    
    def remaining_ttl(self) -> Optional[float]:
        if self.expires_at is None:
            return None
        return max(0, self.expires_at - time.time())


class BaseCacheBackend(ABC):
    """缓存后端基类"""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self.stats = CacheStats() if config.enable_stats else None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """启动清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def _periodic_cleanup(self):
        """定期清理过期缓存"""
        while True:
            try:
                await self._cleanup_expired()
                await asyncio.sleep(300)  # 每5分钟清理一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Cache] 清理任务出错: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再试
    
    def _update_stats(self, operation: str):
        """更新统计信息"""
        if not self.stats:
            return
        
        if operation == "hit":
            self.stats.hits += 1
        elif operation == "miss":
            self.stats.misses += 1
        elif operation == "put":
            self.stats.puts += 1
        elif operation == "eviction":
            self.stats.evictions += 1
        elif operation == "expired":
            self.stats.expired += 1
        
        self.stats.total_requests = self.stats.hits + self.stats.misses
    
    def _make_key(self, key: str) -> str:
        """生成缓存键"""
        if self.config.namespace:
            key = f"{self.config.namespace}:{key}"
        
        if self.config.serialize:
            # 使用MD5哈希确保键的一致性和长度限制
            return hashlib.md5(key.encode('utf-8')).hexdigest()
        
        return key
    
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        pass
    
    @abstractmethod
    async def put(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """设置缓存值"""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除缓存值"""
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """清空缓存"""
        pass
    
    @abstractmethod
    async def _cleanup_expired(self) -> int:
        """清理过期缓存"""
        pass
    
    async def close(self):
        """关闭缓存后端"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass


class MemoryCacheBackend(BaseCacheBackend):
    """内存缓存后端"""
    
    def __init__(self, config: CacheConfig):
        super().__init__(config)
        self._cache: Dict[str, MemoryCacheItem] = {}
        self._access_order: List[str] = []  # LRU 访问顺序
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        cache_key = self._make_key(key)
        
        async with self._lock:
            item = self._cache.get(cache_key)
            
            if item is None:
                self._update_stats("miss")
                return None
            
            if item.is_expired():
                del self._cache[cache_key]
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._update_stats("expired")
                self._update_stats("miss")
                return None
            
            # 更新访问顺序（LRU）
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            
            self._update_stats("hit")
            return item.access()
    
    async def put(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        cache_key = self._make_key(key)
        ttl = ttl or self.config.ttl_seconds
        
        async with self._lock:
            # 检查是否需要腾出空间
            while len(self._cache) >= self.config.max_size:
                await self._evict_lru()
            
            item = MemoryCacheItem(value, ttl)
            self._cache[cache_key] = item
            
            # 更新访问顺序
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            
            self._update_stats("put")
    
    async def delete(self, key: str) -> bool:
        cache_key = self._make_key(key)
        
        async with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                return True
            return False
    
    async def exists(self, key: str) -> bool:
        cache_key = self._make_key(key)
        
        async with self._lock:
            item = self._cache.get(cache_key)
            if item is None:
                return False
            
            if item.is_expired():
                del self._cache[cache_key]
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._update_stats("expired")
                return False
            
            return True
    
    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
            self._access_order.clear()
    
    async def _cleanup_expired(self) -> int:
        """清理过期缓存"""
        expired_keys = []
        
        async with self._lock:
            for key, item in self._cache.items():
                if item.is_expired():
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                self._update_stats("expired")
        
        return len(expired_keys)
    
    async def _evict_lru(self) -> None:
        """淘汰最久未使用的缓存项"""
        if not self._access_order:
            return
        
        lru_key = self._access_order.pop(0)
        if lru_key in self._cache:
            del self._cache[lru_key]
            self._update_stats("eviction")


class ToolCache:
    """工具缓存管理器"""
    
    def __init__(self, default_config: Optional[CacheConfig] = None):
        self.default_config = default_config or CacheConfig()
        self._backends: Dict[str, BaseCacheBackend] = {}
        self._tool_configs: Dict[str, CacheConfig] = {}
        
        # 创建默认后端
        self._default_backend = self._create_backend(self.default_config)
        self._backends["default"] = self._default_backend
    
    def _create_backend(self, config: CacheConfig) -> BaseCacheBackend:
        """创建缓存后端"""
        if config.backend == CacheBackend.MEMORY:
            return MemoryCacheBackend(config)
        else:
            # 目前只实现内存后端，其他后端可以后续扩展
            raise NotImplementedError(f"缓存后端 {config.backend} 尚未实现")
    
    def configure_tool(self, tool_name: str, config: CacheConfig):
        """为特定工具配置缓存"""
        self._tool_configs[tool_name] = config
        backend_key = f"tool_{tool_name}"
        self._backends[backend_key] = self._create_backend(config)
    
    def _get_backend(self, tool_name: Optional[str] = None) -> BaseCacheBackend:
        """获取指定工具的缓存后端"""
        if tool_name and tool_name in self._tool_configs:
            backend_key = f"tool_{tool_name}"
            return self._backends[backend_key]
        return self._default_backend
    
    def _generate_cache_key(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any], 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成缓存键"""
        # 创建一个稳定的键，基于工具名称和参数
        key_data = {
            "tool": tool_name,
            "args": self._normalize_arguments(arguments)
        }
        
        # 如果有上下文信息也包含进去
        if context:
            key_data["context"] = context
        
        # 序列化并生成哈希
        key_json = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(key_json.encode('utf-8')).hexdigest()
    
    def _normalize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """规范化参数，确保缓存键的一致性"""
        normalized = {}
        
        for key, value in sorted(arguments.items()):
            if isinstance(value, (str, int, float, bool)) or value is None:
                normalized[key] = value
            elif isinstance(value, (list, tuple)):
                # 对列表进行排序和规范化
                try:
                    normalized[key] = sorted(value) if all(isinstance(x, (str, int, float)) for x in value) else list(value)
                except TypeError:
                    normalized[key] = list(value)
            elif isinstance(value, dict):
                normalized[key] = self._normalize_arguments(value)
            else:
                # 对于其他类型，转换为字符串
                normalized[key] = str(value)
        
        return normalized
    
    async def get(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """获取工具执行结果缓存"""
        backend = self._get_backend(tool_name)
        cache_key = self._generate_cache_key(tool_name, arguments, context)
        
        return await backend.get(cache_key)
    
    async def put(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any], 
        result: Any,
        ttl: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """缓存工具执行结果"""
        backend = self._get_backend(tool_name)
        cache_key = self._generate_cache_key(tool_name, arguments, context)
        
        await backend.put(cache_key, result, ttl)
    
    async def delete(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """删除缓存项"""
        backend = self._get_backend(tool_name)
        cache_key = self._generate_cache_key(tool_name, arguments, context)
        
        return await backend.delete(cache_key)
    
    async def clear(self, tool_name: Optional[str] = None) -> None:
        """清空缓存"""
        if tool_name:
            backend = self._get_backend(tool_name)
            await backend.clear()
        else:
            # 清空所有后端
            for backend in self._backends.values():
                await backend.clear()
    
    async def get_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """获取缓存统计信息"""
        if tool_name:
            backend = self._get_backend(tool_name)
            stats = backend.stats
            return {
                "tool_name": tool_name,
                "stats": stats.__dict__ if stats else None
            }
        else:
            # 返回所有后端的统计信息
            all_stats = {}
            for name, backend in self._backends.items():
                stats = backend.stats
                all_stats[name] = stats.__dict__ if stats else None
            return all_stats
    
    async def close(self):
        """关闭所有缓存后端"""
        for backend in self._backends.values():
            await backend.close()


# 全局缓存管理器实例
global_tool_cache = ToolCache()
