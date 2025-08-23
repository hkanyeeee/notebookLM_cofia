"""工具系统可观测性模块 - 日志、指标和监控"""
import time
import asyncio
import logging
import json
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
import threading
from functools import wraps


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"           # 计数器
    GAUGE = "gauge"              # 测量值
    HISTOGRAM = "histogram"       # 直方图
    TIMER = "timer"              # 计时器


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: float
    level: LogLevel
    message: str
    component: str
    context: Dict[str, Any]
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    
    def to_json(self) -> str:
        """转换为JSON格式"""
        return json.dumps({
            'timestamp': self.timestamp,
            'level': self.level.value,
            'message': self.message,
            'component': self.component,
            'context': self.context,
            'correlation_id': self.correlation_id,
            'user_id': self.user_id
        }, ensure_ascii=False)


@dataclass
class MetricEntry:
    """指标条目"""
    name: str
    type: MetricType
    value: Union[int, float]
    timestamp: float
    labels: Dict[str, str]
    unit: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """性能指标"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    p95_response_time: float = 0.0
    p99_response_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    active_connections: int = 0
    error_rate: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def cache_hit_rate(self) -> float:
        total_cache_requests = self.cache_hits + self.cache_misses
        if total_cache_requests == 0:
            return 0.0
        return self.cache_hits / total_cache_requests


class StructuredLogger:
    """结构化日志记录器"""
    
    def __init__(self, component: str, level: LogLevel = LogLevel.INFO):
        self.component = component
        self.level = level
        self._logs: deque = deque(maxlen=10000)  # 保留最近10000条日志
        self._lock = threading.Lock()
        
        # 配置标准日志
        self.logger = logging.getLogger(f"tools.{component}")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(getattr(logging, level.value))
    
    def _should_log(self, level: LogLevel) -> bool:
        """检查是否应该记录日志"""
        level_order = {
            LogLevel.DEBUG: 0,
            LogLevel.INFO: 1,
            LogLevel.WARNING: 2,
            LogLevel.ERROR: 3,
            LogLevel.CRITICAL: 4
        }
        return level_order[level] >= level_order[self.level]
    
    def _log(self, level: LogLevel, message: str, context: Dict[str, Any], **kwargs):
        """内部日志记录方法"""
        if not self._should_log(level):
            return
        
        log_entry = LogEntry(
            timestamp=time.time(),
            level=level,
            message=message,
            component=self.component,
            context=context,
            **kwargs
        )
        
        with self._lock:
            self._logs.append(log_entry)
        
        # 同时写入标准日志
        log_level = getattr(logging, level.value)
        extra_info = json.dumps(context, ensure_ascii=False) if context else ""
        self.logger.log(log_level, f"{message} {extra_info}")
    
    def debug(self, message: str, **context):
        """记录DEBUG级别日志"""
        self._log(LogLevel.DEBUG, message, context)
    
    def info(self, message: str, **context):
        """记录INFO级别日志"""
        self._log(LogLevel.INFO, message, context)
    
    def warning(self, message: str, **context):
        """记录WARNING级别日志"""
        self._log(LogLevel.WARNING, message, context)
    
    def error(self, message: str, **context):
        """记录ERROR级别日志"""
        self._log(LogLevel.ERROR, message, context)
    
    def critical(self, message: str, **context):
        """记录CRITICAL级别日志"""
        self._log(LogLevel.CRITICAL, message, context)
    
    def get_recent_logs(self, count: int = 100) -> List[LogEntry]:
        """获取最近的日志"""
        with self._lock:
            return list(self._logs)[-count:]


class MetricsCollector:
    """指标收集器"""
    
    def __init__(self):
        self._metrics: Dict[str, List[MetricEntry]] = defaultdict(list)
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = defaultdict(float)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
    
    def counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """记录计数器指标"""
        labels = labels or {}
        key = f"{name}:{json.dumps(labels, sort_keys=True)}"
        
        with self._lock:
            self._counters[key] += value
            self._metrics[name].append(MetricEntry(
                name=name,
                type=MetricType.COUNTER,
                value=value,
                timestamp=time.time(),
                labels=labels
            ))
    
    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """记录测量值指标"""
        labels = labels or {}
        key = f"{name}:{json.dumps(labels, sort_keys=True)}"
        
        with self._lock:
            self._gauges[key] = value
            self._metrics[name].append(MetricEntry(
                name=name,
                type=MetricType.GAUGE,
                value=value,
                timestamp=time.time(),
                labels=labels
            ))
    
    def histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """记录直方图指标"""
        labels = labels or {}
        
        with self._lock:
            self._histograms[name].append(value)
            # 保持最近1000个值
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]
            
            self._metrics[name].append(MetricEntry(
                name=name,
                type=MetricType.HISTOGRAM,
                value=value,
                timestamp=time.time(),
                labels=labels
            ))
    
    def timer(self, name: str, labels: Optional[Dict[str, str]] = None):
        """创建计时器上下文管理器"""
        return TimerContext(self, name, labels or {})
    
    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """获取计数器值"""
        key = f"{name}:{json.dumps(labels or {}, sort_keys=True)}"
        with self._lock:
            return self._counters.get(key, 0.0)
    
    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """获取测量值"""
        key = f"{name}:{json.dumps(labels or {}, sort_keys=True)}"
        with self._lock:
            return self._gauges.get(key, 0.0)
    
    def get_histogram_stats(self, name: str) -> Dict[str, float]:
        """获取直方图统计信息"""
        with self._lock:
            values = self._histograms.get(name, [])
            if not values:
                return {}
            
            sorted_values = sorted(values)
            count = len(sorted_values)
            
            return {
                'count': count,
                'min': sorted_values[0],
                'max': sorted_values[-1],
                'avg': sum(sorted_values) / count,
                'p50': sorted_values[int(count * 0.5)],
                'p95': sorted_values[int(count * 0.95)],
                'p99': sorted_values[int(count * 0.99)]
            }
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有指标"""
        with self._lock:
            return {
                'counters': dict(self._counters),
                'gauges': dict(self._gauges),
                'histograms': {name: self.get_histogram_stats(name) 
                              for name in self._histograms.keys()}
            }


