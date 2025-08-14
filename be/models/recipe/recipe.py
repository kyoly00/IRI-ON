from sqlalchemy import Column, String, func, Enum
from sqlalchemy.dialects.mysql import BIGINT, SMALLINT, TIMESTAMP, TEXT
from db.base import Base
import enum

class Difficulty(enum.Enum):
    ANY = "아무나"
    EASY = "초급"
    MEDIUM = "중급"
    HARD = "고급"

class Recipe(Base):
    __tablename__ = "recipe"

    recipe_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(100), nullable=False, unique=True)
    description = Column(TEXT)
    image_url = Column(String(255))
    time = Column(SMALLINT)
    servings = Column(SMALLINT)
    difficulty = Column(Enum(Difficulty))
    instructions = Column(TEXT, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())
    tools = Column(TEXT)
    materials = Column(TEXT, nullable=True)
    tips = Column(TEXT)
