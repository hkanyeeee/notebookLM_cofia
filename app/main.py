from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import DATABASE_URL, LLM_SERVICE_URL
from .database import init_db
from .tools.orchestrator import initialize_orchestrator


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
    
    yield


app = FastAPI(title="NotebookLM-Py Backend", lifespan=app_lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from .api.ingest import router as ingest_router
from .api.agenttic_ingest import router as agenttic_ingest_router
from .api.collections import router as collections_router
from .api.search import router as search_router
from .api.documents import router as documents_router
from .api.query import router as query_router

from .api.models import router as models_router

from .api.webhook import router as webhook_router
from .api.n8n_workflow import router as n8n_workflow_router
from .api.vector_fix import router as vector_fix_router

app.include_router(ingest_router)
app.include_router(agenttic_ingest_router)
app.include_router(collections_router)
app.include_router(search_router)
app.include_router(documents_router)
app.include_router(query_router)

app.include_router(models_router)

app.include_router(webhook_router)
app.include_router(n8n_workflow_router)
app.include_router(vector_fix_router)
