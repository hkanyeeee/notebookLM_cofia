import re
import asyncio
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from app.config import PROXY_URL

# =========================
# 1) 原有：抓原始 HTML（轻改：更稳的等待 & UA）
# =========================
async def fetch_html(url: str, timeout: float = 15.0) -> str:
    """
    使用 httpx 异步获取网页原始 HTML；如果失败则使用 Playwright 渲染并获取页面静态 DOM。
    注意：此方法返回的是静态 DOM（page.content），对纯前端/Shadow DOM/WS 注入的页面可能抓不到正文。
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36)"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        proxy = PROXY_URL if PROXY_URL else None
        async with httpx.AsyncClient(trust_env=True, headers=headers, proxies=proxy) as client:
            resp = await client.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
    except Exception:
        # httpx 获取失败，使用 Playwright 进行渲染（静态 DOM）
        async with async_playwright() as p:
            launch_kwargs = {"headless": True}
            browser = await p.chromium.launch(**launch_kwargs)
            context_kwargs = {"user_agent": headers["User-Agent"]}
            if PROXY_URL:
                context_kwargs["proxy"] = {"server": PROXY_URL}
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            try:
                # 不用 networkidle（WS 永远忙），用 domcontentloaded
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                # 稍等一会儿让同步脚本跑完
                await page.wait_for_timeout(800)
                content = await page.content()
            except PlaywrightTimeoutError:
                content = await page.content()
            finally:
                await context.close()
                await browser.close()
            return content

# =========================
# 2) 方案 A：读取渲染后的可见文本（可穿透 Shadow DOM）
# =========================
async def fetch_rendered_text(
    url: str,
    selector: str | None = "article",
    timeout: float = 15.0,
    min_chars: int = 200,
    max_nodes_check: int = 20,
) -> str:
    """
    用 Playwright 真渲染并直接读取可见文本（包括 Shadow DOM 渲染后的文本）。
    - 若提供 selector：优先返回该元素（或其中文本最长的一个）的 innerText
    - 否则：返回 body.innerText
    - 采用“文本长度稳定”策略等待前端/WS 异步渲染完成
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36)"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context_kwargs = {"user_agent": headers["User-Agent"]}
        if PROXY_URL:
            # Playwright 代理应设置在 context 层
            context_kwargs["proxy"] = {"server": PROXY_URL}
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            if selector:
                try:
                    await page.wait_for_selector(selector, timeout=timeout * 1000)
                except PlaywrightTimeoutError:
                    # 没等到也继续，走通用读取
                    pass

            async def read_text() -> str:
                if selector:
                    loc = page.locator(selector)
                    count = await loc.count()
                    if count == 0:
                        return ""
                    texts = []
                    limit = min(count, max_nodes_check)
                    for i in range(limit):
                        try:
                            t = await loc.nth(i).inner_text()
                            if t:
                                texts.append(t)
                        except Exception:
                            pass
                    return max(texts, key=len, default="").strip()
                else:
                    try:
                        return (await page.locator("body").inner_text()).strip()
                    except Exception:
                        return ""

            # 文本稳定：每 500ms 检查一次，连续 3 次长度不变且达到最小长度
            stable = 0
            last_len = -1
            # 最多等待 timeout 秒（*2 是因为 0.5s 一次）
            for _ in range(int(timeout * 2)):
                txt = await read_text()
                L = len(txt)
                if L == last_len:
                    stable += 1
                    if stable >= 3 and L >= min_chars:
                        return txt
                else:
                    stable = 0
                    last_len = L
                await page.wait_for_timeout(500)

            # 超时兜底
            txt = await read_text()
            if txt and len(txt) >= min_chars:
                return txt
            if txt:
                return txt
            raise ValueError("Rendered but empty text.")
        finally:
            await context.close()
            await browser.close()

