"""工具策略选择器"""
from .models import ToolMode, RunConfig
from .registry import tool_registry


class StrategySelector:
    """策略选择器，根据模型和配置选择合适的工具调用策略"""
    
    @staticmethod
    def select_strategy(model: str, tool_mode: ToolMode) -> ToolMode:
        """选择合适的工具策略
        
        Args:
            model: 模型名称
            tool_mode: 用户指定的工具模式
            
        Returns:
            实际使用的工具模式
        """
        # 如果显式指定了策略且不是 auto，直接返回
        if tool_mode != ToolMode.AUTO:
            return tool_mode
        
        # 如果没有可用工具，自动退化为 off 模式
        if not tool_registry.has_tools():
            return ToolMode.OFF
        
        # AUTO 模式下的自动选择逻辑（依据模型名称进行启发式选择）
        # model_name = (model or "").lower()
        # 优先为 GPT-OSS 系列或带有 "oss" 标识的模型启用 Harmony（支持 Channel Commentary / DSL 标注）
        # 暂时禁用
        # if "oss" in model_name or "gpt-oss" in model_name:
        #     return ToolMode.HARMONY
        
        # 其他模型默认使用 JSON Function Calling
        return ToolMode.JSON
    
    @staticmethod
    def should_use_tools(run_config: RunConfig, model: str) -> bool:
        """判断是否应该使用工具功能
        
        Args:
            run_config: 运行配置
            model: 模型名称
            
        Returns:
            是否使用工具功能
        """
        # 显式关闭工具功能
        if run_config.tool_mode == ToolMode.OFF:
            return False
        
        # 没有可用工具
        if not tool_registry.has_tools():
            return False
        
        # 工具列表为空
        if not run_config.tools:
            return False
            
        return True
    
    @staticmethod
    def validate_strategy_for_model(strategy: ToolMode, model: str) -> bool:
        """验证策略是否适用于指定模型
        
        Args:
            strategy: 工具策略
            model: 模型名称
            
        Returns:
            是否适用
        """
        model_name = (model or "").lower()
        # Harmony 更适合支持 Channel Commentary 的模型（如 GPT-OSS 家族）。
        # if strategy == ToolMode.HARMONY:
        #     return ("oss" in model_name or "gpt-oss" in model_name)
        # JSON / ReAct 视为通用可用
        return True
    
    @staticmethod
    def get_fallback_strategy(model: str) -> ToolMode:
        """获取模型的回退策略
        
        当主策略不可用时使用的备选策略
        
        Args:
            model: 模型名称
            
        Returns:
            回退策略
        """
        model_name = (model or "").lower()
        # 对非 OSS 模型回退到 JSON；对 OSS 模型回退到 Harmony
        # if "oss" in model_name or "gpt-oss" in model_name:
        #     return ToolMode.HARMONY
        return ToolMode.JSON
