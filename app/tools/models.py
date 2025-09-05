"""工具系统数据结构定义"""
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel


class ToolMode(str, Enum):
    """工具模式枚举"""
    OFF = "off"          # 关闭工具功能，完全使用现有问答逻辑
    AUTO = "auto"        # 自动选择策略
    JSON = "json"        # JSON Function Calling
    REACT = "react"      # ReAct 提示范式
    HARMONY = "harmony"  # Harmony DSL 标签范式


class ToolSchema(BaseModel):
    """工具定义 Schema"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 格式的参数定义
    
    class Config:
        extra = "forbid"


class ToolCall(BaseModel):
    """工具调用"""
    name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None  # 用于 OpenAI 兼容格式
    
    class Config:
        extra = "forbid"


class ToolResult(BaseModel):
    """工具执行结果"""
    name: str
    result: Union[str, Dict[str, Any]]
    success: bool = True
    error: Optional[str] = None
    call_id: Optional[str] = None
    
    class Config:
        extra = "forbid"


class StepType(str, Enum):
    """步骤类型"""
    REASONING = "reasoning"      # 思考
    ACTION = "action"           # 工具调用
    OBSERVATION = "observation" # 工具结果观察
    FINAL_ANSWER = "final_answer"  # 最终答案


class Step(BaseModel):
    """执行步骤"""
    step_type: StepType
    content: str
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
    
    class Config:
        extra = "forbid"


class RunConfig(BaseModel):
    """运行配置"""
    tool_mode: ToolMode = ToolMode.AUTO
    tools: List[ToolSchema] = []
    max_steps: Optional[int] = None  # 默认为None，将从配置文件读取
    model: Optional[str] = None
    # 可选：按工具名覆盖的运行控制参数
    tool_timeouts: Optional[Dict[str, float]] = None  # seconds
    tool_max_retries: Optional[Dict[str, int]] = None
    # 运行与步骤超时（秒）
    run_timeout_s: Optional[float] = None
    step_timeout_s: Optional[float] = None
    
    def get_max_steps(self) -> int:
        """获取实际的最大步数，如果未设置则使用配置文件中的 MAX_TOOL_STEPS"""
        if self.max_steps is not None:
            return self.max_steps
        try:
            from ..config import MAX_TOOL_STEPS
            return MAX_TOOL_STEPS
        except ImportError:
            return 5  # 兜底默认值
    
    class Config:
        extra = "forbid"


class ToolMetadata(BaseModel):
    """工具元数据与运行控制（注册时可选提供）"""
    timeout_s: float = 1800.0  # 30分钟
    max_retries: int = 1
    max_concurrency: int = 8
    description_override: Optional[str] = None
    # 缓存配置
    cache_enabled: bool = True
    cache_ttl: Optional[float] = None  # 如果不设置，使用默认TTL
    cache_max_size: Optional[int] = None
    # 预留：未来可加入 rate_limit, circuit breaker 等
    
    class Config:
        extra = "forbid"


class ToolExecutionContext(BaseModel):
    """工具执行上下文"""
    question: str
    contexts: List[str]
    run_config: RunConfig
    steps: List[Step] = []
    current_step: int = 0
    conversation_history: Optional[List[Dict[str, str]]] = None
    is_simple_query: bool = False  # 是否为简单查询模式
    
    def add_step(self, step: Step):
        """添加执行步骤"""
        self.steps.append(step)
        self.current_step += 1
        
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史，用于构建 messages"""
        messages = []
        
        # 系统提示会在策略层添加
        
        # 用户问题
        user_content = "参考资料：\n" + "\n".join(self.contexts) + f"\n\n用户问题：{self.question}"
        messages.append({"role": "user", "content": user_content})
        
        # 添加步骤历史
        for step in self.steps:
            if step.step_type == StepType.REASONING:
                # AI 的思考内容
                messages.append({"role": "assistant", "content": step.content})
            elif step.step_type == StepType.ACTION and step.tool_call:
                # 工具调用（根据策略不同，格式会有差异）
                messages.append({"role": "assistant", "content": step.content})
            elif step.step_type == StepType.OBSERVATION and step.tool_result:
                # 工具结果观察
                messages.append({"role": "user", "content": step.content})
                
        return messages
    
    class Config:
        extra = "forbid"
