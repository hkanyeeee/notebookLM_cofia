import zipfile
import io
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..models import Source, Chunk
from ..database import get_db
from ..llm_client import generate_answer
# 从配置中导入LLM服务URL
from ..config import LLM_SERVICE_URL

router = APIRouter()

# 对话消息的Pydantic模型
class Message(BaseModel):
    id: str
    type: str  # 'user' 或 'assistant'
    content: str
    timestamp: datetime
    sources: Optional[List[Dict]] = None

# 对话历史的Pydantic模型
class ConversationExportRequest(BaseModel):
    messages: List[Message]

# 用于存储对话历史的简单模型（基于现有结构）
class ConversationMessage:
    def __init__(self, id: str, type: str, content: str, timestamp: datetime, sources: List[Dict] = None):
        self.id = id
        self.type = type
        self.content = content
        self.timestamp = timestamp
        self.sources = sources or []

# 配置日志记录
logger = logging.getLogger(__name__)

@router.post("/export/conversation/{session_id}", summary="Export conversation history and related documents to zip")
async def export_conversation(
    session_id: str,
    data: ConversationExportRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    导出对话历史和相关文档到zip压缩包
    包含：
    1. 主Markdown文件：对话历史（Obsidian语法）
    2. 相关文档概述文件
    3. 所有文件打包成zip
    """
    
    try:
        # 1. 获取对话中相关的chunks（从messages中的sources信息）
        all_chunk_sources = []
        for message in data.messages:
            if message.sources:
                all_chunk_sources.extend(message.sources)
        
        # 去重并限制为top5个chunks
        unique_sources = {}
        chunk_ids = []  # 新增：用于存储chunk_id列表
        for source in all_chunk_sources:
            # 使用chunk_id作为唯一标识
            chunk_id = source.get('id') or source.get('chunk_id')
            if chunk_id and chunk_id not in unique_sources:
                unique_sources[chunk_id] = source
                chunk_ids.append(chunk_id)
        
        # 限制为top5个
        top5_sources = list(unique_sources.values())[:5]
        
        # 2. 根据chunk_id获取chunks（修改这里，直接用chunk_id查询）
        if chunk_ids:
            stmt = select(Chunk).where(
                Chunk.chunk_id.in_(chunk_ids),
                Chunk.session_id == session_id
            )
            result = await db.execute(stmt)
            chunks = result.scalars().all()
        else:
            # 如果没有找到相关chunk，使用session_id直接查询chunks
            stmt = select(Chunk).where(Chunk.session_id == session_id)
            result = await db.execute(stmt)
            chunks = result.scalars().all()
        
        # 3. 获取所有相关的文档内容
        document_contents = {}
        # 创建一个映射：chunk_id -> source_id，用于正确关联
        chunk_to_source_map = {}
        for source in top5_sources:
            source_id = source.get('id') or source.get('source_id')
            chunk_id = source.get('id') or source.get('chunk_id')
            if chunk_id:
                chunk_to_source_map[chunk_id] = source_id
        
        for source in top5_sources:
            # 获取该source的所有chunks
            source_id = source.get('id') or source.get('source_id')
            
            # 通过chunk_id来查找相关chunks，而不是source_id
            stmt = select(Chunk).where(
                Chunk.source_id == source_id,
                Chunk.session_id == session_id
            )
            result = await db.execute(stmt)
            source_chunks = result.scalars().all()
            
            # 合并文档内容，处理潜在的编码问题
            content_parts = []
            for chunk in source_chunks:
                try:
                    # 尝试直接使用内容
                    content_parts.append(chunk.content)
                except Exception as e:
                    logger.warning(f"Error processing chunk content: {e}")
                    # 如果有编码错误，跳过该chunk或用占位符替代
                    content_parts.append("[无法读取的文档内容]")
            
            # 获取正确的source信息，包括url
            title = source.get('title', 'Untitled')
            
            # 从第一个chunk中获取url信息（因为所有chunk应该来自同一个source）
            url = source.get('url', '')
            if not url and source_chunks:
                # 如果前端没有提供url，尝试从source表获取
                stmt = select(Source).where(Source.id == source_id)
                result = await db.execute(stmt)
                source_obj = result.scalar_one_or_none()
                if source_obj:
                    url = source_obj.url
            
            document_contents[source_id] = {
                "title": title,
                "url": url,
                "content": "\n".join(content_parts),
                "chunks_count": len(source_chunks)
            }
        
        # 4. 创建zip文件
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 5. 创建主Markdown文件（对话历史）
            conversation_md = create_conversation_markdown(session_id, top5_sources, data.messages)
            # 确保Markdown内容是UTF-8编码
            try:
                conversation_md.encode('utf-8')
            except UnicodeEncodeError:
                logger.warning("Conversation markdown contains invalid UTF-8, will be encoded with error handling")
                conversation_md = conversation_md.encode('utf-8', errors='replace').decode('utf-8')
            
            zip_file.writestr(f"conversation_{session_id}.md", conversation_md)
            
            # 6. 为每个文档创建概述文件
            for i, (source_id, doc_info) in enumerate(document_contents.items()):
                # 7. 使用大模型生成文档概述
                summary = await generate_document_summary(doc_info["content"])
                
                # 8. 创建文档概述文件
                # 获取chunk_id而不是source_id，确保正确显示chunk的id
                chunk_id_for_display = None
                for source in top5_sources:
                    if (source.get('id') or source.get('source_id')) == source_id:
                        chunk_id_for_display = source.get('id') or source.get('chunk_id')
                        break
                
                doc_md = create_document_markdown(
                    session_id,
                    chunk_id_for_display or source_id, 
                    i, 
                    doc_info["title"], 
                    doc_info["url"], 
                    summary,
                    doc_info["content"]
                )
                
                # 确保文档内容是UTF-8编码
                try:
                    doc_md.encode('utf-8')
                except UnicodeEncodeError:
                    logger.warning("Document markdown contains invalid UTF-8, will be encoded with error handling")
                    doc_md = doc_md.encode('utf-8', errors='replace').decode('utf-8')
                
                zip_file.writestr(f"document_{source_id}_{i}.md", doc_md)
        
        # 9. 返回zip文件
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=\"conversation_export_{session_id}.zip\""
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

async def generate_document_summary(content: str) -> str:
    """
    使用大模型生成文档概述
    """
    # 限制输入长度以避免超出模型上下文
    truncated_content = content[:3000] if len(content) > 3000 else content
    
    prompt = f"""
    请为以下文档内容生成一个简洁明了的概述，包含：
    1. 文档的核心主题
    2. 关键要点
    3. 主要结论或建议
    
    文档内容：
    {truncated_content}
    """
    
    try:
        summary = await generate_answer(prompt, [])
        return summary
    except Exception as e:
        return f"无法生成概述: {str(e)}"

def create_conversation_markdown(session_id: str, sources: List[Dict], messages: List[Message]) -> str:
    """
    创建对话历史的Markdown文件
    """
    markdown_content = f"# 对话历史导出 (会话 ID: {session_id})\n\n"
    markdown_content += f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    markdown_content += "## 相关文档列表\n\n"
    
    for i, source in enumerate(sources, 1):
        # 修改：使用正确的文件名格式指向文档概述文件
        source_id = source.get('id') or source.get('source_id', i)
        source_title = source.get('title', f'Untitled Document {i}')
        markdown_content += f"{i}. [{source_title}](document_{source_id}_{i-1}.md)\n"
    
    # 添加对话历史
    markdown_content += "\n## 对话历史\n\n"
    
    if not messages:
        markdown_content += "（当前会话中没有对话记录）\n\n"
    else:
        for message in messages:
            # 根据消息类型添加不同的格式
            if message.type == 'user':
                markdown_content += f"**用户**: {message.content}\n\n"
            elif message.type == 'assistant':
                markdown_content += f"**助手**: {message.content}\n\n"
            # 添加时间戳（如果需要的话）
            # markdown_content += f"时间: {message.timestamp}\n\n"
    
    markdown_content += "## 关联说明\n\n"
    markdown_content += "此导出包含会话相关的文档内容和对话历史。\n\n"
    
    return markdown_content

def create_document_markdown(
    session_id: str,
    source_id: str, 
    index: int, 
    title: str, 
    url: str, 
    summary: str,
    full_content: str
) -> str:
    """
    创建文档概述的Markdown文件
    """
    # 处理可能包含非法字符的内容
    safe_title = title.encode('utf-8', errors='replace').decode('utf-8') if title else "Untitled"
    safe_url = url.encode('utf-8', errors='replace').decode('utf-8') if url else ""
    safe_summary = summary.encode('utf-8', errors='replace').decode('utf-8') if summary else ""
    
    markdown_content = f"# 文档概述\n\n"
    markdown_content += f"## 基本信息\n\n"
    markdown_content += f"- **ID**: {source_id}\n"
    markdown_content += f"- **标题**: {safe_title}\n"
    markdown_content += f"- **URL**: [{safe_url}]({safe_url})\n\n"
    
    markdown_content += f"## 概述\n\n"
    markdown_content += f"{safe_summary}\n\n"
    
    # 移除"查看完整文档"的关联链接，只保留概述
    markdown_content += f"## 关联说明\n\n"
    markdown_content += f"此文档概述由大模型生成，包含核心主题、关键要点和主要结论。\n\n"
    
    markdown_content += f"## 完整内容预览\n\n"
    # 限制预览内容长度并处理编码
    preview_content = full_content[:1000] if full_content else ""
    try:
        preview_content.encode('utf-8')
    except UnicodeEncodeError:
        preview_content = preview_content.encode('utf-8', errors='replace').decode('utf-8')
    
    markdown_content += f"```\n{preview_content}...\n```\n"
    
    return markdown_content
