import zipfile
import io
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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


# 配置日志记录
logger = logging.getLogger(__name__)

@router.post("/export/conversation/{session_id}", summary="Export conversation history and related documents to zip")
async def export_conversation(
    session_id: str,
    data: ConversationExportRequest
):
    """
    导出对话历史和相关文档到zip压缩包
    包含：
    1. 主Markdown文件：对话历史（Obsidian语法）
    2. 相关文档概述文件
    3. 所有文件打包成zip
    """
    
    try:
        # 1. 直接使用前端传递的sources信息（已包含所有需要的数据）
        # 由于前端已经处理好数据，这里直接使用data.messages中的sources
        all_chunk_sources = []
        for message in data.messages:
            if message.sources:
                # 只保留每个消息的top5 sources，按score降序排列
                sorted_sources = sorted(message.sources, key=lambda x: x.get('score', 0), reverse=True)
                top5_sources = sorted_sources[:5]
                all_chunk_sources.extend(top5_sources)
        
        # 2. 获取所有相关的文档内容 - 直接使用前端传来的数据
        document_contents = {}
        
        # 遍历所有chunk sources，直接使用前端传递的数据
        for i, source in enumerate(all_chunk_sources):
            # 获取该source的文档内容
            content = source.get('content', '')
            
            # 获取正确的source信息，包括url
            title = source.get('title', 'Untitled')
            url = source.get('url', '')
            
            # 获取chunk_id（使用id或chunkId字段）
            chunk_id = source.get('id') or source.get('chunkId', f'chunk_{i}')
            
            document_contents[chunk_id] = {
                "title": title,
                "url": url,
                "content": content,
                "chunks_count": 1  # 前端已处理好，这里简化为1
            }
        
        # 4. 创建zip文件
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 5. 创建主Markdown文件（对话历史）
            conversation_md = create_conversation_markdown(session_id, all_chunk_sources, data.messages)
            # 确保Markdown内容是UTF-8编码
            try:
                conversation_md.encode('utf-8')
            except UnicodeEncodeError:
                logger.warning("Conversation markdown contains invalid UTF-8, will be encoded with error handling")
                conversation_md = conversation_md.encode('utf-8', errors='replace').decode('utf-8')
            
            zip_file.writestr(f"conversation_{session_id}.md", conversation_md)
            
            # 6. 为每个文档创建概述文件
            for i, (chunk_id, doc_info) in enumerate(document_contents.items()):
                # 7. 使用大模型生成文档概述
                summary = await generate_document_summary(doc_info["content"])
                
                # 8. 创建文档概述文件
                doc_md = create_document_markdown(
                    session_id,
                    chunk_id, 
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
                
                zip_file.writestr(f"document_{chunk_id}_{i}.md", doc_md)
        
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
    # markdown_content += "## 相关文档列表\n\n"
    
    # for i, source in enumerate(sources, 1):
    #     # 修改：使用正确的文件名格式指向文档概述文件
    #     source_id = source.get('id') or source.get('source_id', i)
    #     source_title = source.get('title', f'Untitled Document {i}')
    #     markdown_content += f"{i}. [{source_title}](document_{source_id}_{i-1}.md)\n"
    
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
                # 添加相关文档列表，仅针对该助手回复的来源
                if message.sources:
                    markdown_content += "相关文档:\n\n"
                    # 只保留每个消息的top5 sources，按score降序排列
                    sorted_sources = sorted(message.sources, key=lambda x: x.get('score', 0), reverse=True)
                    top5_sources = sorted_sources[:5]
                    for j, source in enumerate(top5_sources, 1):
                        source_id = source.get('id') or source.get('source_id', j)
                        source_title = source.get('title', f'Untitled Document {j}')
                        markdown_content += f"{j}. [{source_title}](document_{source_id}_{j-1}.md)\n"
                    markdown_content += "\n"
            # 添加时间戳（如果需要的话）
            # markdown_content += f"时间: {message.timestamp}\n\n"
    
    markdown_content += "## 关联说明\n\n"
    markdown_content += "此导出包含会话相关的文档内容和对话历史。\n\n"
    
    return markdown_content

def create_document_markdown(
    session_id: str,
    chunk_id: str, 
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
    
    # 截取内容预览（限制长度）
    preview_content = full_content[:500] if len(full_content) > 500 else full_content
    
    markdown_content = f"# 文档概述\n\n"
    markdown_content += f"## 基本信息\n\n"
    markdown_content += f"- **ID**: {chunk_id}\n"
    markdown_content += f"- **标题**: {safe_title}\n"
    markdown_content += f"- **URL**: [{safe_url}]({safe_url})\n\n"
    
    markdown_content += f"## 概述\n\n"
    markdown_content += f"{safe_summary}\n\n"
    
    markdown_content += f"## 关联链接\n\n"
    markdown_content += f"- [返回对话历史](conversation_{session_id}.md)\n\n"
    
    try:
        preview_content.encode('utf-8')
    except UnicodeEncodeError:
        preview_content = preview_content.encode('utf-8', errors='replace').decode('utf-8')
    
    markdown_content += f"```\n{preview_content}...\n```\n"
    
    return markdown_content