class TimerContext:
    """计时器上下文管理器"""
    
    def __init__(self, collector: MetricsCollector, name: str, labels: Dict[str, str]):
        self.collector = collector
        self.name = name
        self.labels = labels
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = (time.perf_counter() - self.start_time) * 1000  # 毫秒
            self.collector.histogram(self.name, duration, self.labels)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.start_time = time.time()
        self._response_times: deque = deque(maxlen=1000)
        self._lock = threading.Lock()
    
    def record_request(self, duration_ms: float, success: bool, tool_name: str):
        """记录请求"""
        with self._lock:
            self._response_times.append(duration_ms)
        
        # 更新指标
        self.metrics_collector.counter('tool_requests_total', 1.0, {'tool': tool_name})
        self.metrics_collector.counter(
            'tool_requests_status', 1.0, 
            {'tool': tool_name, 'status': 'success' if success else 'error'}
        )
        self.metrics_collector.histogram('tool_request_duration_ms', duration_ms, {'tool': tool_name})
    
    def record_cache_hit(self, tool_name: str, hit: bool):
        """记录缓存命中"""
        self.metrics_collector.counter(
            'tool_cache_requests', 1.0,
            {'tool': tool_name, 'result': 'hit' if hit else 'miss'}
        )
    
    def get_performance_metrics(self) -> PerformanceMetrics:
        """获取性能指标"""
        with self._lock:
            response_times = list(self._response_times)
        
        # 计算响应时间统计
        if response_times:
            sorted_times = sorted(response_times)
            count = len(sorted_times)
            avg_time = sum(sorted_times) / count
            p95_time = sorted_times[int(count * 0.95)] if count > 0 else 0.0
            p99_time = sorted_times[int(count * 0.99)] if count > 0 else 0.0
        else:
            avg_time = p95_time = p99_time = 0.0
        
        # 从指标收集器获取其他数据
        total_requests = self.metrics_collector.get_counter('tool_requests_total')
        successful_requests = self.metrics_collector.get_counter('tool_requests_status', {'status': 'success'})
        failed_requests = self.metrics_collector.get_counter('tool_requests_status', {'status': 'error'})
        cache_hits = self.metrics_collector.get_counter('tool_cache_requests', {'result': 'hit'})
        cache_misses = self.metrics_collector.get_counter('tool_cache_requests', {'result': 'miss'})
        
        return PerformanceMetrics(
            total_requests=int(total_requests),
            successful_requests=int(successful_requests),
            failed_requests=int(failed_requests),
            average_response_time=avg_time,
            p95_response_time=p95_time,
            p99_response_time=p99_time,
            cache_hits=int(cache_hits),
            cache_misses=int(cache_misses),
            error_rate=failed_requests / max(total_requests, 1)
        )


