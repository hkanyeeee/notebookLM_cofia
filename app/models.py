from sqlalchemy import Column, Integer, String, Text
from app.database import Base

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(500), index=True)  # 添加长度限制
    content = Column(Text)