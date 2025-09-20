import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import DATABASE_URL, LLM_SERVICE_URL
from .database import init_db
from .tools.orchestrator import initialize_orchestrator
from .utils.task_status import ingest_task_manager


async def cleanup_tasks_periodically():
    """定期清理已完成的摄取任务"""
    while True:
        try:
            await asyncio.sleep(3600)  # 每小时清理一次
            await ingest_task_manager.cleanup_completed_tasks(max_age_hours=24)
            print("[定时清理] 已完成摄取任务清理")
        except asyncio.CancelledError:
            print("[定时清理] 清理任务已取消")
            break
        except Exception as e:
            print(f"[定时清理] 清理任务出错：{e}")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    print(f"Using LLM_SERVICE_URL: {LLM_SERVICE_URL}")
    
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
    
    # 启动定时清理任务
    cleanup_task = None
    try:
        cleanup_task = asyncio.create_task(cleanup_tasks_periodically())
        print("任务清理定时器启动成功")
    except Exception as e:
        print(f"任务清理定时器启动失败：{e}")
    
    yield
    
    # 应用关闭时停止清理任务
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        print("任务清理定时器已停止")


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
from .api.ingest import router as ingest_router
from .api.auto_ingest import router as auto_ingest_router
from .api.collections import router as collections_router
from .api.search import router as search_router
from .api.documents import router as documents_router
from .api.query import router as query_router

from .api.models import router as models_router

from .api.webhook import router as webhook_router
from .api.n8n_workflow import router as n8n_workflow_router
from .api.vector_fix import router as vector_fix_router

app.include_router(ingest_router)
app.include_router(auto_ingest_router)
app.include_router(collections_router)
app.include_router(search_router)
app.include_router(documents_router)
app.include_router(query_router)

app.include_router(models_router)

app.include_router(webhook_router)
app.include_router(n8n_workflow_router)
app.include_router(vector_fix_router)
