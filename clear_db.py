#!/usr/bin/env python3
"""
清空数据库脚本
"""

import asyncio
from sqlalchemy import text
from app.database import engine, Base
from app.vector_db_client import qdrant_client, COLLECTION_NAME


async def clear_all_data():
    """清空所有数据，包括 SQL 数据库和 Qdrant 向量数据库。"""
    
    # 1. 清空 SQL 数据库
    async with engine.begin() as conn:
        # 使用 TRUNCATE...CASCADE 或者逐个 DELETE
        # 这里我们假设有外键关联，所以需要正确的顺序或者禁用约束
        # 为了简单起见，我们直接删除并重建表
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        print("✅ SQL 数据库表已清空并重建。")

    # 2. 清空 Qdrant 向量数据库
    if qdrant_client:
        try:
            # 检查集合是否存在
            collections_response = qdrant_client.get_collections()
            collection_names = [c.name for c in collections_response.collections]
            
            if COLLECTION_NAME in collection_names:
                print(f"正在删除 Qdrant collection: {COLLECTION_NAME}...")
                qdrant_client.delete_collection(collection_name=COLLECTION_NAME)
                print(f"✅ Qdrant collection '{COLLECTION_NAME}' 已删除。")
            else:
                print(f"Qdrant collection '{COLLECTION_NAME}' 不存在，无需删除。")
                
        except Exception as e:
            print(f"❌ 删除 Qdrant collection 失败: {e}")
    else:
        print("Qdrant 客户端未初始化，跳过清理。")


if __name__ == "__main__":
    print("正在清空所有存储...")
    asyncio.run(clear_all_data())
