import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import DATABASE_URL
from app.models import Base, Source, Chunk  # 显式导入模型，确保注册

from sqlalchemy import event

# 针对 SQLite 并发写入容易数据库锁定的问题，增加 WAL + busy_timeout 设置
is_sqlite = DATABASE_URL.startswith("sqlite")

connect_args = {}
if is_sqlite:
    # 30 秒等待锁释放，允许跨线程/异步并发
    connect_args = {"timeout": 30, "check_same_thread": False}

# 异步数据库引擎
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
)

# 如果是 SQLite，再添加 WAL 与 busy_timeout 等 PRAGMA 设置
if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # 开启 WAL，提高并发读写能力
        cursor.execute("PRAGMA journal_mode=WAL")
        # 降低同步级别，换取性能
        cursor.execute("PRAGMA synchronous=NORMAL")
        # 设置锁等待时间
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

# 异步会话工厂
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db():
    """
    初始化数据库，根据模型创建所有的表
    """
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)  # 如果需要，可以取消注释以在启动时清空数据库
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created.")


async def get_db():
    """
    FastAPI 依赖项，用于获取数据库会话
    """
    async with AsyncSessionLocal() as session:
        yield session
