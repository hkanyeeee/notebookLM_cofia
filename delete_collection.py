#!/usr/bin/env python3
"""
删除指定的Qdrant向量数据库collection
"""

import asyncio
import sys
from app.vector_db_client import qdrant_client


async def delete_collection(collection_name: str):
    """删除指定的collection"""
    
    if not qdrant_client:
        print("❌ Qdrant客户端未初始化")
        return False
    
    try:
        # 检查collection是否存在
        collections_response = qdrant_client.get_collections()
        collection_names = [c.name for c in collections_response.collections]
        
        if collection_name not in collection_names:
            print(f"❌ Collection '{collection_name}' 不存在")
            return False
        
        # 删除collection
        print(f"正在删除 collection: {collection_name}...")
        qdrant_client.delete_collection(collection_name=collection_name)
        print(f"✅ Collection '{collection_name}' 删除成功")
        return True
        
    except Exception as e:
        print(f"❌ 删除collection失败: {e}")
        return False


async def main():
    """主函数"""
    
    if len(sys.argv) != 2:
        print("使用方法: python delete_collection.py <collection_name>")
        print("请先运行 'python list_collections.py' 来查看所有可用的collections")
        return
    
    collection_name = sys.argv[1]
    
    print(f"准备删除collection: {collection_name}")
    success = await delete_collection(collection_name)
    
    if success:
        print("删除操作完成")
    else:
        print("删除操作失败")


if __name__ == "__main__":
    print("正在删除指定的collection...")
    asyncio.run(main())
