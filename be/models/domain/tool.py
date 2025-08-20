from sqlalchemy import Column, String, Enum
from sqlalchemy.dialects.mysql import BIGINT
from db.base import Base
import enum

class Category(enum.Enum):
    knife = "knife"
    scissors = "scissors"
    fire = "fire"
    peeler = "peeler"
    other = "other"

class Tool(Base):
    __tablename__ = "tool"

    tool_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(100), nullable=False)
    category = Column(Enum(Category), nullable=False)
