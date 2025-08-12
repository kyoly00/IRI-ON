from sqlalchemy import Column, String, func
from sqlalchemy.dialects.mysql import BIGINT, SMALLINT, TIMESTAMP, TEXT, DECIMAL
from db.base import Base

class Recipe(Base):
    __tablename__ = "recipe"

    recipe_id = Column(BIGINT, primary_key=True, autoincrement=True, index=True)

    name = Column(String(100), nullable=False, unique=True)
    description = Column(TEXT)
    cooking_time = Column(SMALLINT)
    serving_size = Column(DECIMAL(3, 1))
    instructions = Column(TEXT, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=func.now(), onupdate=func.now())
