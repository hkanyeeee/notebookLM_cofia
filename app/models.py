from sqlalchemy import String, Integer, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime
import pytz
from typing import List

class Base(DeclarativeBase):
    pass

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chunks: Mapped[List["Chunk"]] = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, url='{self.url[:30]}...', session_id='{self.session_id}')>"

class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String, unique=True, index=True)  # 添加chunk_id字段
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<Chunk(id={self.id}, chunk_id={self.chunk_id}, source_id={self.source_id}, session_id='{self.session_id}')>"

class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)  # n8n执行ID
    document_name: Mapped[str] = mapped_column(String(500), nullable=False)  # 文档名称
    workflow_id: Mapped[str] = mapped_column(String, nullable=True)  # n8n工作流ID（可选）
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")  # 执行状态
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(pytz.timezone('Asia/Shanghai')))  # 开始时间
    stopped_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # 结束时间
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)  # 会话ID
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(pytz.timezone('Asia/Shanghai')))

    def __repr__(self) -> str:
        return f"<WorkflowExecution(id={self.id}, execution_id='{self.execution_id}', document_name='{self.document_name}', status='{self.status}')>"

class Config(Base):
    __tablename__ = "configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # 配置项键名
    value: Mapped[str] = mapped_column(Text)  # 配置值（字符串存储，便于处理各种类型）
    type: Mapped[str] = mapped_column(String(50))  # 配置值类型：string, integer, float, boolean
    description: Mapped[str] = mapped_column(Text, nullable=True)  # 配置项描述
    default_value: Mapped[str] = mapped_column(Text)  # 默认值
    is_hot_reload: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否支持热更新
    
    def __repr__(self) -> str:
        return f"<Config(id={self.id}, key='{self.key}', value='{self.value[:50]}...')>"
