import asyncio
import atexit
import weakref
import random
from typing import Optional

import httpx
from playwright.async_api import async_playwright, Browser, Playwright, BrowserContext

from app.config import (
    PROXY_URL,
    HTTPX_HTTP2_ENABLED,
    HTTPX_MAX_KEEPALIVE_CONNECTIONS,
    HTTPX_MAX_CONNECTIONS,
    PLAYWRIGHT_MAX_CONCURRENCY,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_PERSISTENT,
    PLAYWRIGHT_USER_DATA_DIR,
    PLAYWRIGHT_STEALTH,
    PLAYWRIGHT_USER_AGENT,
    PLAYWRIGHT_LOCALE,
    PLAYWRIGHT_TIMEZONE,
    PLAYWRIGHT_VIEWPORT_WIDTH,
    PLAYWRIGHT_VIEWPORT_HEIGHT,
    PLAYWRIGHT_EXTRA_ARGS,
)


# 全局单例资源（由应用 lifespan 管理）
_httpx_client: Optional[httpx.AsyncClient] = None
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_playwright_semaphore: Optional[asyncio.Semaphore] = None
_persistent_context: Optional[BrowserContext] = None

# 追踪所有创建的 httpx 客户端，确保都能被关闭
_created_clients: weakref.WeakSet[httpx.AsyncClient] = weakref.WeakSet()
_shutdown_registered = False


async def initialize_network_resources() -> None:
    """初始化全局 httpx 客户端与 Playwright 浏览器。"""
    global _httpx_client, _playwright, _browser, _playwright_semaphore, _persistent_context

    if _httpx_client is None:
        client_kwargs = {
            "trust_env": True,
            "http2": HTTPX_HTTP2_ENABLED,
            "limits": httpx.Limits(
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=HTTPX_MAX_CONNECTIONS,
            ),
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        }
        if PROXY_URL:
            client_kwargs["proxy"] = PROXY_URL
        _httpx_client = httpx.AsyncClient(**client_kwargs)

    if _playwright is None:
        _playwright = await async_playwright().start()
    # 根据是否启用持久化上下文决定启动方式
    if PLAYWRIGHT_PERSISTENT:
        if _persistent_context is None:
            launch_kwargs = {
                "headless": PLAYWRIGHT_HEADLESS,
                "args": PLAYWRIGHT_EXTRA_ARGS,
                "viewport": {
                    "width": PLAYWRIGHT_VIEWPORT_WIDTH + random.randint(0, 48),
                    "height": PLAYWRIGHT_VIEWPORT_HEIGHT + random.randint(0, 48),
                },
                "locale": PLAYWRIGHT_LOCALE,
                "timezone_id": PLAYWRIGHT_TIMEZONE,
                "user_agent": PLAYWRIGHT_USER_AGENT,
            }
            if PROXY_URL:
                launch_kwargs["proxy"] = {"server": PROXY_URL}
            _persistent_context = await _playwright.chromium.launch_persistent_context(
                PLAYWRIGHT_USER_DATA_DIR,
                **launch_kwargs,
            )
        # 非持久化浏览器对象保持为空，防止误用
        _browser = None
    else:
        if _browser is None:
            _browser = await _playwright.chromium.launch(
                headless=PLAYWRIGHT_HEADLESS,
                args=PLAYWRIGHT_EXTRA_ARGS,
            )

    if _playwright_semaphore is None:
        _playwright_semaphore = asyncio.Semaphore(max(1, PLAYWRIGHT_MAX_CONCURRENCY))


async def shutdown_network_resources() -> None:
    """关闭并清理全局 httpx 客户端与 Playwright 浏览器。"""
    global _httpx_client, _playwright, _browser, _playwright_semaphore, _persistent_context

    # 关闭主要的 httpx 客户端
    if _httpx_client is not None:
        try:
            await _httpx_client.aclose()
        except Exception as e:
            print(f"Error closing main httpx client: {e}")
        finally:
            _httpx_client = None

    # 关闭所有可能的懒加载客户端
    clients_to_close = list(_created_clients)
    for client in clients_to_close:
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception as e:
            print(f"Error closing httpx client: {e}")

    if _persistent_context is not None:
        try:
            await _persistent_context.close()
        except Exception as e:
            print(f"Error closing Playwright persistent context: {e}")
        finally:
            _persistent_context = None

    if _browser is not None:
        try:
            await _browser.close()
        except Exception as e:
            print(f"Error closing Playwright browser: {e}")
        finally:
            _browser = None

    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception as e:
            print(f"Error stopping Playwright: {e}")
        finally:
            _playwright = None

    _playwright_semaphore = None