# =========================
# 3) 你的正文提取器（保留 selector 语义 + 回退策略）
# =========================
def extract_text(html: str, selector: str = "article") -> str:
    """
    优先按 selector 抓取；若失败或文本过少，再回退到多策略提取。
    - selector 支持 CSS 选择器（优先使用 soup.select）
    - 如果 CSS 语法不合法，则尝试当作标签名 soup.find(selector)
    """
    soup = BeautifulSoup(html, "html.parser")

    # ------ 清理噪声 ------
    for tag in soup(["script", "style", "header", "footer", "nav", "aside", "noscript", "iframe"]):
        tag.decompose()

    def node_text(n):
        return n.get_text(separator="\n", strip=True)

    STRICT_SELECTOR = False
    MIN_LEN = 200  # 过短则认为不够“正文”，触发回退（仅在非严格模式）

    # ------ 1) 按 selector 抓取 ------
    if selector:
        try:
            nodes = soup.select(selector)
            if nodes:
                if all(n.name and n.name.lower() == "p" for n in nodes):
                    text = "\n\n".join(node_text(n) for n in nodes if node_text(n))
                else:
                    best = max(nodes, key=lambda n: len(node_text(n)))
                    text = node_text(best)

                if STRICT_SELECTOR or (text and len(text) >= MIN_LEN):
                    return text
                elif text and not STRICT_SELECTOR:
                    selector_text_fallback = text
                else:
                    selector_text_fallback = None
            else:
                selector_text_fallback = None
        except Exception:
            try:
                node = soup.find(selector)
                text = node_text(node) if node else ""
                if STRICT_SELECTOR or (text and len(text) >= MIN_LEN):
                    return text
                selector_text_fallback = text or None
            except Exception:
                selector_text_fallback = None
    else:
        selector_text_fallback = None

    # ------ 2) 常见结构：<article>/<main> ------
    for name in ("article", "main"):
        n = soup.find(name)
        if n:
            text = node_text(n)
            if text and len(text) >= MIN_LEN:
                return text

    # ------ 3) 常见内容容器（id/class 含关键字） ------
    candidates = []
    for n in soup.find_all(["div", "section"]):
        id_cls = " ".join(filter(None, [n.get("id", ""), *n.get("class", [])]))
        if re.search(r"\b(content|article|post|main|body|entry|read|page|detail|text)\b", id_cls, re.I):
            text = node_text(n)
            if len(text) >= MIN_LEN:
                candidates.append((len(text), n))
    if candidates:
        best = max(candidates, key=lambda x: x[0])[1]
        return node_text(best)

    # ------ 4) Readability 提取（可选：pip install readability-lxml） ------
    try:
        from readability import Document
        doc = Document(str(soup))
        cleaned_html = doc.summary()
        clean_soup = BeautifulSoup(cleaned_html, "html.parser")
        text = clean_soup.get_text(separator="\n", strip=True)
        if text and len(text) >= MIN_LEN:
            return text
    except Exception:
        pass

    # ------ 5) trafilatura 提取（可选：pip install trafilatura） ------
    try:
        import trafilatura
        text = trafilatura.extract(str(soup), include_comments=False, include_tables=False)
        if text and len(text) >= MIN_LEN:
            return text
    except Exception:
        pass

    # ------ 6) <p> 兜底 ------
    paragraphs = [node_text(p) for p in soup.find_all("p")]
    if paragraphs:
        text = "\n\n".join(p for p in paragraphs if p)
        if text:
            return text

    # ------ 7) 如果 selector 之前有抓到但偏短，最后兜底返回它 ------
    if selector_text_fallback:
        return selector_text_fallback

    raise ValueError("Could not extract any content from the URL.")

# =========================
# 4) 封装：先静态抓 + 解析，失败再用方案 A
# =========================
async def fetch_then_extract(url: str, selector: str = "article", timeout: float = 15.0) -> str:
    """
    调用顺序：
      1) httpx 抓原始 HTML + extract_text 解析
      2) 如果失败或为空，再用 Playwright 渲染 innerText（方案 A）
    """
    html = ""
    try:
        html = await fetch_html(url, timeout=timeout)
    except Exception:
        pass

    if html:
        try:
            text = extract_text(html, selector=selector)
            if text and len(text.strip()) >= 1:
                return text
        except Exception:
            pass

    # 走方案 A
    return await fetch_rendered_text(url, selector=selector, timeout=max(15.0, timeout))

# =========================
# 用法示例
# =========================
# async def main():
#     url = "https://fiction.live/stories/Fiction-liveBench-Feb-21-2025/oQdzQvKHw8JyXbN87"
#     # 你可以根据页面实际结构换 selector，比如 ".content" / "article" / "#main"
#     text = await fetch_then_extract(url, selector="article", timeout=15.0)
#     print(text[:1500])
#
# if __name__ == "__main__":
#     asyncio.run(main())
