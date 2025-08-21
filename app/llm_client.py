import httpx
import json
from typing import AsyncGenerator, List, Dict, Any
from app.config import LLM_SERVICE_URL
from .tools.models import RunConfig, ToolMode
from .tools.orchestrator import get_orchestrator
from .tools.selector import StrategySelector


# DEFAULT_CHAT_MODEL = "qwen3-30b-a3b-thinking-2507-mlx"
DEFAULT_CHAT_MODEL = "qwen3-30b-a3b-thinking-2507-mlx"
# DEFAULT_CHAT_MODEL = "qwen3_8b_awq"

async def generate_answer(question: str, contexts: List[str], model: str = DEFAULT_CHAT_MODEL) -> str:
    """调用 LM Studio OpenAI 兼容 /v1/chat/completions 接口，根据检索到的上下文生成答案。"""
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科。必须使用中文进行回答"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    print(len(contexts), "contexts")

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        # 优先使用 reasoning_content，其次 content
        message = (data.get("choices") or [{}])[0].get("message", {})
        return message.get("reasoning_content") or message.get("content") or ""


async def stream_answer(
    question: str,
    contexts: List[str],
    model: str = DEFAULT_CHAT_MODEL,
) -> AsyncGenerator[dict, None]:
    """以 OpenAI 流式接口风格，逐块产出内容增量。

    约定：后端 LLM 服务兼容 /v1/chat/completions，开启 payload["stream"] = True 后返回如下格式的 SSE：
      data: {"id":..., "choices":[{"delta":{"content":"..."}}], ...}
      data: {"id":..., "choices":[{"delta":{"content":"..."}}], ...}
      data: [DONE]
    本函数会把每个 delta.content 直接 yield 给调用方。
    """
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科。必须使用中文进行回答"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                # OpenAI 兼容：每行以 data: 开头
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    if data_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        reasoning_content = delta.get("reasoning_content")
                        content = delta.get("content")
                        
                        if reasoning_content:
                            yield {"type": "reasoning", "content": reasoning_content}
                        if content:
                            yield {"type": "content", "content": content}
                    except Exception:
                        # 忽略无法解析的行
                        continue


async def generate_answer_with_tools(
    question: str, 
    contexts: List[str], 
    run_config: RunConfig
) -> Dict[str, Any]:
    """使用工具进行非流式问答
    
    Args:
        question: 用户问题
        contexts: 参考上下文
        run_config: 运行配置（包含工具相关参数）
        
    Returns:
        包含答案和执行步骤的结果
    """
    # 检查是否应该使用工具
    if not StrategySelector.should_use_tools(run_config, run_config.model or DEFAULT_CHAT_MODEL):
        # 退化为普通问答
        answer = await generate_answer(question, contexts, run_config.model or DEFAULT_CHAT_MODEL)
        return {
            "answer": answer,
            "steps": [],
            "success": True,
            "tool_mode": "disabled"
        }
    
    # 使用工具编排器
    orchestrator = get_orchestrator()
    if not orchestrator:
        # 编排器未初始化，退化为普通问答
        answer = await generate_answer(question, contexts, run_config.model or DEFAULT_CHAT_MODEL)
        return {
            "answer": answer,
            "steps": [],
            "success": True,
            "tool_mode": "fallback"
        }
    
    # 设置模型
    if not run_config.model:
        run_config.model = DEFAULT_CHAT_MODEL
    
    result = await orchestrator.execute_non_stream(question, contexts, run_config)
    result["tool_mode"] = run_config.tool_mode.value
    
    return result


async def stream_answer_with_tools(
    question: str,
    contexts: List[str],
    run_config: RunConfig
) -> AsyncGenerator[Dict[str, Any], None]:
    """使用工具进行流式问答
    
    Args:
        question: 用户问题
        contexts: 参考上下文
        run_config: 运行配置（包含工具相关参数）
        
    Yields:
        流式事件数据
    """
    # 检查是否应该使用工具
    if not StrategySelector.should_use_tools(run_config, run_config.model or DEFAULT_CHAT_MODEL):
        # 退化为普通流式问答
        async for delta in stream_answer(question, contexts, run_config.model or DEFAULT_CHAT_MODEL):
            yield delta
        return
    
    # 使用工具编排器
    orchestrator = get_orchestrator()
    if not orchestrator:
        # 编排器未初始化，退化为普通流式问答
        async for delta in stream_answer(question, contexts, run_config.model or DEFAULT_CHAT_MODEL):
            yield delta
        return
    
    # 设置模型
    if not run_config.model:
        run_config.model = DEFAULT_CHAT_MODEL
    
    # 流式执行工具编排
    async for event in orchestrator.execute_stream(question, contexts, run_config):
        yield event
