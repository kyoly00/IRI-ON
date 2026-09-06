from sqlalchemy import Column, ForeignKey, Integer, String, TEXT
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import relationship
from db.base import Base

class RecipeStep(Base):
    __tablename__ = "recipe_step"

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)
    step = Column(TINYINT, primary_key=True)
    text = Column(TEXT)  # 단계 설명 텍스트
    url = Column(String(255))
    video_id = Column(String(32), nullable=True, index=True)
    start_url = Column(String(512), nullable=True)
    start_seconds = Column(Integer, nullable=True)
    step_len = Column(Integer, nullable=True)

    recipe = relationship("Recipe", backref="recipe_steps")
