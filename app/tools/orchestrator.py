"""工具编排器 - Reason → Act → Observation 主循环"""
import asyncio
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
from .models import (
    ToolMode, RunConfig, ToolExecutionContext, Step, StepType,
    ToolSchema
)
from .selector import StrategySelector
from .registry import tool_registry
from .strategies.json_fc import JSONFunctionCallingStrategy
from .strategies.react import ReActStrategy
from .strategies.harmony import HarmonyStrategy


class ToolOrchestrator:
    """工具编排器，负责整个工具执行流程的协调"""
    
    def __init__(self, llm_service_url: str):
        self.llm_service_url = llm_service_url
        self.strategies = {
            ToolMode.JSON: JSONFunctionCallingStrategy(llm_service_url),
            ToolMode.REACT: ReActStrategy(llm_service_url),
            ToolMode.HARMONY: HarmonyStrategy(llm_service_url)
        }
    
    def _select_strategy(self, context: ToolExecutionContext):
        """选择执行策略"""
        # 确定实际使用的策略
        selected_mode = StrategySelector.select_strategy(
            context.run_config.model or "default",
            context.run_config.tool_mode
        )
        
        # 验证策略是否适用于模型
        if not StrategySelector.validate_strategy_for_model(
            selected_mode, context.run_config.model or "default"
        ):
            # 使用回退策略
            selected_mode = StrategySelector.get_fallback_strategy(
                context.run_config.model or "default"
            )
        
        return self.strategies.get(selected_mode)
    
    def _should_continue(self, context: ToolExecutionContext) -> bool:
        """判断是否应该继续执行"""
        # 检查最大步数限制
        if context.current_step >= context.run_config.max_steps:
            return False
        
        # 检查是否已经有最终答案
        if context.steps and context.steps[-1].step_type == StepType.FINAL_ANSWER:
            return False
        
        # 如果没有可用工具，直接结束（让策略处理）
        if not tool_registry.has_tools():
            return False
        
        return True
    
    async def execute_non_stream(
        self,
        question: str,
        contexts: List[str],
        run_config: RunConfig
    ) -> Dict[str, Any]:
        """非流式执行工具编排
        
        Args:
            question: 用户问题
            contexts: 参考上下文
            run_config: 运行配置
            
        Returns:
            包含答案和执行步骤的结果
        """
        context = ToolExecutionContext(
            question=question,
            contexts=contexts,
            run_config=run_config
        )
        
        strategy = self._select_strategy(context)
        if not strategy:
            return {
                "answer": f"不支持的工具模式: {run_config.tool_mode}",
                "steps": [],
                "success": False
            }
        
        # 执行主循环
        try:
            while self._should_continue(context):
                step = await strategy.execute_step(context)
                
                if not step:
                    break
                
                context.add_step(step)
                
                # 如果是最终答案，结束循环
                if step.step_type == StepType.FINAL_ANSWER:
                    break
            
            # 提取最终答案
            final_answer = ""
            if context.steps:
                final_step = context.steps[-1]
                if final_step.step_type == StepType.FINAL_ANSWER:
                    final_answer = final_step.content
                else:
                    # 如果没有明确的最终答案，使用最后的内容
                    final_answer = "执行完成，但未找到明确的最终答案。"
            
            return {
                "answer": final_answer,
                "steps": [
                    {
                        "type": step.step_type.value,
                        "content": step.content,
                        "tool_call": {
                            "name": step.tool_call.name,
                            "arguments": step.tool_call.arguments
                        } if step.tool_call else None,
                        "tool_result": {
                            "name": step.tool_result.name,
                            "result": step.tool_result.result,
                            "success": step.tool_result.success
                        } if step.tool_result else None
                    } for step in context.steps
                ],
                "success": True
            }
            
        except Exception as e:
            return {
                "answer": f"工具执行出错: {str(e)}",
                "steps": [],
                "success": False
            }
    
    async def execute_stream(
        self,
        question: str,
        contexts: List[str],
        run_config: RunConfig
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行工具编排
        
        Args:
            question: 用户问题
            contexts: 参考上下文
            run_config: 运行配置
            
        Yields:
            流式事件数据
        """
        context = ToolExecutionContext(
            question=question,
            contexts=contexts,
            run_config=run_config
        )
        
        strategy = self._select_strategy(context)
        if not strategy:
            yield {
                "type": "error",
                "message": f"不支持的工具模式: {run_config.tool_mode}"
            }
            return
        
        try:
            step_count = 0
            while step_count < run_config.max_steps:
                step_count += 1
                
                # 检查是否应该继续
                if not self._should_continue(context):
                    break
                
                # 流式执行步骤
                step_executed = False
                async for event in strategy.stream_execute_step(context):
                    step_executed = True
                    yield event
                    
                    # 如果是最终答案相关的事件，结束
                    if event.get("type") == "final_answer":
                        return
                
                # 如果没有执行任何步骤，退出循环
                if not step_executed:
                    break
                
                # 小延迟，避免过于频繁的请求
                await asyncio.sleep(0.1)
            
            # 如果达到最大步数，发送完成事件
            if step_count >= run_config.max_steps:
                yield {
                    "type": "complete",
                    "message": f"已达到最大步数限制 ({run_config.max_steps})"
                }
            
        except Exception as e:
            yield {
                "type": "error",
                "message": f"流式执行出错: {str(e)}"
            }
    
    def register_tools_from_config(self, tools: List[Dict[str, Any]]):
        """从配置中注册工具（当前为空实现，后续扩展）"""
        # 当前工具注册表为空，此方法暂不实现具体逻辑
        # 后续可以根据传入的工具配置动态注册工具
        pass
    
    async def validate_setup(self) -> Dict[str, Any]:
        """验证工具系统设置"""
        return {
            "has_tools": tool_registry.has_tools(),
            "tool_count": len(tool_registry.get_all_schemas()),
            "available_tools": [schema.name for schema in tool_registry.get_all_schemas()],
            "supported_strategies": [mode.value for mode in self.strategies.keys()],
            "llm_service_url": self.llm_service_url
        }


# 全局编排器实例（需要在 app 启动时初始化）
_orchestrator: Optional[ToolOrchestrator] = None


def initialize_orchestrator(llm_service_url: str):
    """初始化全局编排器实例"""
    global _orchestrator
    _orchestrator = ToolOrchestrator(llm_service_url)


def get_orchestrator() -> Optional[ToolOrchestrator]:
    """获取全局编排器实例"""
    return _orchestrator
