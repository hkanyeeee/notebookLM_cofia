#!/usr/bin/env python3
"""检查Qdrant配置和限制"""
import asyncio
from app.vector_db_client import qdrant_client, COLLECTION_NAME

def check_qdrant_configuration():
    """检查Qdrant的配置和限制"""
    print("=== 检查Qdrant配置 ===")
    
    try:
        if not qdrant_client:
            print("❌ Qdrant客户端未连接")
            return
        
        # 1. 检查集合配置
        print("1. 检查集合配置...")
        collection_info = qdrant_client.get_collection(COLLECTION_NAME)
        print(f"✅ 集合名称: {COLLECTION_NAME}")
        print(f"   向量数量: {collection_info.points_count}")
        print(f"   向量维度: {collection_info.config.params.vectors.size}")
        print(f"   距离函数: {collection_info.config.params.vectors.distance}")
        
        # 2. 检查HNSW配置
        hnsw_config = collection_info.config.hnsw_config
        print(f"   HNSW配置:")
        print(f"     - m: {hnsw_config.m}")
        print(f"     - ef_construct: {hnsw_config.ef_construct}")
        print(f"     - full_scan_threshold: {hnsw_config.full_scan_threshold}")
        
        # 3. 检查优化器配置
        optimizer_config = collection_info.config.optimizer_config
        print(f"   优化器配置:")
        print(f"     - deleted_threshold: {optimizer_config.deleted_threshold}")
        print(f"     - vacuum_min_vector_number: {optimizer_config.vacuum_min_vector_number}")
        print(f"     - default_segment_number: {optimizer_config.default_segment_number}")
        print(f"     - max_segment_size: {optimizer_config.max_segment_size}")
        print(f"     - memmap_threshold: {optimizer_config.memmap_threshold}")
        print(f"     - indexing_threshold: {optimizer_config.indexing_threshold}")
        print(f"     - flush_interval_sec: {optimizer_config.flush_interval_sec}")
        print(f"     - max_optimization_threads: {optimizer_config.max_optimization_threads}")
        
        # 4. 检查WAL配置
        wal_config = collection_info.config.wal_config
        print(f"   WAL配置:")
        print(f"     - wal_capacity_mb: {wal_config.wal_capacity_mb}")
        print(f"     - wal_segments_ahead: {wal_config.wal_segments_ahead}")
        
        # 5. 检查量化配置(如果有)
        if hasattr(collection_info.config, 'quantization_config') and collection_info.config.quantization_config:
            print(f"   量化配置: {collection_info.config.quantization_config}")
        else:
            print("   量化配置: 未启用")
            
        # 6. 检查集合状态
        print(f"\n2. 检查集合状态...")
        print(f"   状态: {collection_info.status}")
        print(f"   索引状态: {'已建立' if collection_info.indexed_vectors_count > 0 else '未建立'}")
        print(f"   已索引向量数: {collection_info.indexed_vectors_count}")
        
        # 7. 检查最近的点数据
        print(f"\n3. 检查最近数据...")
        recent_points = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=5,
            with_payload=True,
            offset=None
        )
        
        if recent_points[0]:
            print("最近的数据:")
            for point in recent_points[0]:
                session_id = point.payload.get('session_id', 'N/A')
                source_id = point.payload.get('source_id', 'N/A')
                content_preview = point.payload.get('content', '')[:50] + "..."
                print(f"   Point {point.id}: Session={session_id}, Source={source_id}")
                print(f"   Content: {content_preview}")
        
        # 8. 尝试检查是否有TTL或过期设置
        print(f"\n4. 检查服务器信息...")
        try:
            # 注意：不是所有Qdrant版本都支持这个API
            # server_info = qdrant_client.get_collections()
            collections = qdrant_client.get_collections()
            print(f"   总集合数: {len(collections.collections)}")
            for collection in collections.collections:
                print(f"   - {collection.name}: {collection.vectors_count} vectors")
                
        except Exception as e:
            print(f"   无法获取服务器信息: {e}")
            
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_qdrant_configuration()
