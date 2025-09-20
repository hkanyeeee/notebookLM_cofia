#!/usr/bin/env python3
"""
通用向量数据库数据修复脚本
支持修复指定集合或全部集合的向量数据
"""
import asyncio
import argparse
from typing import List, Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Source, Chunk
from app.embedding_client import embed_texts
from app.vector_db_client import add_embeddings, qdrant_client, COLLECTION_NAME, delete_vector_db_data
from app.config import EMBEDDING_BATCH_SIZE, EMBEDDING_DIMENSIONS, DEFAULT_EMBEDDING_MODEL


class VectorDataFixer:
    """向量数据修复器"""

    def __init__(self, session_id: str, force_regenerate: bool = False, dry_run: bool = False):
        self.session_id = session_id
        self.force_regenerate = force_regenerate
        self.dry_run = dry_run
        self.stats = {
            'processed_collections': 0,
            'total_chunks': 0,
            'generated_embeddings': 0,
            'errors': 0
        }

    async def list_collections(self) -> List[Dict[str, Any]]:
        """列出所有可修复的集合"""
        print("=== 扫描所有集合 ===")

        async for db in get_db():
            try:
                # 获取所有Source
                sources_stmt = select(Source).where(Source.session_id == self.session_id)
                sources_result = await db.execute(sources_stmt)
                sources = sources_result.scalars().all()

                collections = []
                for source in sources:
                    # 获取每个source的chunks数量
                    chunks_stmt = select(Chunk).where(
                        Chunk.source_id == source.id,
                        Chunk.session_id == self.session_id
                    )
                    chunks_result = await db.execute(chunks_stmt)
                    chunks_count = len(chunks_result.scalars().all())

                    # 检查Qdrant中是否已有向量数据
                    try:
                        search_result = qdrant_client.scroll(
                            collection_name=COLLECTION_NAME,
                            scroll_filter={
                                "must": [
                                    {"key": "source_id", "match": {"value": source.id}},
                                    {"key": "session_id", "match": {"value": self.session_id}}
                                ]
                            },
                            limit=1
                        )
                        qdrant_count = len(search_result[0])
                    except Exception:
                        qdrant_count = 0

                    collections.append({
                        'id': source.id,
                        'title': source.title,
                        'chunks_count': chunks_count,
                        'qdrant_count': qdrant_count,
                        'needs_fix': chunks_count > 0 and (qdrant_count == 0 or self.force_regenerate)
                    })

                print(f"✅ 找到 {len(collections)} 个集合")
                return collections

            except Exception as e:
                print(f"❌ 扫描集合失败: {e}")
                return []

    async def fix_collection(self, collection_id: int) -> bool:
        """修复指定集合的向量数据"""
        print(f"\n=== 修复Collection {collection_id} ===")

        async for db in get_db():
            try:
                # 1. 获取Collection信息
                print(f"1. 获取Collection {collection_id}的信息...")
                source_stmt = select(Source).where(
                    Source.id == collection_id,
                    Source.session_id == self.session_id
                )
                source_result = await db.execute(source_stmt)
                source = source_result.scalar_one_or_none()

                if not source:
                    print(f"❌ Collection {collection_id} 不存在")
                    return False

                print(f"✅ 找到Collection: {source.title}")

                # 2. 检查是否需要修复
                if not self.force_regenerate:
                    try:
                        search_result = qdrant_client.scroll(
                            collection_name=COLLECTION_NAME,
                            scroll_filter={
                                "must": [
                                    {"key": "source_id", "match": {"value": source.id}},
                                    {"key": "session_id", "match": {"value": self.session_id}}
                                ]
                            },
                            limit=1
                        )
                        if len(search_result[0]) > 0:
                            print(f"ℹ️ Collection {collection_id} 已有向量数据，跳过")
                            return True
                    except Exception:
                        pass  # 如果检查失败，继续处理

                # 在重建前清理该集合在 Qdrant 的历史向量，避免旧数据残留
                try:
                    await delete_vector_db_data([source.id])
                except Exception as e:
                    print(f"清理旧向量失败（跳过继续）: {e}")

                # 3. 获取所有chunks
                print("2. 获取chunks...")
                chunks_stmt = select(Chunk).where(
                    Chunk.source_id == source.id,
                    Chunk.session_id == self.session_id
                )
                chunks_result = await db.execute(chunks_stmt)
                chunks = chunks_result.scalars().all()

                print(f"✅ 找到 {len(chunks)} 个chunks")

                if not chunks:
                    print("❌ 没有chunks需要处理")
                    return False

                # 4. 分批处理embeddings
                if self.dry_run:
                    print(f"📋 [DRY RUN] 预估处理 {len(chunks)} 个chunks")
                    self.stats['generated_embeddings'] += len(chunks)
                    self.stats['processed_collections'] += 1
                    return True

                print(f"3. 开始生成embeddings (批次大小: {EMBEDDING_BATCH_SIZE})...")
                batch_size = EMBEDDING_BATCH_SIZE
                total_batches = (len(chunks) + batch_size - 1) // batch_size

                for batch_index in range(total_batches):
                    start_idx = batch_index * batch_size
                    end_idx = min((batch_index + 1) * batch_size, len(chunks))
                    batch_chunks = chunks[start_idx:end_idx]

                    print(f"处理批次 {batch_index + 1}/{total_batches}: {len(batch_chunks)} chunks")

                    # 提取文本内容
                    batch_texts = [chunk.content for chunk in batch_chunks]

                    try:
                        # 生成embeddings
                        embeddings = await embed_texts(
                            texts=batch_texts,
                            model=DEFAULT_EMBEDDING_MODEL,
                            batch_size=EMBEDDING_BATCH_SIZE,
                            dimensions=EMBEDDING_DIMENSIONS
                        )

                        if not embeddings or len(embeddings) != len(batch_chunks):
                            print(f"❌ 批次 {batch_index + 1} embedding生成失败或数量不匹配")
                            self.stats['errors'] += 1
                            continue

                        # 存储到Qdrant
                        await add_embeddings(source.id, batch_chunks, embeddings)
                        print(f"✅ 批次 {batch_index + 1} 存储完成")

                        self.stats['generated_embeddings'] += len(batch_chunks)

                    except Exception as e:
                        print(f"❌ 批次 {batch_index + 1} 处理失败: {e}")
                        self.stats['errors'] += 1
                        continue

                print(f"✅ Collection {collection_id} 向量数据修复完成！")
                self.stats['processed_collections'] += 1
                self.stats['total_chunks'] += len(chunks)
                return True

            except Exception as e:
                print(f"❌ 修复Collection {collection_id} 失败: {e}")
                self.stats['errors'] += 1
                import traceback
                traceback.print_exc()
                return False

    async def fix_all_collections(self) -> None:
        """修复所有需要修复的集合"""
        collections = await self.list_collections()

        if not collections:
            return

        # 显示需要修复的集合
        need_fix = [c for c in collections if c['needs_fix']]
        if not need_fix:
            print("ℹ️ 所有集合都已有向量数据，无需修复")
            return

        print(f"\n需要修复的集合: {len(need_fix)} 个")
        for collection in need_fix:
            print(f"  - ID: {collection['id']}, 标题: {collection['title']}, Chunks: {collection['chunks_count']}")

        # 逐个修复
        for collection in need_fix:
            await self.fix_collection(collection['id'])

    async def verify_collection(self, collection_id: int) -> Dict[str, Any]:
        """验证集合的向量数据"""
        print(f"\n=== 验证Collection {collection_id} ===")

        result = {
            'collection_id': collection_id,
            'db_chunks': 0,
            'qdrant_points': 0,
            'status': 'unknown'
        }

        try:
            async for db in get_db():
                # 获取数据库中的chunks数量
                chunks_stmt = select(Chunk).where(
                    Chunk.source_id == collection_id,
                    Chunk.session_id == self.session_id
                )
                chunks_result = await db.execute(chunks_stmt)
                chunks = chunks_result.scalars().all()
                result['db_chunks'] = len(chunks)

            # 获取Qdrant中的数据
            search_result = qdrant_client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter={
                    "must": [
                        {"key": "source_id", "match": {"value": collection_id}},
                        {"key": "session_id", "match": {"value": self.session_id}}
                    ]
                },
                limit=1000,  # 获取更多记录用于统计
                with_payload=True
            )

            result['qdrant_points'] = len(search_result[0])

            if result['db_chunks'] == result['qdrant_points']:
                result['status'] = 'complete'
            elif result['qdrant_points'] == 0:
                result['status'] = 'missing'
            else:
                result['status'] = 'partial'

            print(f"数据库chunks: {result['db_chunks']}")
            print(f"Qdrant向量: {result['qdrant_points']}")
            print(f"状态: {result['status']}")

            if search_result[0]:
                print("前3条记录预览:")
                for i, point in enumerate(search_result[0][:3]):
                    content_preview = point.payload.get('content', '')[:80] + "..."
                    print(f"  {i+1}. Point {point.id}: {content_preview}")

        except Exception as e:
            print(f"❌ 验证失败: {e}")
            result['status'] = 'error'

        return result

    def print_stats(self):
        """打印统计信息"""
        print("\n=== 修复统计 ===")
        print(f"处理集合数: {self.stats['processed_collections']}")
        print(f"处理chunks总数: {self.stats['total_chunks']}")
        print(f"生成embeddings数: {self.stats['generated_embeddings']}")
        print(f"错误次数: {self.stats['errors']}")


