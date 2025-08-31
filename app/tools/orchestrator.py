"""工具编排器 - Reason → Act → Observation 主循环"""
import asyncio
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
from .models import (
    ToolMode, RunConfig, ToolExecutionContext, Step, StepType,
    ToolSchema
)
from .selector import StrategySelector
from .registry import tool_registry, register_all_tools
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
    
    async def close(self):
        """清理资源，关闭HTTP连接"""
        for strategy in self.strategies.values():
            try:
                await strategy.close()
            except Exception as e:
                print(f"[Orchestrator] 清理策略资源时出错: {e}")
    
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
        if context.current_step >= context.run_config.get_max_steps():
            return False
        
        # 检查是否已经有最终答案
        if context.steps and context.steps[-1].step_type == StepType.FINAL_ANSWER:
            return False
        
        # 如果没有可用工具，直接结束（让策略处理）
        if not tool_registry.has_tools():
            return False
        
        # 检查是否应该继续执行更多步骤
        # 允许工具执行后进行一轮最终回答生成
        
        return True
    
    def _should_force_final_answer(self, context: ToolExecutionContext) -> bool:
        """判断是否应该强制生成最终答案（达到步数限制时）"""
        return context.current_step >= context.run_config.get_max_steps()
    
    async def execute_non_stream(
        self,
        question: str,
        contexts: List[str],
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
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
            run_config=run_config,
            conversation_history=conversation_history
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
            # 运行级别超时
            run_deadline = None
            if run_config.run_timeout_s and run_config.run_timeout_s > 0:
                run_deadline = asyncio.get_event_loop().time() + run_config.run_timeout_s
            while self._should_continue(context):
                if run_deadline is not None and asyncio.get_event_loop().time() >= run_deadline:
                    break
                if run_config.step_timeout_s and run_config.step_timeout_s > 0:
                    step = await asyncio.wait_for(strategy.execute_step(context), timeout=run_config.step_timeout_s)
                else:
                    step = await strategy.execute_step(context)
                
                if not step:
                    break
                
                context.add_step(step)
                
                # 如果是最终答案，结束循环
                if step.step_type == StepType.FINAL_ANSWER:
                    break
            
            # 检查是否需要强制生成最终答案
            final_answer = ""
            if context.steps and context.steps[-1].step_type == StepType.FINAL_ANSWER:
                final_answer = context.steps[-1].content
            elif self._should_force_final_answer(context):
                # 达到最大步数限制，强制生成最终答案
                print(f"[Orchestrator] 达到最大工具调用步数限制({context.run_config.get_max_steps()}步)，强制生成最终答案")
                try:
                    final_step = await strategy.force_final_answer(context)
                    if final_step:
                        context.add_step(final_step)
                        final_answer = final_step.content
                    else:
                        final_answer = "已达到最大工具调用步数限制，但无法生成最终答案。"
                except Exception as e:
                    print(f"[Orchestrator] 强制生成最终答案时出错: {e}")
                    final_answer = f"已达到最大工具调用步数限制，生成最终答案时出错：{str(e)}"
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
        run_config: RunConfig,
        conversation_history: Optional[List[Dict[str, str]]] = None
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
            run_config=run_config,
            conversation_history=conversation_history
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
            max_steps = run_config.get_max_steps()
            
            while step_count < max_steps:
                step_count += 1
                
                # 检查是否应该继续
                if not self._should_continue(context):
                    break
                
                # 流式执行步骤
                step_executed = False
                if run_config.step_timeout_s and run_config.step_timeout_s > 0:
                    # 将流式输出转入内部队列，以便应用超时
                    queue: asyncio.Queue = asyncio.Queue()
                    async def _pump():
                        try:
                            async for ev in strategy.stream_execute_step(context):
                                await queue.put(ev)
                        finally:
                            await queue.put({"__done__": True})
                    task = asyncio.create_task(_pump())
                    try:
                        while True:
                            event = await asyncio.wait_for(queue.get(), timeout=run_config.step_timeout_s)
                            if event.get("__done__"):
                                break
                            step_executed = True
                            yield event
                            if event.get("type") == "final_answer":
                                return
                    finally:
                        task.cancel()
                else:
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
            
            # 如果达到最大步数（按循环计数或上下文累计步数），强制生成最终答案
            # 之前仅依据 step_count 判断，若策略在单轮内添加多个步骤导致 context.current_step 先到上限，
            # 会提前跳出循环且无法进入强制生成分支，导致未产生 final_answer。
            if (step_count >= max_steps or context.current_step >= max_steps) and not (context.steps and context.steps[-1].step_type == StepType.FINAL_ANSWER):
                yield {
                    "type": "info",
                    "message": f"已达到最大工具调用步数限制({max_steps}步)，正在生成最终答案..."
                }
                try:
                    # 流式强制生成最终答案
                    async for event in strategy.stream_force_final_answer(context):
                        yield event
                        if event.get("type") == "final_answer":
                            return
                except Exception as e:
                    yield {
                        "type": "error",
                        "message": f"强制生成最终答案时出错: {str(e)}"
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
    
    # 先注册所有工具（避免循环导入）
    register_all_tools()
    
    # 然后初始化编排器
    _orchestrator = ToolOrchestrator(llm_service_url)


def get_orchestrator() -> Optional[ToolOrchestrator]:
    """获取全局编排器实例"""
    return _orchestrator
