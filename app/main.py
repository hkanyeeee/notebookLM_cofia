from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import DATABASE_URL
from .database import init_db


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    try:
        await init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        # 可选：重新抛出异常以阻止应用启动
        # raise e
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
from .api.search import router as search_router
from .api.documents import router as documents_router
from .api.query import router as query_router
from .api.export import router as export_router

app.include_router(ingest_router)
app.include_router(search_router)
app.include_router(documents_router)
app.include_router(query_router)
app.include_router(export_router)