async def main():
    parser = argparse.ArgumentParser(description="向量数据库数据修复工具")
    # 默认使用与 agenttic_ingest 一致的固定 Session ID，用户无需理解/传递
    parser.add_argument(
        "--session-id",
        required=False,
        default="fixed_session_id_for_agenttic_ingest",
        help="Session ID（可选，默认与 agenttic_ingest 一致）",
    )
    parser.add_argument("--collection-id", type=int, help="指定修复的集合ID")
    parser.add_argument("--all", action="store_true", help="修复所有需要修复的集合")
    parser.add_argument("--list", action="store_true", help="列出所有集合状态")
    parser.add_argument("--verify", type=int, help="验证指定集合的状态")
    parser.add_argument("--force", action="store_true", help="强制重新生成所有向量数据")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际执行")

    args = parser.parse_args()

    if not any([args.collection_id, args.all, args.list, args.verify]):
        parser.error("必须指定 --collection-id、--all、--list 或 --verify 中的一个")

    fixer = VectorDataFixer(
        session_id=args.session_id,
        force_regenerate=args.force,
        dry_run=args.dry_run
    )

    try:
        if args.list:
            collections = await fixer.list_collections()
            print("\n=== 集合状态详情 ===")
            for collection in collections:
                status_icon = "✅" if collection['qdrant_count'] > 0 else "❌"
                needs_fix_icon = "🔧" if collection['needs_fix'] else "✓"
                print(f"{status_icon} {needs_fix_icon} ID: {collection['id']}, "
                      f"标题: {collection['title']}, "
                      f"Chunks: {collection['chunks_count']}, "
                      f"向量: {collection['qdrant_count']}")

        elif args.verify:
            result = await fixer.verify_collection(args.verify)

        elif args.collection_id:
            success = await fixer.fix_collection(args.collection_id)
            if success:
                # 验证修复结果
                await fixer.verify_collection(args.collection_id)

        elif args.all:
            await fixer.fix_all_collections()

        fixer.print_stats()

    except KeyboardInterrupt:
        print("\n⚠️ 操作被用户中断")
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
