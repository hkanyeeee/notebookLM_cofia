import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import DATABASE_URL
from app.models import Base, Source, Chunk  # 显式导入模型，确保注册

# 异步数据库引擎
engine = create_async_engine(DATABASE_URL, echo=True, future=True)

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
