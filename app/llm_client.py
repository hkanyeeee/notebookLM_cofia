import httpx
from typing import List
from app.config import LLM_SERVICE_URL


DEFAULT_CHAT_MODEL = "gpt-3.5-turbo"

async def generate_answer(question: str, contexts: List[str], model: str = DEFAULT_CHAT_MODEL) -> str:
    """调用 LM Studio OpenAI 兼容 /v1/chat/completions 接口，根据检索到的上下文生成答案。"""
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位检索增强问答助手，请结合提供的参考资料回答用户问题；"
        "若无法从资料中得到答案，请直接回答不知道，不要编造。"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        # OpenAI 返回格式：choices[0].message.content
        return data["choices"][0]["message"]["content"]
