"""工具系统配置管理"""
import os
import json
import yaml
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum

from .models import ToolMetadata
from .cache import CacheConfig
from .performance import PerformanceConfig
from .observability import LogLevel


class ConfigSource(str, Enum):
    """配置源类型"""
    ENVIRONMENT = "environment"
    FILE = "file"
    DICT = "dict"
    DEFAULT = "default"


@dataclass
class ToolsConfig:
    """工具系统配置"""
    # 基本配置
    llm_service_url: str = "http://localhost:8000"
    default_timeout: float = 300.0
    max_retries: int = 3
    
    # 缓存配置
    cache: CacheConfig = field(default_factory=lambda: CacheConfig())
    
    # 性能配置
    performance: PerformanceConfig = field(default_factory=lambda: PerformanceConfig())
    
    # 日志配置
    log_level: LogLevel = LogLevel.INFO
    log_file: Optional[str] = None
    structured_logs: bool = True
    
    # 安全配置
    allowed_tools: Optional[List[str]] = None
    disabled_tools: List[str] = field(default_factory=list)
    api_keys: Dict[str, str] = field(default_factory=dict)
    
    # 工具特定配置
    tool_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tool_metadata: Dict[str, ToolMetadata] = field(default_factory=dict)
    
    # 高级配置
    enable_monitoring: bool = True
    enable_caching: bool = True
    enable_batch_processing: bool = True
    debug_mode: bool = False
    
    # 自动发现配置
    auto_discovery: Dict[str, Any] = field(default_factory=lambda: {
        'enabled': True,
        'packages': [],
        'modules': [],
        'directories': []
    })


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self._config: Optional[ToolsConfig] = None
        self._config_sources: List[Dict[str, Any]] = []
        self._watchers: List[callable] = []
    
    def load_from_env(self, prefix: str = "TOOLS_") -> Dict[str, Any]:
        """从环境变量加载配置"""
        config_dict = {}
        
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower()
                
                # 尝试解析复杂类型
                try:
                    # JSON 格式的值
                    if value.startswith('{') or value.startswith('['):
                        config_dict[config_key] = json.loads(value)
                    # 布尔值
                    elif value.lower() in ('true', 'false'):
                        config_dict[config_key] = value.lower() == 'true'
                    # 数字
                    elif value.replace('.', '').replace('-', '').isdigit():
                        config_dict[config_key] = float(value) if '.' in value else int(value)
                    # 字符串
                    else:
                        config_dict[config_key] = value
                except (json.JSONDecodeError, ValueError):
                    config_dict[config_key] = value
        
        self._config_sources.append({
            'source': ConfigSource.ENVIRONMENT,
            'data': config_dict
        })
        
        return config_dict
    
    def load_from_file(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """从文件加载配置"""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {file_path}")
        
        config_dict = {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix.lower() in ['.yml', '.yaml']:
                    config_dict = yaml.safe_load(f) or {}
                elif file_path.suffix.lower() == '.json':
                    config_dict = json.load(f)
                else:
                    raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        
        except Exception as e:
            raise ValueError(f"解析配置文件失败: {e}")
        
        self._config_sources.append({
            'source': ConfigSource.FILE,
            'path': str(file_path),
            'data': config_dict
        })
        
        return config_dict
    
    def load_from_dict(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """从字典加载配置"""
        self._config_sources.append({
            'source': ConfigSource.DICT,
            'data': config_dict.copy()
        })
        
        return config_dict
    
    def merge_configs(self, *config_dicts: Dict[str, Any]) -> Dict[str, Any]:
        """合并多个配置字典"""
        merged = {}
        
        for config_dict in config_dicts:
            self._deep_merge(merged, config_dict)
        
        return merged
    
    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]):
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value
    
    def build_config(self) -> ToolsConfig:
        """构建最终配置"""
        # 从所有源合并配置
        merged_config = {}
        for source_info in self._config_sources:
            self._deep_merge(merged_config, source_info['data'])
        
        # 处理嵌套配置对象
        config_kwargs = {}
        
        for key, value in merged_config.items():
            if key == 'cache' and isinstance(value, dict):
                config_kwargs['cache'] = CacheConfig(**value)
            elif key == 'performance' and isinstance(value, dict):
                config_kwargs['performance'] = PerformanceConfig(**value)
            elif key == 'log_level' and isinstance(value, str):
                config_kwargs['log_level'] = LogLevel(value.upper())
            elif key == 'tool_metadata' and isinstance(value, dict):
                tool_metadata = {}
                for tool_name, metadata_dict in value.items():
                    if isinstance(metadata_dict, dict):
                        tool_metadata[tool_name] = ToolMetadata(**metadata_dict)
                    else:
                        tool_metadata[tool_name] = metadata_dict
                config_kwargs['tool_metadata'] = tool_metadata
            else:
                config_kwargs[key] = value
        
        self._config = ToolsConfig(**config_kwargs)
        return self._config
    
    def get_config(self) -> ToolsConfig:
        """获取当前配置"""
        if self._config is None:
            # 如果没有加载任何配置，返回默认配置
            self._config = ToolsConfig()
        return self._config
    
    def get_tool_config(self, tool_name: str) -> Dict[str, Any]:
        """获取特定工具的配置"""
        config = self.get_config()
        return config.tool_configs.get(tool_name, {})
    
    def get_tool_metadata(self, tool_name: str) -> Optional[ToolMetadata]:
        """获取特定工具的元数据"""
        config = self.get_config()
        return config.tool_metadata.get(tool_name)
    
    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被允许"""
        config = self.get_config()
        
        # 检查是否在禁用列表中
        if tool_name in config.disabled_tools:
            return False
        
        # 检查是否在允许列表中（如果设置了允许列表）
        if config.allowed_tools is not None:
            return tool_name in config.allowed_tools
        
        return True
    
    def update_config(self, updates: Dict[str, Any]):
        """动态更新配置"""
        if self._config is None:
            self._config = ToolsConfig()
        
        # 更新配置
        for key, value in updates.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        
        # 通知观察者
        self._notify_watchers()
    
    def watch_config_changes(self, callback: callable):
        """监听配置变化"""
        self._watchers.append(callback)
    
    def _notify_watchers(self):
        """通知配置变化观察者"""
        for watcher in self._watchers:
            try:
                watcher(self._config)
            except Exception as e:
                print(f"配置变化通知失败: {e}")
    
    def export_config(self, format: str = "dict") -> Union[Dict[str, Any], str]:
        """导出配置"""
        config = self.get_config()
        config_dict = asdict(config)
        
        if format == "dict":
            return config_dict
        elif format == "json":
            return json.dumps(config_dict, indent=2, ensure_ascii=False)
        elif format == "yaml":
            return yaml.dump(config_dict, default_flow_style=False, allow_unicode=True)
        else:
            raise ValueError(f"不支持的导出格式: {format}")
    
    def save_config(self, file_path: Union[str, Path]):
        """保存配置到文件"""
        file_path = Path(file_path)
        
        if file_path.suffix.lower() in ['.yml', '.yaml']:
            content = self.export_config("yaml")
        elif file_path.suffix.lower() == '.json':
            content = self.export_config("json")
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def validate_config(self) -> List[str]:
        """验证配置"""
        errors = []
        config = self.get_config()
        
        # 验证基本配置
        if not config.llm_service_url:
            errors.append("llm_service_url 不能为空")
        
        if config.default_timeout <= 0:
            errors.append("default_timeout 必须大于 0")
        
        if config.max_retries < 0:
            errors.append("max_retries 不能小于 0")
        
        # 验证缓存配置
        if config.cache.ttl_seconds <= 0:
            errors.append("cache.ttl_seconds 必须大于 0")
        
        if config.cache.max_size <= 0:
            errors.append("cache.max_size 必须大于 0")
        
        # 验证性能配置
        if config.performance.max_connections <= 0:
            errors.append("performance.max_connections 必须大于 0")
        
        # 验证工具配置
        for tool_name, metadata in config.tool_metadata.items():
            if metadata.timeout_s <= 0:
                errors.append(f"工具 {tool_name} 的 timeout_s 必须大于 0")
            
            if metadata.max_retries < 0:
                errors.append(f"工具 {tool_name} 的 max_retries 不能小于 0")
        
        return errors
    
    def get_config_info(self) -> Dict[str, Any]:
        """获取配置信息"""
        return {
            'sources': self._config_sources,
            'watchers_count': len(self._watchers),
            'config_loaded': self._config is not None,
            'validation_errors': self.validate_config()
        }


# 全局配置管理器实例
global_config_manager = ConfigManager()


def initialize_config(
    config_file: Optional[Union[str, Path]] = None,
    env_prefix: str = "TOOLS_",
    additional_config: Optional[Dict[str, Any]] = None
) -> ToolsConfig:
    """初始化配置系统"""
    
    config_sources = []
    
    # 1. 加载环境变量配置
    try:
        env_config = global_config_manager.load_from_env(env_prefix)
        if env_config:
            config_sources.append(env_config)
            print(f"从环境变量加载了 {len(env_config)} 个配置项")
    except Exception as e:
        print(f"加载环境变量配置失败: {e}")
    
    # 2. 加载文件配置
    if config_file:
        try:
            file_config = global_config_manager.load_from_file(config_file)
            if file_config:
                config_sources.append(file_config)
                print(f"从文件 {config_file} 加载了配置")
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    
    # 3. 加载额外配置
    if additional_config:
        try:
            global_config_manager.load_from_dict(additional_config)
            config_sources.append(additional_config)
            print(f"加载了额外配置")
        except Exception as e:
            print(f"加载额外配置失败: {e}")
    
    # 4. 构建最终配置
    config = global_config_manager.build_config()
    
    # 5. 验证配置
    validation_errors = global_config_manager.validate_config()
    if validation_errors:
        print("配置验证警告:")
        for error in validation_errors:
            print(f"  - {error}")
    
    print("工具系统配置初始化完成")
    return config


def get_config() -> ToolsConfig:
    """获取全局配置"""
    return global_config_manager.get_config()
