#!/usr/bin/env python3
"""
清空数据库脚本
"""

import asyncio
from sqlalchemy import text
from app.database import engine, Base
from app.models import Chunk

async def clear_database():
    """清空数据库中的所有数据"""
    async with engine.begin() as conn:
        # 删除所有表数据
        await conn.execute(text("DELETE FROM chunks"))
        print("✅ 数据库已清空")

async def drop_and_recreate_tables():
    """删除并重新创建所有表"""
    async with engine.begin() as conn:
        # 删除所有表
        await conn.run_sync(Base.metadata.drop_all)
        # 重新创建所有表
        await conn.run_sync(Base.metadata.create_all)
        print("✅ 数据库表已重新创建")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--recreate":
        asyncio.run(drop_and_recreate_tables())
    else:
        asyncio.run(clear_database()) 