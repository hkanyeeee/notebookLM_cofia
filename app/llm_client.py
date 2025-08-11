import httpx
from typing import List
from app.config import LLM_SERVICE_URL


# DEFAULT_CHAT_MODEL = "qwen3-30b-a3b-thinking-2507-mlx"
# DEFAULT_CHAT_MODEL = "openai/gpt-oss-20b"
DEFAULT_CHAT_MODEL = "qwen3_8b_awq"

async def generate_answer(question: str, contexts: List[str], model: str = DEFAULT_CHAT_MODEL) -> str:
    """调用 LM Studio OpenAI 兼容 /v1/chat/completions 接口，根据检索到的上下文生成答案。"""
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料，提取有效信息、排除数据杂音，最终结合你自己的知识提供直击题干的回答；你拿到的参考资料是经过排序的数组，数组中排序在前的资料与问题更相关；回答中不要带有可能、大概、也许这些不确定的词，且必须使用中文进行回答"
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

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        # OpenAI 返回格式：choices[0].message.content
        return data["choices"][0]["message"]["content"]
