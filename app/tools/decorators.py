"""工具注册装饰器和自动发现系统"""
import inspect
import importlib
import importlib.util
import pkgutil
from typing import Any, Dict, List, Optional, Callable, get_type_hints
from functools import wraps
from pathlib import Path

from .models import ToolSchema, ToolMetadata
from .registry import tool_registry


def generate_json_schema_from_function(func: Callable) -> Dict[str, Any]:
    """从函数签名生成JSON Schema"""
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    
    properties = {}
    required = []
    
    for param_name, param in signature.parameters.items():
        # 跳过self参数
        if param_name == 'self':
            continue
        
        param_type = type_hints.get(param_name, type(None))
        param_info = {
            "description": f"参数 {param_name}"
        }
        
        # 根据类型设置JSON Schema类型
        if param_type == str:
            param_info["type"] = "string"
        elif param_type == int:
            param_info["type"] = "integer"
        elif param_type == float:
            param_info["type"] = "number"
        elif param_type == bool:
            param_info["type"] = "boolean"
        elif param_type == list or param_type == List:
            param_info["type"] = "array"
        elif param_type == dict or param_type == Dict:
            param_info["type"] = "object"
        else:
            # 尝试处理泛型类型
            if hasattr(param_type, '__origin__'):
                origin = param_type.__origin__
                if origin == list:
                    param_info["type"] = "array"
                    # 如果有泛型参数，添加items类型
                    if hasattr(param_type, '__args__') and param_type.__args__:
                        item_type = param_type.__args__[0]
                        if item_type == str:
                            param_info["items"] = {"type": "string"}
                        elif item_type == int:
                            param_info["items"] = {"type": "integer"}
                elif origin == dict:
                    param_info["type"] = "object"
                else:
                    param_info["type"] = "string"  # 默认为字符串
            else:
                param_info["type"] = "string"  # 默认为字符串
        
        # 检查是否有默认值
        if param.default != inspect.Parameter.empty:
            param_info["default"] = param.default
        else:
            required.append(param_name)
        
        properties[param_name] = param_info
    
    return {
        "type": "object",
        "properties": properties,
        "required": required
    }


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[ToolMetadata] = None,
    auto_schema: bool = True
):
    """工具注册装饰器
    
    Args:
        name: 工具名称，默认使用函数名
        description: 工具描述，默认使用函数docstring
        metadata: 工具元数据
        auto_schema: 是否自动生成参数schema
        
    Example:
        @tool(description="搜索网络信息")
        def web_search(query: str, language: str = "en-US") -> str:
            '''搜索网络上的信息'''
            # 实现搜索逻辑
            return "搜索结果"
    """
    def decorator(func: Callable):
        # 获取工具名称
        tool_name = name or func.__name__
        
        # 获取工具描述
        tool_description = description or func.__doc__ or f"工具: {tool_name}"
        
        # 生成参数schema
        if auto_schema:
            parameters = generate_json_schema_from_function(func)
        else:
            parameters = {"type": "object", "properties": {}, "required": []}
        
        # 创建工具schema
        schema = ToolSchema(
            name=tool_name,
            description=tool_description.strip(),
            parameters=parameters
        )
        
        # 使用默认元数据或提供的元数据
        tool_metadata = metadata or ToolMetadata()
        
        # 注册工具
        tool_registry.register_tool(schema, func, tool_metadata)
        
        # 添加工具标记到函数，用于自动发现
        func._is_tool = True
        func._tool_name = tool_name
        func._tool_schema = schema
        func._tool_metadata = tool_metadata
        
        return func
    
    return decorator


def batch_tool(*tools_info):
    """批量注册工具装饰器
    
    Args:
        tools_info: 工具信息元组列表 [(name, description, metadata), ...]
        
    Example:
        @batch_tool(
            ("search", "搜索信息", ToolMetadata(timeout_s=60)),
            ("fetch", "获取内容", ToolMetadata(timeout_s=120))
        )
        class SearchTools:
            def search(self, query: str) -> str:
                return "搜索结果"
            
            def fetch(self, url: str) -> str:
                return "页面内容"
    """
    def decorator(cls):
        for tool_info in tools_info:
            tool_name, tool_desc, tool_meta = tool_info
            
            if hasattr(cls, tool_name):
                func = getattr(cls, tool_name)
                
                # 为实例方法创建包装函数
                if inspect.ismethod(func) or inspect.isfunction(func):
                    # 生成参数schema
                    parameters = generate_json_schema_from_function(func)
                    
                    # 创建工具schema
                    schema = ToolSchema(
                        name=tool_name,
                        description=tool_desc,
                        parameters=parameters
                    )
                    
                    # 创建实例化的调用包装器
                    @wraps(func)
                    async def async_wrapper(*args, **kwargs):
                        instance = cls()
                        return await func(instance, *args, **kwargs)
                    
                    @wraps(func)
                    def sync_wrapper(*args, **kwargs):
                        instance = cls()
                        return func(instance, *args, **kwargs)
                    
                    # 根据原函数类型选择包装器
                    if inspect.iscoroutinefunction(func):
                        wrapper = async_wrapper
                    else:
                        wrapper = sync_wrapper
                    
                    # 注册工具
                    tool_registry.register_tool(schema, wrapper, tool_meta)
        
        return cls
    
    return decorator


