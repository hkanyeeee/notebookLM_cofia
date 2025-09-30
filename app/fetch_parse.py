import re
import asyncio
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from app.config import PROXY_URL
from app.config import (
    PLAYWRIGHT_WAIT_FOR_FONTS,
    PLAYWRIGHT_WAIT_FOR_DOM_STABLE,
    PLAYWRIGHT_DOM_STABLE_MS,
    PLAYWRIGHT_TEXT_STABLE_CHECKS,
    PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS,
    PLAYWRIGHT_MIN_CHARS,
    PLAYWRIGHT_MAX_NODES_CHECK,
    PLAYWRIGHT_SCROLL_STEPS,
    PLAYWRIGHT_SCROLL_INTERVAL_MS,
    PLAYWRIGHT_CANDIDATE_SELECTORS,
)
from app.services.network import (
    get_httpx_client,
    get_playwright_browser,
    get_playwright_semaphore,
    initialize_network_resources,
    get_playwright_context,
    is_playwright_persistent_enabled,
    apply_stealth_if_enabled,
)

# =========================
# 1) 原有：抓原始 HTML（轻改：更稳的等待 & UA）
# =========================
async def fetch_html(url: str, timeout: float = 10.0) -> str:
    """
    使用 httpx 异步获取网页原始 HTML；如果失败则使用 Playwright 渲染并获取页面静态 DOM。
    注意：此方法返回的是静态 DOM（page.content），对纯前端/Shadow DOM/WS 注入的页面可能抓不到正文。
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36)"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    client = get_httpx_client()
    try:
        resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        # httpx 获取失败，使用 Playwright 进行渲染（静态 DOM）
        try:
            # 懒加载初始化网络资源（例如在独立脚本/任务中直接调用而未启动应用）
            browser = get_playwright_browser()
            semaphore = get_playwright_semaphore()
        except Exception:
            await initialize_network_resources()
            semaphore = get_playwright_semaphore()
        async with semaphore:
            context = await get_playwright_context()
            page = await context.new_page()
            try:
                await apply_stealth_if_enabled(page)
            except Exception:
                pass
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                # 轻量滚动以触发懒加载
                try:
                    for _ in range(2):
                        await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")
                        await page.wait_for_timeout(500)
                except Exception:
                    pass
                await page.wait_for_timeout(800)
                content = await page.content()
            except PlaywrightTimeoutError:
                content = await page.content()
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                if not is_playwright_persistent_enabled():
                    try:
                        await context.close()
                    except Exception:
                        pass
            return content

# =========================
# 2) 方案 A：读取渲染后的可见文本（可穿透 Shadow DOM）
# =========================
async def fetch_rendered_text(
    url: str,
    selector: str | None = "article",
    timeout: float = 10.0,
    min_chars: int | None = None,
    max_nodes_check: int | None = None,
) -> str:
    """
    使用 Playwright 渲染并提取页面“可见文本”（优先正文区域），面向通用爬取。

    参数说明：
    - url: 目标地址
    - selector: 优先选择器。若提供，将被加入候选选择器列表的首位；否则仅使用配置项 PLAYWRIGHT_CANDIDATE_SELECTORS。
    - timeout: 总等待时长（秒），影响“文本稳定”轮询次数。
    - min_chars: 文本长度阈值。None 时采用配置 PLAYWRIGHT_MIN_CHARS。
    - max_nodes_check: 每个选择器最多检查的节点数。None 时采用配置 PLAYWRIGHT_MAX_NODES_CHECK。

    配置交互：
    - PLAYWRIGHT_WAIT_FOR_FONTS: 若开启，等待 document.fonts.ready 防止 FOIT 导致 innerText 为空。
    - PLAYWRIGHT_WAIT_FOR_DOM_STABLE + PLAYWRIGHT_DOM_STABLE_MS: 通过 MutationObserver 等待 DOM 子树在指定毫秒内无变更。
    - PLAYWRIGHT_CANDIDATE_SELECTORS: 候选正文选择器列表；本函数不再硬编码默认候选，全部来源于配置（加上可选的 selector）。
    - PLAYWRIGHT_TEXT_STABLE_CHECKS / PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS: 文本稳定性判定（连续 N 次长度不变）。
    - PLAYWRIGHT_SCROLL_STEPS / PLAYWRIGHT_SCROLL_INTERVAL_MS: 轻量滚动触发懒加载。
    - 其他拟真/上下文/并发配置由 app.services.network 管理。
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36)"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        browser = get_playwright_browser()
        semaphore = get_playwright_semaphore()
    except Exception:
        await initialize_network_resources()
        semaphore = get_playwright_semaphore()
    async with semaphore:
        context = await get_playwright_context()
        page = await context.new_page()
        try:
            await apply_stealth_if_enabled(page)
        except Exception:
            pass
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)

            # 等待 Web 字体（可选，防止 FOIT 导致 innerText 为空）
            if PLAYWRIGHT_WAIT_FOR_FONTS:
                try:
                    await page.evaluate("document.fonts && document.fonts.ready")
                except Exception:
                    pass

            # 轻量滚动触发懒加载
            try:
                steps = max(1, PLAYWRIGHT_SCROLL_STEPS)
                for _ in range(steps):
                    await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.9))")
                    await page.wait_for_timeout(max(0, PLAYWRIGHT_SCROLL_INTERVAL_MS))
            except Exception:
                pass

            # 等待 DOM 子树稳定（与接口无关，避免永远等待 networkidle）
            if PLAYWRIGHT_WAIT_FOR_DOM_STABLE:
                try:
                    await page.evaluate(
                        "(stableMs) => new Promise((resolve) => {\n"
                        "  const target = document.body;\n"
                        "  let timer;\n"
                        "  timer = setTimeout(() => { obs.disconnect(); resolve(true); }, stableMs);\n"
                        "  const obs = new MutationObserver(() => {\n"
                        "    if (timer) clearTimeout(timer);\n"
                        "    timer = setTimeout(() => { obs.disconnect(); resolve(true); }, stableMs);\n"
                        "  });\n"
                        "  obs.observe(target, { subtree: true, childList: true, attributes: true, characterData: true });\n"
                        "})",
                        PLAYWRIGHT_DOM_STABLE_MS,
                    )
                except Exception:
                    pass

            # 等待候选选择器之一；若未提供 selector，使用候选列表
            candidate_selectors = []
            if selector:
                candidate_selectors.append(selector)
            # 合并配置中的候选选择器，去重
            for sel in PLAYWRIGHT_CANDIDATE_SELECTORS:
                if sel not in candidate_selectors:
                    candidate_selectors.append(sel)
            waited = False
            for sel in candidate_selectors:
                try:
                    await page.wait_for_selector(sel, timeout=int(timeout * 500))
                    waited = True
                    break
                except PlaywrightTimeoutError:
                    continue

            async def read_text() -> str:
                # 将多次 inner_text 跨进程调用合并为一次 evaluate，减少往返开销
                try:
                    return await page.evaluate(
                        "(selectors, maxNodes) => {\n"
                        "  const safeText = (el) => (el && el.innerText ? el.innerText.trim() : '');\n"
                        "  let best = '';\n"
                        "  for (const sel of selectors) {\n"
                        "    try {\n"
                        "      const nodes = Array.from(document.querySelectorAll(sel));\n"
                        "      const limit = Math.min(nodes.length, Math.max(1, maxNodes));\n"
                        "      for (let i = 0; i < limit; i++) {\n"
                        "        const t = safeText(nodes[i]);\n"
                        "        if (t && t.length > best.length) best = t;\n"
                        "      }\n"
                        "    } catch (e) { /* ignore */ }\n"
                        "  }\n"
                        "  if (!best) {\n"
                        "    const body = document.body;\n"
                        "    best = safeText(body);\n"
                        "  }\n"
                        "  return best || '';\n"
                        "}",
                        candidate_selectors,
                        (max_nodes_check or PLAYWRIGHT_MAX_NODES_CHECK),
                    )
                except Exception:
                    # 兜底：仍尝试 body.innerText（极端情况下 evaluate 不可用）
                    try:
                        return (await page.locator("body").inner_text()).strip()
                    except Exception:
                        return ""

            # 文本稳定：每 interval 检查一次，连续 checks 次长度不变且达到最小长度
            stable = 0
            last_len = -1
            checks = max(1, PLAYWRIGHT_TEXT_STABLE_CHECKS)
            interval_ms = max(0, PLAYWRIGHT_TEXT_STABLE_INTERVAL_MS)
            # 根据间隔计算循环次数
            max_loops = max(1, int((timeout * 1000) / max(1, interval_ms)))
            for _ in range(max_loops):
                txt = await read_text()
                L = len(txt)
                if L == last_len:
                    stable += 1
                    if stable >= checks and L >= (min_chars or PLAYWRIGHT_MIN_CHARS):
                        return txt
                else:
                    stable = 0
                    last_len = L
                await page.wait_for_timeout(interval_ms)

            # 超时兜底
            txt = await read_text()
            final_min = (min_chars or PLAYWRIGHT_MIN_CHARS)
            if txt and len(txt) >= final_min:
                return txt
            if txt:
                return txt
            raise ValueError("Rendered but empty text.")
        finally:
            try:
                await page.close()
            except Exception:
                pass
            if not is_playwright_persistent_enabled():
                try:
                    await context.close()
                except Exception:
                    pass

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
async def fetch_then_extract(url: str, selector: str = "article", timeout: float = 10.0) -> str:
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
    return await fetch_rendered_text(url, selector=selector, timeout=max(10.0, timeout))

# =========================
# 用法示例
# =========================
# async def main():
#     url = "https://fiction.live/stories/Fiction-liveBench-Feb-21-2025/oQdzQvKHw8JyXbN87"
#     # 你可以根据页面实际结构换 selector，比如 ".content" / "article" / "#main"
#     text = await fetch_then_extract(url, selector="article", timeout=10.0)
#     print(text[:1500])
#
# if __name__ == "__main__":
#     asyncio.run(main())
