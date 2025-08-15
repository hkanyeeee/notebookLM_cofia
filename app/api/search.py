import httpx
import json
import re
from fastapi import APIRouter, Body, HTTPException

from ..config import LLM_SERVICE_URL, SEARXNG_QUERY_URL


router = APIRouter()


@router.post("/api/search/generate", summary="Generate web search queries from a topic using LLM")
async def generate_search_queries(
    data: dict = Body(...),
):
    """根据用户输入的课题，调用已配置的 LLM 服务生成 3 个搜索查询。
    返回 {queries: [str, str, str]}。
    """
    topic = data.get("topic", "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic cannot be empty")

    # 使用现有 LLM 服务，以系统提示约束返回 JSON
    prompt_system = (
        "你是搜索查询生成器。给定课题，产出3个多样化、可直接用于网页搜索的英文查询。"
        "返回JSON，键为queries，值为包含3个字符串的数组，不要夹杂多余文本。"
    )
    user_prompt = f"课题：{topic}\n请直接给出 JSON，如：{{'queries': ['...', '...', '...']}}"

    payload = {
        "model": "qwen3-30b-a3b-thinking-2507-mlx",
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{LLM_SERVICE_URL}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 尝试解析为 JSON
            import json as _json
            import re as _re

            try:
                # 去掉可能的代码块包裹 ```json ... ``` / ``` ... ```
                content_stripped = content.strip()
                if content_stripped.startswith("```"):
                    content_stripped = _re.sub(r"^```(?:json)?\\s*|\\s*```$", "", content_stripped)

                # 如果包含 JSON 对象子串，只取第一个对象
                m = _re.search(r"\{[\s\S]*\}", content_stripped)
                json_candidate = m.group(0) if m else content_stripped

                # 先尝试严格 JSON
                parsed = _json.loads(json_candidate)
                queries = parsed.get("queries") or parsed.get("Queries")
                if not isinstance(queries, list):
                    raise ValueError("Invalid schema: queries not list")
                queries = [str(q).strip() for q in queries if str(q).strip()][:3]
                if not queries:
                    raise ValueError("Empty queries")
                # 填满 3 个
                while len(queries) < 3:
                    queries.append(topic)
                return {"queries": queries[:3]}
            except Exception:
                # 宽松处理：把单引号换成双引号再试一次
                try:
                    relaxed = json_candidate.replace("'", '"')
                    parsed2 = _json.loads(relaxed)
                    qs = parsed2.get("queries") or parsed2.get("Queries")
                    if isinstance(qs, list):
                        qs = [str(q).strip() for q in qs if str(q).strip()][:3]
                        while len(qs) < 3:
                            qs.append(topic)
                        return {"queries": qs[:3]}
                except Exception:
                    pass

                # 兜底：按行拆分，过滤可能的 JSON 包裹
                lines = [s.strip() for s in content.split("\n") if s.strip()]
                # 如果第一行就是一个对象字符串，尝试再解析一次
                if lines and (lines[0].startswith("{") and lines[0].endswith("}")):
                    try:
                        obj = _json.loads(lines[0].replace("'", '"'))
                        if isinstance(obj.get("queries"), list):
                            arr = [str(q).strip() for q in obj["queries"] if str(q).strip()]
                            return {"queries": (arr + [topic, f"{topic} 相关问题"])[:3]}
                    except Exception:
                        pass

                queries = lines[:3]
                if not queries:
                    queries = [topic, f"{topic} 关键点", f"{topic} 最新进展"]
                return {"queries": queries[:3]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generate queries failed: {e}")


@router.post("/api/search/searxng", summary="Search web via SearxNG for a given query")
async def search_searxng_api(data: dict = Body(...)):
    """调用 SearxNG /search 接口，按 Open WebUI 行为对齐：
    - 语言固定 en-US
    - time_range / categories 为空
    - 传递 pageno=1、theme=simple、image_proxy=0、safesearch=1
    - 设置与 Open WebUI 相同的请求头
    - 对返回 results 按 score 降序并截断至 count
    """
    query = data.get("query", "").strip()
    count = int(data.get("count", 4))
    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")

    params = {
        "q": query,
        "format": "json",
        "pageno": 1,
        "safesearch": "1",
        "language": "en-US",
        "time_range": "",
        "categories": "",
        "theme": "simple",
        "image_proxy": 0,
    }

    headers = {
        "User-Agent": "Open WebUI (https://github.com/open-webui/open-webui) RAG Bot",
        "Accept": "text/html",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(SEARXNG_QUERY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", [])
            # 对齐 Open WebUI：按 score 降序
            results_sorted = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
            items = []
            for r in results_sorted[:max(1, count)]:
                title = r.get("title") or r.get("name") or "Untitled"
                url = r.get("url") or r.get("link")
                if not url:
                    continue
                items.append({"title": title, "url": url})
            return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SearxNG request failed: {e}")


