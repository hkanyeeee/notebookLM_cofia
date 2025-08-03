import httpx
from typing import List
from app.config import LLM_SERVICE_URL


DEFAULT_CHAT_MODEL = "qwen3_8b_awq"
# DEFAULT_CHAT_MODEL = "qwen/qwq-32b"

async def generate_answer(question: str, contexts: List[str], model: str = DEFAULT_CHAT_MODEL) -> str:
    """调用 LM Studio OpenAI 兼容 /v1/chat/completions 接口，根据检索到的上下文生成答案。"""
    url = f"{LLM_SERVICE_URL}/chat/completions"

    system_prompt = (
        "你是一位严谨的助手，请阅读提供的参考资料、结合你自己的知识回答用户问题；"
    )
    user_content = "参考资料：\n" + "\n".join(contexts) + f"\n\n用户问题：{question}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.6,
    }

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        # OpenAI 返回格式：choices[0].message.content
        return data["choices"][0]["message"]["content"]
