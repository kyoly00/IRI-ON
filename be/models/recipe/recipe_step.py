from sqlalchemy import Column, ForeignKey, String, TEXT
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import relationship
from db.base import Base

class RecipeStep(Base):
    __tablename__ = "recipe_step"

    recipe_id = Column(BIGINT, ForeignKey("recipe.recipe_id"), primary_key=True)
    step = Column(TINYINT, primary_key=True)
    text = Column(TEXT)  # 단계 설명 텍스트
    url = Column(String(255))

    recipe = relationship("Recipe", backref="recipe_steps")
