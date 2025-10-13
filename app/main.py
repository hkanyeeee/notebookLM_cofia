import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import DATABASE_URL, LLM_SERVICE_URL, TIKTOKEN_CACHE_DIR
from .database import init_db
from .tools.orchestrator import initialize_orchestrator
from .services.network import initialize_network_resources, shutdown_network_resources


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    print(f"Using LLM_SERVICE_URL: {LLM_SERVICE_URL}")
    
    # 设置 tiktoken 缓存目录
    import os
    os.environ["TIKTOKEN_CACHE_DIR"] = TIKTOKEN_CACHE_DIR
    print(f"Set TIKTOKEN_CACHE_DIR: {TIKTOKEN_CACHE_DIR}")
    
    # 初始化网络资源（httpx/Playwright 单例）
    try:
        await initialize_network_resources()
        print("Network resources initialized successfully")
    except Exception as e:
        print(f"Network resources initialization failed: {e}")

    # 初始化数据库
    try:
        await init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        # 可选：重新抛出异常以阻止应用启动
        # raise e
    
    # 初始化工具编排器
    try:
        initialize_orchestrator(LLM_SERVICE_URL)
        print("Tool orchestrator initialized successfully")
    except Exception as e:
        print(f"Tool orchestrator initialization failed: {e}")
        # 继续运行，工具功能会自动退化为普通问答
    
    yield

    # 关闭网络资源
    try:
        await shutdown_network_resources()
        print("Network resources shutdown successfully")
    except Exception as e:
        print(f"Network resources shutdown failed: {e}")


app = FastAPI(title="NotebookLM-Py Backend", lifespan=app_lifespan)

# 只允许 192.168.31.* 网段的前端调用，动态生成 1-255 的地址
def generate_lan_origins():
    base = "http://192.168.31."
    return [f"{base}{i}" for i in range(1, 256)] + [
        "http://localhost",
        "http://127.0.0.1"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from .api import (
    ingest_router,
    documents_router,
    search_router,
    query_router,
    models_router,
)

app.include_router(ingest_router, prefix="/api", tags=["ingest"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
app.include_router(search_router, prefix="/api", tags=["search"])
app.include_router(query_router, prefix="/api", tags=["query"])
app.include_router(models_router, prefix="/api", tags=["models"])
