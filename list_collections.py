#!/usr/bin/env python3
"""
列出所有Qdrant向量数据库中的collection
"""

import asyncio
from app.vector_db_client import qdrant_client


async def list_collections():
    """列出所有Qdrant中的collection"""
    
    if not qdrant_client:
        print("❌ Qdrant客户端未初始化")
        return []
    
    try:
        # 获取所有collections
        collections_response = qdrant_client.get_collections()
        collection_names = [c.name for c in collections_response.collections]
        
        print("📋 所有可用的collections:")
        print("-" * 50)
        for i, name in enumerate(collection_names, 1):
            print(f"{i}. {name}")
        
        if not collection_names:
            print("没有找到任何collections")
        
        return collection_names
        
    except Exception as e:
        print(f"❌ 获取collections失败: {e}")
        return []


if __name__ == "__main__":
    print("正在获取collections列表...")
    collections = asyncio.run(list_collections())