def _register_emergency_cleanup():
    """注册紧急清理函数，在进程退出时确保资源被释放"""
    global _shutdown_registered
    if _shutdown_registered:
        return
    
    def emergency_cleanup():
        """同步版本的紧急清理，仅用于进程退出时"""
        clients_to_close = list(_created_clients)
        for client in clients_to_close:
            try:
                if hasattr(client, '_transport') and client._transport:
                    # 强制关闭传输层，释放连接
                    if hasattr(client._transport, 'close'):
                        client._transport.close()
            except Exception:
                pass
    
    atexit.register(emergency_cleanup)
    _shutdown_registered = True


def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None:
        # 懒加载：在未经过 lifespan 初始化时，也提供可用客户端
        print("[Network] Warning: Creating httpx client outside of lifespan, ensure proper cleanup")
        client_kwargs = {
            "trust_env": True,
            "http2": HTTPX_HTTP2_ENABLED,
            "limits": httpx.Limits(
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=HTTPX_MAX_CONNECTIONS,
            ),
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        }
        if PROXY_URL:
            client_kwargs["proxy"] = PROXY_URL
        _httpx_client = httpx.AsyncClient(**client_kwargs)
        # 追踪这个客户端以确保能被清理
        _created_clients.add(_httpx_client)
        # 注册紧急清理
        _register_emergency_cleanup()
    return _httpx_client


def get_playwright_browser() -> Browser:
    if _browser is None:
        raise RuntimeError("Playwright browser is not initialized (non-persistent mode). Ensure lifespan has started.")
    return _browser


def get_playwright_semaphore() -> asyncio.Semaphore:
    if _playwright_semaphore is None:
        raise RuntimeError("Playwright semaphore is not initialized. Ensure lifespan has started.")
    return _playwright_semaphore


def is_playwright_persistent_enabled() -> bool:
    return PLAYWRIGHT_PERSISTENT and _persistent_context is not None


async def get_playwright_context() -> BrowserContext:
    """获取一个可用的 BrowserContext。
    - 如果启用持久化上下文：返回全局持久化 context
    - 否则：在全局 Browser 上创建新 context 并按配置拟真
    """
    if PLAYWRIGHT_PERSISTENT:
        if _persistent_context is None:
            raise RuntimeError("Persistent context is not initialized. Ensure lifespan has started.")
        # 可设置额外头部
        try:
            await _persistent_context.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" if PLAYWRIGHT_LOCALE.startswith("zh") else "en-US,en;q=0.9",
            })
        except Exception:
            pass
        return _persistent_context
    else:
        browser = get_playwright_browser()
        context_kwargs = {
            "user_agent": PLAYWRIGHT_USER_AGENT,
            "locale": PLAYWRIGHT_LOCALE,
            "timezone_id": PLAYWRIGHT_TIMEZONE,
            "viewport": {
                "width": PLAYWRIGHT_VIEWPORT_WIDTH + random.randint(0, 48),
                "height": PLAYWRIGHT_VIEWPORT_HEIGHT + random.randint(0, 48),
            },
        }
        if PROXY_URL:
            context_kwargs["proxy"] = {"server": PROXY_URL}
        context = await browser.new_context(**context_kwargs)
        try:
            await context.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" if PLAYWRIGHT_LOCALE.startswith("zh") else "en-US,en;q=0.9",
            })
        except Exception:
            pass
        return context


async def apply_stealth_if_enabled(page) -> None:
    """在可用时应用 playwright-stealth。失败时静默跳过。"""
    if not PLAYWRIGHT_STEALTH:
        return
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except Exception as e:
        # 插件缺失或失败时不影响主流程
        print(f"[Network] Stealth 插件未启用或应用失败: {e}")


class NetworkResourcesManager:
    """上下文管理器，用于在独立脚本中安全管理网络资源"""
    
    def __init__(self):
        self._initialized = False
    
    async def __aenter__(self):
        await initialize_network_resources()
        self._initialized = True
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._initialized:
            await shutdown_network_resources()
            self._initialized = False


# 便利函数：用于独立脚本
async def with_network_resources():
    """
    便利函数，用于在独立脚本中使用网络资源
    
    Example:
        async with with_network_resources():
            client = get_httpx_client()
            response = await client.get("https://example.com")
    """
    return NetworkResourcesManager()


