from sqlalchemy import String, Integer, Text, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime
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