class ToolObservability:
    """工具系统可观测性管理器"""
    
    def __init__(self):
        self.logger = StructuredLogger("tool_system")
        self.performance_monitor = PerformanceMonitor()
        self.metrics_collector = self.performance_monitor.metrics_collector
        
        # 组件日志记录器
        self._component_loggers: Dict[str, StructuredLogger] = {}
    
    def get_logger(self, component: str) -> StructuredLogger:
        """获取组件日志记录器"""
        if component not in self._component_loggers:
            self._component_loggers[component] = StructuredLogger(component)
        return self._component_loggers[component]
    
    def monitor_tool_execution(self, tool_name: str):
        """工具执行监控装饰器"""
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                success = False
                
                logger = self.get_logger(f"tool.{tool_name}")
                logger.info(f"开始执行工具: {tool_name}", tool_name=tool_name, args=str(args), kwargs=str(kwargs))
                
                try:
                    result = await func(*args, **kwargs)
                    success = True
                    logger.info(f"工具执行成功: {tool_name}", tool_name=tool_name, result_type=type(result).__name__)
                    return result
                except Exception as e:
                    logger.error(f"工具执行失败: {tool_name}", tool_name=tool_name, error=str(e), error_type=type(e).__name__)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    self.performance_monitor.record_request(duration_ms, success, tool_name)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                success = False
                
                logger = self.get_logger(f"tool.{tool_name}")
                logger.info(f"开始执行工具: {tool_name}", tool_name=tool_name, args=str(args), kwargs=str(kwargs))
                
                try:
                    result = func(*args, **kwargs)
                    success = True
                    logger.info(f"工具执行成功: {tool_name}", tool_name=tool_name, result_type=type(result).__name__)
                    return result
                except Exception as e:
                    logger.error(f"工具执行失败: {tool_name}", tool_name=tool_name, error=str(e), error_type=type(e).__name__)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    self.performance_monitor.record_request(duration_ms, success, tool_name)
            
            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator
    
    @contextmanager
    def trace_operation(self, operation_name: str, **context):
        """操作追踪上下文管理器"""
        logger = self.get_logger("tracer")
        start_time = time.perf_counter()
        
        logger.info(f"开始操作: {operation_name}", operation=operation_name, **context)
        
        try:
            yield
            logger.info(f"操作完成: {operation_name}", operation=operation_name, **context)
        except Exception as e:
            logger.error(f"操作失败: {operation_name}", operation=operation_name, error=str(e), **context)
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.metrics_collector.histogram(f"operation_duration_ms", duration_ms, {'operation': operation_name})
    
    def get_health_status(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        perf_metrics = self.performance_monitor.get_performance_metrics()
        
        # 判断健康状态
        is_healthy = (
            perf_metrics.error_rate < 0.1 and  # 错误率小于10%
            perf_metrics.average_response_time < 30000  # 平均响应时间小于30秒
        )
        
        return {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'timestamp': time.time(),
            'uptime_seconds': time.time() - self.performance_monitor.start_time,
            'performance': asdict(perf_metrics),
            'metrics': self.metrics_collector.get_all_metrics()
        }


# 全局可观测性实例
global_observability = ToolObservability()
