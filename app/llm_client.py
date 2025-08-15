import httpx
import json
from typing import AsyncGenerator, List
from app.config import LLM_SERVICE_URL


# DEFAULT_CHAT_MODEL = "qwen3-30b-a3b-thinking-2507-mlx"
DEFAULT_CHAT_MODEL = "qwen3-30b-a3b-thinking-2507-mlx"
# DEFAULT_CHAT_MODEL = "qwen3_8b_awq"

async def generate_answer(question: str, contexts: List[str], model: str = DEFAULT_CHAT_MODEL) -> str:
    """调用 LM Studio OpenAI 兼容 /v1/chat/completions 接口，根据检索到的上下文生成答案。"""
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科，必须使用中文进行回答"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
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
) -> AsyncGenerator[str, None]:
    """以 OpenAI 流式接口风格，逐块产出内容增量。

    约定：后端 LLM 服务兼容 /v1/chat/completions，开启 payload["stream"] = True 后返回如下格式的 SSE：
      data: {"id":..., "choices":[{"delta":{"content":"..."}}], ...}
      data: {"id":..., "choices":[{"delta":{"content":"..."}}], ...}
      data: [DONE]
    本函数会把每个 delta.content 直接 yield 给调用方。
    """
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，根据问题进行多角度推理，最终结合你自己的知识提供直击题干的回答和分析；你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；回答中不要带有可能、大概、也许这些不确定的词，不要带有根据参考资料、根据获得文本、根据获得信息等字眼，你的回答不应该是照本宣科，必须使用中文进行回答"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
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
                        content = delta.get("reasoning_content") or delta.get("content")
                        if content:
                            yield content
                    except Exception:
                        # 忽略无法解析的行
                        continue
