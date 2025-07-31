from sqlalchemy import Column, Integer, String, Text
from app.database import Base

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    content = Column(Text)