class ToolDiscovery:
    """工具自动发现系统"""
    
    @staticmethod
    def discover_tools_in_module(module_name: str) -> List[Dict[str, Any]]:
        """在指定模块中发现工具"""
        discovered_tools = []
        
        try:
            module = importlib.import_module(module_name)
            
            for name in dir(module):
                obj = getattr(module, name)
                
                # 检查是否为工具函数
                if hasattr(obj, '_is_tool'):
                    discovered_tools.append({
                        'name': obj._tool_name,
                        'function': obj,
                        'schema': obj._tool_schema,
                        'metadata': obj._tool_metadata,
                        'module': module_name
                    })
        
        except ImportError as e:
            print(f"[ToolDiscovery] 无法导入模块 {module_name}: {e}")
        
        return discovered_tools
    
    @staticmethod
    def discover_tools_in_package(package_name: str) -> List[Dict[str, Any]]:
        """在指定包中递归发现工具"""
        discovered_tools = []
        
        try:
            package = importlib.import_module(package_name)
            package_path = package.__path__
            
            for importer, modname, ispkg in pkgutil.walk_packages(
                package_path, 
                prefix=f"{package_name}."
            ):
                if not ispkg:  # 只处理模块，不处理包
                    tools = ToolDiscovery.discover_tools_in_module(modname)
                    discovered_tools.extend(tools)
        
        except ImportError as e:
            print(f"[ToolDiscovery] 无法导入包 {package_name}: {e}")
        
        return discovered_tools
    
    @staticmethod
    def discover_tools_in_directory(directory: str) -> List[Dict[str, Any]]:
        """在指定目录中发现Python工具文件"""
        discovered_tools = []
        directory_path = Path(directory)
        
        if not directory_path.exists():
            print(f"[ToolDiscovery] 目录不存在: {directory}")
            return discovered_tools
        
        # 查找所有Python文件
        for py_file in directory_path.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            
            # 构建模块名
            relative_path = py_file.relative_to(directory_path)
            module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
            module_name = ".".join(module_parts)
            
            # 尝试导入并发现工具
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    for name in dir(module):
                        obj = getattr(module, name)
                        
                        if hasattr(obj, '_is_tool'):
                            discovered_tools.append({
                                'name': obj._tool_name,
                                'function': obj,
                                'schema': obj._tool_schema,
                                'metadata': obj._tool_metadata,
                                'file': str(py_file)
                            })
            
            except Exception as e:
                print(f"[ToolDiscovery] 处理文件 {py_file} 时出错: {e}")
        
        return discovered_tools
    
    @staticmethod
    def auto_register_discovered_tools(discovered_tools: List[Dict[str, Any]]):
        """自动注册发现的工具"""
        registered_count = 0
        
        for tool_info in discovered_tools:
            try:
                tool_registry.register_tool(
                    tool_info['schema'],
                    tool_info['function'],
                    tool_info['metadata']
                )
                registered_count += 1
                print(f"[ToolDiscovery] 已注册工具: {tool_info['name']}")
            
            except Exception as e:
                print(f"[ToolDiscovery] 注册工具 {tool_info['name']} 失败: {e}")
        
        print(f"[ToolDiscovery] 总共注册了 {registered_count} 个工具")
        return registered_count


def auto_discover_and_register(
    packages: Optional[List[str]] = None,
    modules: Optional[List[str]] = None,
    directories: Optional[List[str]] = None
):
    """自动发现并注册工具
    
    Args:
        packages: 要搜索的包名列表
        modules: 要搜索的模块名列表
        directories: 要搜索的目录路径列表
    """
    discovery = ToolDiscovery()
    all_discovered_tools = []
    
    # 在包中发现工具
    if packages:
        for package_name in packages:
            tools = discovery.discover_tools_in_package(package_name)
            all_discovered_tools.extend(tools)
            print(f"[AutoDiscovery] 在包 {package_name} 中发现 {len(tools)} 个工具")
    
    # 在模块中发现工具
    if modules:
        for module_name in modules:
            tools = discovery.discover_tools_in_module(module_name)
            all_discovered_tools.extend(tools)
            print(f"[AutoDiscovery] 在模块 {module_name} 中发现 {len(tools)} 个工具")
    
    # 在目录中发现工具
    if directories:
        for directory in directories:
            tools = discovery.discover_tools_in_directory(directory)
            all_discovered_tools.extend(tools)
            print(f"[AutoDiscovery] 在目录 {directory} 中发现 {len(tools)} 个工具")
    
    # 注册发现的工具
    if all_discovered_tools:
        discovery.auto_register_discovered_tools(all_discovered_tools)
    else:
        print("[AutoDiscovery] 未发现任何工具")


# 便捷工具元数据创建函数
def quick_metadata(
    timeout: float = 300.0,
    retries: int = 1,
    concurrency: int = 8,
    cache_ttl: Optional[float] = None,
    cache_enabled: bool = True
) -> ToolMetadata:
    """快速创建工具元数据"""
    return ToolMetadata(
        timeout_s=timeout,
        max_retries=retries,
        max_concurrency=concurrency,
        cache_enabled=cache_enabled,
        cache_ttl=cache_ttl
    )
