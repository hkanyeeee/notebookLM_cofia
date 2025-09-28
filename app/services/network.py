import asyncio
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Browser, Playwright

from app.config import (
    PROXY_URL,
    HTTPX_HTTP2_ENABLED,
    HTTPX_MAX_KEEPALIVE_CONNECTIONS,
    HTTPX_MAX_CONNECTIONS,
    PLAYWRIGHT_MAX_CONCURRENCY,
)


# 全局单例资源（由应用 lifespan 管理）
_httpx_client: Optional[httpx.AsyncClient] = None
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_playwright_semaphore: Optional[asyncio.Semaphore] = None


async def initialize_network_resources() -> None:
    """初始化全局 httpx 客户端与 Playwright 浏览器。"""
    global _httpx_client, _playwright, _browser, _playwright_semaphore

    if _httpx_client is None:
        _httpx_client = httpx.AsyncClient(
            trust_env=True,
            http2=HTTPX_HTTP2_ENABLED,
            proxy=PROXY_URL,
            limits=httpx.Limits(
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=HTTPX_MAX_CONNECTIONS,
            ),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    if _playwright is None:
        _playwright = await async_playwright().start()
    if _browser is None:
        # 代理在 context 级别设置，这里保持浏览器干净
        _browser = await _playwright.chromium.launch(headless=True)

    if _playwright_semaphore is None:
        _playwright_semaphore = asyncio.Semaphore(max(1, PLAYWRIGHT_MAX_CONCURRENCY))


async def shutdown_network_resources() -> None:
    """关闭并清理全局 httpx 客户端与 Playwright 浏览器。"""
    global _httpx_client, _playwright, _browser, _playwright_semaphore

    if _httpx_client is not None:
        try:
            await _httpx_client.aclose()
        finally:
            _httpx_client = None

    if _browser is not None:
        try:
            await _browser.close()
        finally:
            _browser = None

    if _playwright is not None:
        try:
            await _playwright.stop()
        finally:
            _playwright = None

    _playwright_semaphore = None


def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None:
        # 懒加载：在未经过 lifespan 初始化时，也提供可用客户端
        _httpx_client = httpx.AsyncClient(
            trust_env=True,
            http2=HTTPX_HTTP2_ENABLED,
            proxy=PROXY_URL,
            limits=httpx.Limits(
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=HTTPX_MAX_CONNECTIONS,
            ),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
    return _httpx_client


def get_playwright_browser() -> Browser:
    if _browser is None:
        raise RuntimeError("Playwright browser is not initialized. Ensure lifespan has started.")
    return _browser


def get_playwright_semaphore() -> asyncio.Semaphore:
    if _playwright_semaphore is None:
        raise RuntimeError("Playwright semaphore is not initialized. Ensure lifespan has started.")
    return _playwright_semaphore


