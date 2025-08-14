import zipfile
import io
import logging
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from ..models import Source, Chunk
from ..database import get_db
from ..llm_client import generate_answer
# 从配置中导入LLM服务URL
from ..config import LLM_SERVICE_URL

router = APIRouter()

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
        # 1. 获取会话相关的源文档（Source）
        stmt = select(Source).where(Source.session_id == session_id)
        result = await db.execute(stmt)
        sources = result.scalars().all()
        
        if not sources:
            raise HTTPException(status_code=404, detail="No documents found for this session")
        
        # 2. 获取所有相关的chunks
        source_ids = [source.id for source in sources]
        stmt = select(Chunk).where(
            Chunk.source_id.in_(source_ids),
            Chunk.session_id == session_id
        )
        result = await db.execute(stmt)
        chunks = result.scalars().all()
        
        # 3. 生成对话历史（从前端存储的会话数据）
        # 这里需要从数据库中获取对话历史，但当前系统没有专门的对话历史表
        # 我们可以先创建一个简单的实现，返回相关文档信息
        
        # 4. 获取所有相关的文档内容
        document_contents = {}
        for source in sources:
            # 获取该文档的所有chunks
            stmt = select(Chunk).where(
                Chunk.source_id == source.id,
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
            
            content = "\n".join(content_parts)
            document_contents[source.id] = {
                "title": source.title,
                "url": source.url,
                "content": content,
                "chunks_count": len(source_chunks)
            }
        
        # 5. 创建zip文件
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 6. 创建主Markdown文件（对话历史）
            conversation_md = create_conversation_markdown(session_id, sources)
            # 确保Markdown内容是UTF-8编码
            try:
                conversation_md.encode('utf-8')
            except UnicodeEncodeError:
                logger.warning("Conversation markdown contains invalid UTF-8, will be encoded with error handling")
                conversation_md = conversation_md.encode('utf-8', errors='replace').decode('utf-8')
            
            zip_file.writestr(f"conversation_{session_id}.md", conversation_md)
            
            # 7. 为每个文档创建概述文件
            for i, (source_id, doc_info) in enumerate(document_contents.items()):
                # 8. 使用大模型生成文档概述
                summary = await generate_document_summary(doc_info["content"])
                
                # 9. 创建文档概述文件
                doc_md = create_document_markdown(
                    source_id, 
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
        
        # 10. 返回zip文件
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

def create_conversation_markdown(session_id: str, sources: List[Source]) -> str:
    """
    创建对话历史的Markdown文件
    """
    markdown_content = f"# 对话历史导出 (会话 ID: {session_id})\n\n"
    markdown_content += f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    markdown_content += "## 相关文档列表\n\n"
    
    for i, source in enumerate(sources, 1):
        markdown_content += f"{i}. [{source.title}]({source.url})\n"
    
    # 注意：由于系统中没有专门的对话历史存储，这里返回一个占位符
    markdown_content += "\n## 对话历史\n\n"
    markdown_content += "（当前系统没有专门存储对话历史，此部分为空）\n\n"
    markdown_content += "## 关联说明\n\n"
    markdown_content += "此导出包含会话相关的文档内容和其概述。\n\n"
    
    return markdown_content

def create_document_markdown(
    source_id: int, 
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
    
    markdown_content += f"## 关联链接\n\n"
    markdown_content += f"- [查看完整文档](document_{source_id}_{index}.md)\n"
    markdown_content += f"- [返回对话历史](conversation_{source_id}.md)\n\n"
    
    markdown_content += f"## 完整内容预览\n\n"
    # 限制预览内容长度并处理编码
    preview_content = full_content[:1000] if full_content else ""
    try:
        preview_content.encode('utf-8')
    except UnicodeEncodeError:
        preview_content = preview_content.encode('utf-8', errors='replace').decode('utf-8')
    
    markdown_content += f"```\n{preview_content}...\n```\n"
    
    return markdown_content
