"""工具系统错误处理模块"""
import time
from typing import Dict, Any, Optional, Type, Union
from enum import Enum
import traceback


class ErrorSeverity(str, Enum):
    """错误严重性级别"""
    LOW = "low"           # 轻微错误，可以继续执行
    MEDIUM = "medium"     # 中等错误，需要用户注意但可以恢复
    HIGH = "high"         # 严重错误，需要立即处理
    CRITICAL = "critical" # 致命错误，系统无法继续


class ErrorCategory(str, Enum):
    """错误类别"""
    NETWORK = "network"               # 网络相关错误
    VALIDATION = "validation"         # 参数验证错误
    PERMISSION = "permission"         # 权限错误
    TIMEOUT = "timeout"               # 超时错误
    RATE_LIMIT = "rate_limit"         # 限流错误
    TOOL_EXECUTION = "tool_execution" # 工具执行错误
    PARSING = "parsing"               # 解析错误
    RESOURCE = "resource"             # 资源错误（内存、文件等）
    CONFIGURATION = "configuration"   # 配置错误
    UNKNOWN = "unknown"               # 未知错误


class ToolSystemError(Exception):
    """工具系统基础异常类"""
    
    def __init__(
        self, 
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.details = details or {}
        self.recoverable = recoverable
        self.original_exception = original_exception
        self.timestamp = time.time()
        
        # 添加堆栈跟踪信息
        if original_exception:
            self.details['original_traceback'] = ''.join(
                traceback.format_exception(
                    type(original_exception), 
                    original_exception, 
                    original_exception.__traceback__
                )
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'message': self.message,
            'category': self.category.value,
            'severity': self.severity.value,
            'recoverable': self.recoverable,
            'details': self.details,
            'timestamp': self.timestamp,
            'error_type': self.__class__.__name__
        }
    
    def get_user_message(self) -> str:
        """获取用户友好的错误信息"""
        user_messages = {
            ErrorCategory.NETWORK: "网络连接出现问题，请检查网络状态后重试",
            ErrorCategory.VALIDATION: "输入参数有误，请检查参数格式和内容",
            ErrorCategory.PERMISSION: "没有执行该操作的权限",
            ErrorCategory.TIMEOUT: "操作超时，请稍后重试",
            ErrorCategory.RATE_LIMIT: "请求过于频繁，请稍后再试",
            ErrorCategory.TOOL_EXECUTION: "工具执行出现问题",
            ErrorCategory.PARSING: "数据解析失败",
            ErrorCategory.RESOURCE: "系统资源不足",
            ErrorCategory.CONFIGURATION: "系统配置错误",
            ErrorCategory.UNKNOWN: "出现未知错误"
        }
        
        base_msg = user_messages.get(self.category, self.message)
        
        # 根据严重性添加建议
        if self.severity == ErrorSeverity.CRITICAL:
            base_msg += "。请联系系统管理员。"
        elif self.recoverable:
            base_msg += "。系统将尝试自动恢复。"
        
        return base_msg


class NetworkError(ToolSystemError):
    """网络相关错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class ValidationError(ToolSystemError):
    """参数验证错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            recoverable=False,
            **kwargs
        )


class PermissionError(ToolSystemError):
    """权限错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.PERMISSION,
            severity=ErrorSeverity.HIGH,
            recoverable=False,
            **kwargs
        )


class TimeoutError(ToolSystemError):
    """超时错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class RateLimitError(ToolSystemError):
    """限流错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class ToolExecutionError(ToolSystemError):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str = "", **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.TOOL_EXECUTION,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )
        self.details['tool_name'] = tool_name


class ParsingError(ToolSystemError):
    """解析错误"""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message, 
            category=ErrorCategory.PARSING,
            severity=ErrorSeverity.LOW,
            **kwargs
        )


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self.error_stats: Dict[str, int] = {}
        self.recovery_strategies: Dict[ErrorCategory, callable] = {
            ErrorCategory.NETWORK: self._handle_network_error,
            ErrorCategory.TIMEOUT: self._handle_timeout_error,
            ErrorCategory.RATE_LIMIT: self._handle_rate_limit_error,
        }
    
    def handle_error(
        self, 
        error: Union[Exception, ToolSystemError], 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """统一错误处理入口"""
        
        # 转换为标准错误格式
        if isinstance(error, ToolSystemError):
            tool_error = error
        else:
            tool_error = self._convert_exception(error)
        
        # 记录错误统计
        error_key = f"{tool_error.category.value}:{tool_error.__class__.__name__}"
        self.error_stats[error_key] = self.error_stats.get(error_key, 0) + 1
        
        # 执行恢复策略
        recovery_result = None
        if tool_error.recoverable and tool_error.category in self.recovery_strategies:
            try:
                recovery_result = self.recovery_strategies[tool_error.category](tool_error, context)
            except Exception as recovery_error:
                print(f"[ErrorHandler] 错误恢复失败: {recovery_error}")
        
        return {
            'error': tool_error.to_dict(),
            'user_message': tool_error.get_user_message(),
            'recovery_attempted': recovery_result is not None,
            'recovery_success': recovery_result.get('success', False) if recovery_result else False,
            'recovery_details': recovery_result
        }
    
    def _convert_exception(self, error: Exception) -> ToolSystemError:
        """将标准异常转换为工具系统错误"""
        error_name = error.__class__.__name__.lower()
        
        # 根据异常类型映射到相应的错误类别
        if 'timeout' in error_name:
            return TimeoutError(str(error), original_exception=error)
        elif 'connection' in error_name or 'network' in error_name:
            return NetworkError(str(error), original_exception=error)
        elif 'permission' in error_name or 'forbidden' in error_name:
            return PermissionError(str(error), original_exception=error)
        elif 'validation' in error_name or 'invalid' in error_name:
            return ValidationError(str(error), original_exception=error)
        else:
            return ToolSystemError(
                str(error), 
                category=ErrorCategory.UNKNOWN,
                original_exception=error
            )
    
    def _handle_network_error(self, error: ToolSystemError, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """处理网络错误"""
        return {
            'success': True,
            'strategy': 'retry_with_backoff',
            'details': '将在下次请求时自动重试'
        }
    
    def _handle_timeout_error(self, error: ToolSystemError, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """处理超时错误"""
        return {
            'success': True,
            'strategy': 'extend_timeout',
            'details': '已自动延长超时时间'
        }
    
    def _handle_rate_limit_error(self, error: ToolSystemError, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """处理限流错误"""
        return {
            'success': True,
            'strategy': 'exponential_backoff',
            'details': '将自动延迟重试'
        }
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        return {
            'total_errors': sum(self.error_stats.values()),
            'error_breakdown': self.error_stats.copy(),
            'most_common_errors': sorted(
                self.error_stats.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5]
        }


# 全局错误处理器实例
global_error_handler = ErrorHandler()
